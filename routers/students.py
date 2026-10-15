"""
routers/students.py
--------------------
Defines all HTTP endpoints for the /students resource.

This file is the bridge between HTTP and the database layer. Its only jobs are:
  1. Accept and validate incoming HTTP requests (Pydantic handles validation).
  2. Call the correct crud.py function.
  3. Return the right HTTP status code and response body.
  4. Translate crud.py exceptions into safe HTTP error responses.

It does NOT contain any SQL or business logic — that belongs in crud.py.

HOW APIRouter WORKS
--------------------
Instead of defining routes directly on the FastAPI app object, we use an
APIRouter. Think of it as a mini-app that groups related endpoints together.
main.py will import this router and register it with:

    app.include_router(router)

The prefix="/students" set below means every route defined here is
automatically available under /students/... — you don't repeat the prefix
on each endpoint.

HTTP STATUS CODE REFERENCE (used in this file)
------------------------------------------------
200 OK            — Request succeeded. Response body contains the result.
201 Created       — A new resource was successfully created.
204 No Content    — Request succeeded but there is nothing to return (delete).
404 Not Found     — The requested student does not exist.
409 Conflict      — The student_id already exists (duplicate).
422 Unprocessable — Validation failed: bad input or invalid update logic.
500 Internal      — Unexpected server error. Details are hidden from the client.
"""

from fastapi import APIRouter, HTTPException, status

from crud import (
    DatabaseError,
    DuplicateStudentError,
    create_student,
    delete_student,
    get_all_students,
    get_student_by_id,
    update_student,
)
from models import StudentCreate, StudentResponse, StudentUpdate

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------
# prefix="/students"   → all routes here live under /students/
# tags=["students"]    → groups endpoints together in the /docs page
router = APIRouter(prefix="/students", tags=["students"])


# ---------------------------------------------------------------------------
# POST /students/   — Create a new student
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=StudentResponse,  # Shape of the JSON we return
    status_code=status.HTTP_201_CREATED,  # 201 = something was created
    summary="Create a new student",
    description=(
        "Creates a new student record. "
        "student_id must be unique. "
        "At least one of email or phone is required."
    ),
)
def create_student_endpoint(student: StudentCreate):
    """
    Accepts a JSON body matching StudentCreate, inserts a new row, and returns
    the stored record.

    FastAPI automatically:
      - Parses the request body as JSON
      - Validates it through StudentCreate (runs all field and model validators)
      - Returns 422 automatically if validation fails — no code needed here

    We only need to handle what happens after Pydantic says the data is valid.

    student.model_dump() converts the Pydantic model to a plain Python dict,
    which is what create_student() in crud.py expects.
    """
    try:
        created = create_student(student.model_dump())
        # crud.py returns a plain dict; FastAPI serializes it through
        # StudentResponse (declared in response_model above).
        return created

    except DuplicateStudentError as e:
        # The student_id already exists in the database.
        # 409 Conflict is the correct code — the request is valid but
        # conflicts with the current state of the resource.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),  # e.g. "A student with ID 'STU001' already exists."
        )

    except DatabaseError:
        # Something unexpected went wrong at the database level.
        # We do NOT pass the exception message — it may contain internal paths
        # or raw SQLite error text. The client gets a generic safe message.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )


# ---------------------------------------------------------------------------
# GET /students/   — List all students
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=list[StudentResponse],  # A list of student objects
    status_code=status.HTTP_200_OK,
    summary="List all students",
    description="Returns all student records ordered by student_id. Returns an empty list if there are no records.",
)
def list_students_endpoint():
    """
    No path parameters or request body needed — just returns everything.

    get_all_students() always returns a list (possibly empty), never None,
    so there is no "not found" case here. An empty database returns [].
    """
    try:
        return get_all_students()

    except DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )


# ---------------------------------------------------------------------------
# GET /students/{student_id}   — Retrieve one student by ID
# ---------------------------------------------------------------------------
@router.get(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a student by ID",
    description="Returns the student record for the given student_id. Returns 404 if not found.",
)
def get_student_endpoint(student_id: str):
    """
    {student_id} in the path becomes a function parameter automatically.
    FastAPI extracts the value from the URL and passes it here.

    For example, GET /students/STU001 → student_id = "STU001"

    crud.py returns None when the student doesn't exist, so we check for
    that and raise HTTPException(404) ourselves.
    """
    try:
        student = get_student_by_id(student_id)

        if student is None:
            # 404 Not Found — the student_id does not exist in the database.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with ID '{student_id}' not found.",
            )

        return student

    except HTTPException:
        # Re-raise HTTPExceptions unchanged.
        # Without this, the broad `except DatabaseError` below could not
        # accidentally catch 404s — but being explicit is cleaner.
        raise

    except DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )


# ---------------------------------------------------------------------------
# PUT /students/{student_id}   — Update an existing student
# ---------------------------------------------------------------------------
@router.put(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a student",
    description=(
        "Partially updates a student record. "
        "Only the fields included in the request body are changed. "
        "Omitted fields keep their current values. "
        "Send null to clear a field. "
        "At least one contact method (email or phone) must remain after the update."
    ),
)
def update_student_endpoint(student_id: str, update_data: StudentUpdate):
    """
    Two inputs:
      - student_id  : from the URL path  (/students/STU001)
      - update_data : from the JSON body ({\"name\": \"Alice Smith\"})

    FastAPI validates update_data through StudentUpdate before this function
    runs. So by the time we reach this code, we know:
      - The body is not empty (StudentUpdate.reject_empty_update)
      - Any provided date_of_birth is valid
      - Any provided name has at least 2 characters
      - Any provided phone is not blank

    What we still need to handle here:
      - Student not found (crud returns None) → 404
      - Contact method guard violated (crud raises ValueError) → 422
      - Database error → 500
    """
    try:
        # update_student() expects a StudentUpdate instance directly.
        # crud.py uses update_data.model_fields_set internally to know
        # which fields to apply.
        updated = update_student(student_id, update_data)

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with ID '{student_id}' not found.",
            )

        return updated

    except HTTPException:
        # Re-raise 404s (and any other HTTPExceptions) unchanged.
        raise

    except ValueError as e:
        # crud.py raises ValueError when the update would leave the student
        # with no contact method (both email and phone would be NULL).
        # 422 Unprocessable is correct — the request data is structurally
        # valid JSON, but the business rule rejects the specific combination.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    except DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )


# ---------------------------------------------------------------------------
# DELETE /students/{student_id}   — Delete a student
# ---------------------------------------------------------------------------
@router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a student",
    description="Deletes the student with the given student_id. Returns 204 on success, 404 if not found.",
)
def delete_student_endpoint(student_id: str):
    """
    No response body on success — HTTP 204 means "done, nothing to return".
    FastAPI sends an empty response body automatically when the function
    returns None (or nothing at all) and status_code is 204.

    crud.py returns:
      True  → student existed and was deleted → we return nothing (204)
      False → no student matched → we raise 404
    """
    try:
        deleted = delete_student(student_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with ID '{student_id}' not found.",
            )

        # Return None explicitly — FastAPI sends 204 No Content with no body.
        return None

    except HTTPException:
        raise

    except DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )
