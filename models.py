"""
models.py
---------
Defines the shape of student data using Pydantic models.

Pydantic's job: When FastAPI receives a JSON request body, it hands the raw
data to Pydantic. Pydantic checks that every field has the right type and
passes your custom validation rules. If anything fails, Pydantic automatically
returns a clear 422 error to the caller.

Three models are defined here:
  1. StudentCreate   — for POST /students/ (creating a new student)
  2. StudentUpdate   — for PUT  /students/{id} (updating an existing student)
  3. StudentResponse — for all responses that return student data

NOTE ON EXPLICIT NULL IN StudentUpdate
---------------------------------------
Pydantic 2 distinguishes between a field that was omitted from the request
body and a field that was explicitly set to null (JSON null / Python None).

  {"name": "Alice"}          → name is set, email/phone/dob were omitted
  {"email": null}            → email was explicitly set to null

We use `model_fields_set` (the set of field names that the caller actually
included) to tell these apart. This matters in crud.py:

  - Omitted fields  → do not touch the existing database value
  - Explicit null   → set the column to NULL in the database (clear the value)

IMPORTANT: crud.py's update function is responsible for checking that after
applying all changes, the record still has at least one contact method
(email or phone). models.py cannot do that check because it only sees the
incoming delta, not the current database state. That guard belongs in crud.py.
"""

import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator, model_validator

# Compiled once at module load — matches exactly YYYY-MM-DD with 4-2-2 digits.
# We use this in addition to strptime because strptime("%Y-%m-%d") accepts
# single-digit months and days on some platforms (e.g. "2003-6-5").
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# 1. StudentCreate — used when creating a new student record
# ---------------------------------------------------------------------------
class StudentCreate(BaseModel):
    """
    Validates the request body for POST /students/.

    Required fields:  student_id, name, date_of_birth
    Optional fields:  email, phone  (but at least one must be non-empty)
    """

    student_id: str
    """
    Unique identifier for the student, e.g. "STU001".
    Required. Whitespace is stripped. Cannot be blank after stripping.
    """

    name: str
    """
    Full name of the student, e.g. "Alice Johnson".
    Required. Whitespace is stripped. Must have at least 2 characters after stripping.
    """

    date_of_birth: str
    """
    Birth date in exactly "YYYY-MM-DD" format, e.g. "2003-06-15".
    Must be a real calendar date. Must not be in the future.
    Stored as TEXT in SQLite.
    """

    email: Optional[EmailStr] = None
    """
    Optional email address. When provided, EmailStr checks the format
    (requires an @ sign, valid domain, etc.) using the email-validator package.
    """

    phone: Optional[str] = None
    """
    Optional phone number stored as plain text.
    Whitespace is stripped. A blank or whitespace-only value is rejected.
    """

    # ------------------------------------------------------------------
    # Field validator: student_id
    # ------------------------------------------------------------------
    @field_validator("student_id")
    @classmethod
    def student_id_not_blank(cls, value: str) -> str:
        """
        Strips surrounding whitespace, then rejects an empty result.
        "  " would pass Pydantic's `str` type check but is not a valid ID.
        """
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("student_id cannot be blank.")
        return cleaned

    # ------------------------------------------------------------------
    # Field validator: name
    # ------------------------------------------------------------------
    @field_validator("name")
    @classmethod
    def name_min_length(cls, value: str) -> str:
        """
        Strips surrounding whitespace, then requires at least 2 characters.
        Rejects " A ", "  ", or any single-character name.
        """
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError(
                "name must contain at least 2 non-whitespace characters."
            )
        return cleaned

    # ------------------------------------------------------------------
    # Field validator: date_of_birth
    # ------------------------------------------------------------------
    @field_validator("date_of_birth")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        """
        Two-stage check:

        Stage 1 — Regex: confirms the string is exactly 10 characters in the
        pattern YYYY-MM-DD (4 digits, hyphen, 2 digits, hyphen, 2 digits).
        This rejects "2003-6-5" and "03-06-2003" before strptime even runs.

        Stage 2 — strptime: parses the string as a real calendar date.
        This rejects impossible dates like "2003-02-30" (Feb has no 30th)
        or "2003-13-01" (month 13 does not exist).

        After both checks pass, we also reject future dates.
        """
        # Stage 1: strict format check
        if not _DATE_PATTERN.match(value):
            raise ValueError(
                "date_of_birth must be in exactly YYYY-MM-DD format "
                "with zero-padded month and day (e.g. '2003-06-15', not '2003-6-5')."
            )

        # Stage 2: real calendar date check
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(
                "date_of_birth is not a valid calendar date "
                "(e.g. '2003-02-30' does not exist)."
            )

        # Sanity check: a date of birth cannot be in the future
        if parsed > date.today():
            raise ValueError("date_of_birth cannot be in the future.")

        return value  # Return the original string — SQLite stores it as TEXT

    # ------------------------------------------------------------------
    # Field validator: phone
    # ------------------------------------------------------------------
    @field_validator("phone")
    @classmethod
    def phone_not_blank(cls, value: Optional[str]) -> Optional[str]:
        """
        If phone is provided, strip whitespace and reject a blank result.
        Passing phone="   " should not count as providing a phone number.
        Pydantic 2 skips this validator entirely when phone is None (omitted).
        """
        if value is not None:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError(
                    "phone cannot be blank. Omit the field or provide a real number."
                )
            return cleaned
        return value

    # ------------------------------------------------------------------
    # Model validator: at least one of email or phone must be non-empty
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def require_email_or_phone(self) -> "StudentCreate":
        """
        Runs after all field validators succeed, so self.email and self.phone
        are already cleaned and valid (or None).

        At least one must be present and non-empty. Both None means no way
        to contact the student.
        """
        if not self.email and not self.phone:
            raise ValueError(
                "At least one contact method is required: "
                "provide email, phone, or both."
            )
        return self


# ---------------------------------------------------------------------------
# 2. StudentUpdate — used when updating an existing student record
# ---------------------------------------------------------------------------
class StudentUpdate(BaseModel):
    """
    Validates the request body for PUT /students/{student_id}.

    Every field is Optional so callers only send what they want to change.
    Fields omitted from the request are not touched in the database.

    IMPORTANT — omitted vs. explicit null
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Pydantic 2 tracks which fields were actually included in the request
    via `model_fields_set`. This is how crud.py will know what to do:

      Caller sends: {"name": "Alice"}
        → model_fields_set = {"name"}
        → Only name is updated. email/phone/dob columns stay as they are.

      Caller sends: {"email": null}
        → model_fields_set = {"email"}
        → email column is set to NULL (cleared).
        → crud.py must then check: does the record still have a phone?
          If not, it must reject the update with a 422 error.

      Caller sends: {}
        → model_fields_set = set()
        → Rejected here with a 422 — nothing to update.

    student_id is intentionally absent. The URL path (/students/STU001)
    identifies which record to update. Changing a primary key through
    the body would create ambiguity and is not allowed.

    CONTACT METHOD GUARD (handled in crud.py, not here):
    After applying the update, crud.py must verify that at least one of
    email or phone remains non-null for the record. models.py cannot do
    this check because it only sees the incoming fields, not the current
    database state.
    """

    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    # ------------------------------------------------------------------
    # Field validator: name
    # ------------------------------------------------------------------
    @field_validator("name")
    @classmethod
    def name_min_length(cls, value: Optional[str]) -> Optional[str]:
        """
        Pydantic 2 skips this when name is None (omitted).
        When provided, applies the same 2-character rule as StudentCreate.
        """
        if value is not None:
            cleaned = value.strip()
            if len(cleaned) < 2:
                raise ValueError(
                    "name must contain at least 2 non-whitespace characters."
                )
            return cleaned
        return value

    # ------------------------------------------------------------------
    # Field validator: date_of_birth
    # ------------------------------------------------------------------
    @field_validator("date_of_birth")
    @classmethod
    def validate_date_format(cls, value: Optional[str]) -> Optional[str]:
        """
        Pydantic 2 skips this when date_of_birth is None (omitted).
        When provided, applies the same two-stage check as StudentCreate.
        """
        if value is not None:
            if not _DATE_PATTERN.match(value):
                raise ValueError(
                    "date_of_birth must be in exactly YYYY-MM-DD format "
                    "with zero-padded month and day (e.g. '2003-06-15', not '2003-6-5')."
                )
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(
                    "date_of_birth is not a valid calendar date "
                    "(e.g. '2003-02-30' does not exist)."
                )
            if parsed > date.today():
                raise ValueError("date_of_birth cannot be in the future.")
        return value

    # ------------------------------------------------------------------
    # Field validator: phone
    # ------------------------------------------------------------------
    @field_validator("phone")
    @classmethod
    def phone_not_blank(cls, value: Optional[str]) -> Optional[str]:
        """
        If phone is explicitly provided as a non-null string, strip whitespace
        and reject a blank result.

        Note: phone=None (explicit null) is allowed here — the caller is
        deliberately clearing the phone number. crud.py is responsible for
        checking that the record still has at least one contact method after
        the update.
        """
        if value is not None:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError(
                    "phone cannot be blank. "
                    "To clear it, send null. To update it, send a real number."
                )
            return cleaned
        return value

    # ------------------------------------------------------------------
    # Model validator: reject completely empty updates
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def reject_empty_update(self) -> "StudentUpdate":
        """
        Checks that the caller included at least one field in the request body.

        We use `model_fields_set` instead of `model_dump(exclude_none=True)`.

        Why the difference matters:
          model_dump(exclude_none=True)  → drops fields that are None,
            including fields set to explicit null. So {"email": null} would
            look the same as {} and be incorrectly rejected.

          model_fields_set               → the set of field names the caller
            actually sent. {"email": null} gives model_fields_set={"email"},
            which is non-empty, so the update proceeds correctly to crud.py.
        """
        if not self.model_fields_set:
            raise ValueError(
                "Update body cannot be empty. "
                "Provide at least one field: name, date_of_birth, email, or phone."
            )
        return self


# ---------------------------------------------------------------------------
# 3. StudentResponse — used when returning student data to the caller
# ---------------------------------------------------------------------------
class StudentResponse(BaseModel):
    """
    Shapes the JSON that the API sends back for any student-related response.

    Used as `response_model` in route handlers:
        @router.get("/{student_id}", response_model=StudentResponse)

    FastAPI then:
      1. Takes the return value of your route function (a dict from SQLite)
      2. Validates it through StudentResponse
      3. Serializes it to JSON, including only these fields

    SQLite compatibility:
      sqlite3.Row objects support both dict-style (row["name"]) and
      attribute-style (row.name) access. `from_attributes=True` tells
      Pydantic to use attribute access, which works with both plain dicts
      and Row objects. We also accept plain dicts via `dict(row)` in crud.py.
    """

    student_id: str
    name: str
    date_of_birth: str
    email: Optional[str] = None
    phone: Optional[str] = None

    model_config = {
        # Allows Pydantic to read from objects with attribute access,
        # not just plain dictionaries. Required for SQLite Row compatibility.
        "from_attributes": True
    }
