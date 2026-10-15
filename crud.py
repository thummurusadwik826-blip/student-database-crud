"""
crud.py
-------
All database operations for the students table.

CRUD stands for Create, Read, Update, Delete — the four fundamental things
you can do with data in any database application.

This file contains only database logic. It knows nothing about HTTP, status
codes, or request/response formatting. That separation keeps each file focused
on one job, which makes the code easier to read, test, and change.

HOW CONNECTIONS ARE HANDLED
----------------------------
Every function opens its own connection at the start and closes it in a
`finally` block at the end. The `finally` block runs whether the operation
succeeded or raised an exception, so the connection is always closed cleanly.

  conn = get_connection(db_file)
  try:
      ...do work...
  finally:
      conn.close()

HOW ERRORS ARE COMMUNICATED
-----------------------------
Rather than returning error codes or special strings, this module raises
custom exception classes. The router layer catches these and translates them
into appropriate HTTP responses. This keeps HTTP concerns out of crud.py.

  DuplicateStudentError  → raised when student_id already exists (→ HTTP 409)
  StudentNotFoundError   → not used as an exception here; functions return
                           None/False instead, and the router raises 404
  DatabaseError          → raised for unexpected database problems (→ HTTP 500)

WHY PARAMETERIZED QUERIES?
---------------------------
Every SQL statement uses ? placeholders and passes values as a tuple:

    conn.execute("INSERT INTO students VALUES (?, ?, ?, ?, ?)", (a, b, c, d, e))

Never do this:
    conn.execute(f"INSERT INTO students VALUES ('{student_id}', ...)")

The parameterized form prevents SQL injection — a classic security bug where
a malicious value like  ' OR '1'='1  could manipulate your SQL statement.
SQLite handles the escaping automatically when you use placeholders.
"""

import sqlite3
from typing import Optional

from database import DATABASE_FILE, get_connection
from models import StudentUpdate


# ---------------------------------------------------------------------------
# CUSTOM EXCEPTIONS
# ---------------------------------------------------------------------------

class DuplicateStudentError(Exception):
    """
    Raised when an INSERT fails because the student_id already exists.

    The SQLite PRIMARY KEY constraint catches this at the database level,
    so even if two requests arrive simultaneously, only one can succeed.
    We catch sqlite3.IntegrityError and re-raise as DuplicateStudentError
    so the router gets a clean, predictable exception type to handle.
    """
    pass


class DatabaseError(Exception):
    """
    Raised for unexpected database problems that are not the caller's fault
    (e.g. disk full, corrupted file, unexpected SQLite error).

    We deliberately do not include the raw SQLite error message in the HTTP
    response — that could expose internal implementation details. Instead the
    router returns a generic 500 message, and the original error is preserved
    in this exception so it can be logged.
    """
    def __init__(self, message: str, original: Exception = None):
        super().__init__(message)
        self.original = original  # Keep original for logging


# ---------------------------------------------------------------------------
# HELPER: convert a sqlite3.Row to a plain dict
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    """
    Converts a sqlite3.Row object into a plain Python dictionary.

    sqlite3.Row supports dict-style access (row["name"]) but is not a real
    dict. Pydantic's StudentResponse has `from_attributes=True` which can
    handle Row objects directly, but returning plain dicts from crud.py
    makes the functions easier to test independently (no Pydantic needed
    in test assertions) and avoids any edge-case Row behaviour after the
    connection closes.
    """
    return dict(row)


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

def create_student(student_data: dict, db_file: str = DATABASE_FILE) -> dict:
    """
    Inserts a new student record into the database.

    Parameters:
        student_data: A plain dict with keys matching the students table
                      columns. Typically produced by calling
                      StudentCreate(...).model_dump() in the router.
        db_file:      Path to the SQLite file. Tests pass a temporary path.

    Returns:
        A dict representing the newly created student record (re-fetched
        from the database to confirm what was actually stored).

    Raises:
        DuplicateStudentError: if student_id already exists.
        DatabaseError:         for any other database failure.

    SQL note:
        INSERT OR IGNORE would silently swallow duplicates — we don't want
        that. A plain INSERT raises IntegrityError on duplicate, which we
        catch and convert to DuplicateStudentError.
    """
    conn = get_connection(db_file)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO students (student_id, name, date_of_birth, email, phone)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    student_data["student_id"],
                    student_data["name"],
                    student_data["date_of_birth"],
                    student_data.get("email"),   # .get() returns None if key absent
                    student_data.get("phone"),
                ),
            )

        # Re-fetch the row to return exactly what is stored.
        # This is safer than returning student_data directly because it
        # confirms the write succeeded and returns the canonical DB values.
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_data["student_id"],),
        ).fetchone()

        return _row_to_dict(row)

    except sqlite3.IntegrityError as e:
        # IntegrityError covers PRIMARY KEY violations (duplicate student_id)
        # and NOT NULL violations. We check the message to distinguish them.
        error_msg = str(e).lower()
        if "unique" in error_msg or "primary key" in error_msg:
            raise DuplicateStudentError(
                f"A student with ID '{student_data['student_id']}' already exists."
            )
        # Any other integrity error (e.g. NOT NULL violated — shouldn't happen
        # if Pydantic validated first, but handle defensively)
        raise DatabaseError(
            "Database constraint violation during student creation.", original=e
        )

    except sqlite3.Error as e:
        raise DatabaseError("Unexpected database error during student creation.", original=e)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# READ ALL
# ---------------------------------------------------------------------------

def get_all_students(db_file: str = DATABASE_FILE) -> list[dict]:
    """
    Retrieves every student record from the database.

    Parameters:
        db_file: Path to the SQLite file.

    Returns:
        A list of dicts, one per student. Returns an empty list [] if there
        are no students — never returns None.

    Raises:
        DatabaseError: for unexpected database failures.

    SQL note:
        ORDER BY student_id makes the results predictable. Without an ORDER BY,
        SQLite can return rows in any order, which makes API responses and tests
        harder to reason about.
    """
    conn = get_connection(db_file)
    try:
        rows = conn.execute(
            "SELECT * FROM students ORDER BY student_id"
        ).fetchall()

        # fetchall() returns [] if there are no rows — no special handling needed.
        return [_row_to_dict(row) for row in rows]

    except sqlite3.Error as e:
        raise DatabaseError("Unexpected database error while fetching students.", original=e)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# READ ONE
# ---------------------------------------------------------------------------

def get_student_by_id(student_id: str, db_file: str = DATABASE_FILE) -> Optional[dict]:
    """
    Retrieves a single student record by student_id.

    Parameters:
        student_id: The unique student identifier to look up.
        db_file:    Path to the SQLite file.

    Returns:
        A dict of the student record if found.
        None if no student with that ID exists.

    Raises:
        DatabaseError: for unexpected database failures.

    The router translates None → HTTP 404.
    """
    conn = get_connection(db_file)
    try:
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()

        # fetchone() returns None when no row matches — we pass that through
        # directly. The router decides what HTTP status code to use.
        if row is None:
            return None

        return _row_to_dict(row)

    except sqlite3.Error as e:
        raise DatabaseError(
            f"Unexpected database error while fetching student '{student_id}'.",
            original=e,
        )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

def update_student(
    student_id: str,
    update_data: StudentUpdate,
    db_file: str = DATABASE_FILE,
) -> Optional[dict]:
    """
    Updates specific fields of an existing student record.

    Parameters:
        student_id:  The ID of the student to update (from the URL path).
        update_data: A StudentUpdate instance. Only fields in
                     `update_data.model_fields_set` are applied.
        db_file:     Path to the SQLite file.

    Returns:
        A dict of the updated student record if the student exists.
        None if no student with that ID exists.

    Raises:
        ValueError:    if the update would leave the record without any
                       contact method (both email and phone would be NULL).
        DatabaseError: for unexpected database failures.

    HOW PARTIAL UPDATES WORK (step by step)
    -----------------------------------------
    Pydantic's model_fields_set tells us which fields the caller actually
    sent in the request body:

        {"name": "Alice"}          → model_fields_set = {"name"}
        {"email": null}            → model_fields_set = {"email"}
        {"name": "Bob", "phone": "9999999999"} → model_fields_set = {"name", "phone"}

    Step 1: Fetch the current record from the database.
            If it doesn't exist, return None immediately.

    Step 2: Build a "merged" dict by starting with the current values and
            overlaying only the fields that were explicitly sent.

            - Fields in model_fields_set are applied (even if their value is None,
              which means the caller deliberately wants to clear that column).
            - Fields NOT in model_fields_set keep the current database value.

    Step 3: Check the contact method guard. After merging, if both email and
            phone are None, reject the update with a ValueError.
            This is the check that models.py couldn't do because it only sees
            the incoming delta, not the current state.

    Step 4: Build a dynamic UPDATE statement containing only the columns that
            changed. This avoids overwriting unchanged fields and keeps the
            SQL precise.

    Step 5: Execute the UPDATE, re-fetch the row, and return it.
    """
    conn = get_connection(db_file)
    try:
        # ------------------------------------------------------------------
        # Step 1: Fetch current record
        # ------------------------------------------------------------------
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()

        if row is None:
            return None  # Student does not exist; router will send 404

        current = _row_to_dict(row)

        # ------------------------------------------------------------------
        # Step 2: Merge — overlay only the fields the caller sent
        # ------------------------------------------------------------------
        # model_fields_set is a Python set of field name strings, e.g. {"name", "email"}.
        # We iterate only over those names and pick their values from update_data.
        incoming = {
            field: getattr(update_data, field)
            for field in update_data.model_fields_set
        }

        # Start with a copy of current values, then apply incoming changes.
        merged = {**current, **incoming}

        # ------------------------------------------------------------------
        # Step 3: Contact method guard
        # ------------------------------------------------------------------
        # After merging, verify the record will still have at least one
        # contact method. A student with no email AND no phone is not allowed.
        if not merged.get("email") and not merged.get("phone"):
            raise ValueError(
                "Update rejected: the student must have at least one contact method. "
                "Provide a valid email or phone before clearing the other."
            )

        # ------------------------------------------------------------------
        # Step 4: Build the dynamic UPDATE statement
        # ------------------------------------------------------------------
        # We only include columns that were explicitly changed by the caller.
        # If the caller sent only {"name": "Alice"}, we write:
        #   UPDATE students SET name = ? WHERE student_id = ?
        # Not:
        #   UPDATE students SET name = ?, date_of_birth = ?, email = ?, phone = ?
        #
        # This is safer: it avoids accidentally overwriting columns with stale
        # values if something unexpected happened between fetch and update.
        #
        # `SET name = ?` syntax: the list comprehension builds ["name = ?", ...]
        # and we join them with ", " to form the SET clause.

        if not incoming:
            # This should be caught by StudentUpdate.reject_empty_update,
            # but guard here too for safety.
            raise ValueError("No fields to update.")

        set_clauses = [f"{field} = ?" for field in incoming]      # ["name = ?", ...]
        set_values  = [incoming[field] for field in incoming]      # ["Alice", ...]

        sql = f"UPDATE students SET {', '.join(set_clauses)} WHERE student_id = ?"
        params = set_values + [student_id]

        # ------------------------------------------------------------------
        # Step 5: Execute and return the updated record
        # ------------------------------------------------------------------
        with conn:
            conn.execute(sql, params)

        updated_row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()

        return _row_to_dict(updated_row)

    except ValueError:
        # Re-raise ValueError (contact method guard) so the router can
        # return a 422, not a 500. Do not wrap it in DatabaseError.
        raise

    except sqlite3.Error as e:
        raise DatabaseError(
            f"Unexpected database error while updating student '{student_id}'.",
            original=e,
        )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def delete_student(student_id: str, db_file: str = DATABASE_FILE) -> bool:
    """
    Deletes a student record by student_id.

    Parameters:
        student_id: The unique student identifier to delete.
        db_file:    Path to the SQLite file.

    Returns:
        True  if the student was found and deleted.
        False if no student with that ID exists.

    Raises:
        DatabaseError: for unexpected database failures.

    HOW WE DETECT "NOT FOUND" WITHOUT A PRE-CHECK
    -----------------------------------------------
    Rather than first fetching the student and then deleting, we run a single
    DELETE statement and check `cursor.rowcount` afterwards.

    `rowcount` tells us how many rows the last statement affected:
      - 1 → the student existed and was deleted  → return True
      - 0 → no row matched the WHERE clause      → return False

    This is more efficient than a separate SELECT + DELETE, and it avoids a
    race condition where the student could be deleted between the SELECT check
    and the DELETE by another request.
    """
    conn = get_connection(db_file)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM students WHERE student_id = ?",
                (student_id,),
            )

        # cursor.rowcount is set by SQLite after the DELETE executes.
        # 1 means one row was deleted. 0 means no row matched.
        return cursor.rowcount == 1

    except sqlite3.Error as e:
        raise DatabaseError(
            f"Unexpected database error while deleting student '{student_id}'.",
            original=e,
        )

    finally:
        conn.close()
