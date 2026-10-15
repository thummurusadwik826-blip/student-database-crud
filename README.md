# Student Database CRUD API

A REST API for managing student records, built with **Python 3.13**, **FastAPI**, and **SQLite**. Data is stored persistently in a local SQLite file. All endpoints are testable through FastAPI's built-in interactive documentation at `/docs` — no separate frontend required.

Built as an internship project for EWB Edu Tech.

---

## Features

- Create a student record with a unique ID
- List all students
- Retrieve a single student by ID
- Update individual fields without overwriting the rest
- Delete a student record
- Input validation with clear error messages
- Duplicate ID detection enforced at the database level
- Automated test suite covering 37 cases

---

## Student Record

| Field | Type | Required | Validation rules |
|---|---|---|---|
| `student_id` | string | Yes | Must be non-blank after trimming whitespace |
| `name` | string | Yes | At least 2 non-whitespace characters after trimming |
| `date_of_birth` | string | Yes | Exactly `YYYY-MM-DD` format, real calendar date, not in the future |
| `email` | string | No | Valid email format if provided (e.g. `alice@example.com`) |
| `phone` | string | No | Non-blank string if provided |

**Contact method rule:** at least one of `email` or `phone` must be present on every record. A record cannot have both set to `null`.

**Update behaviour:** only the fields you include in a PUT request are changed. Omitted fields keep their current values. Send `null` to explicitly clear a field — but the contact method rule still applies after the change.

---

## Project Structure

```
student_db/
├── main.py              # Creates the FastAPI app and registers the router
├── database.py          # SQLite connection helper and table setup
├── models.py            # Pydantic models for validation and response shaping
├── crud.py              # Database operations (create, read, update, delete)
├── routers/
│   └── students.py      # HTTP route handlers and status code mapping
├── tests/
│   └── test_crud.py     # Automated tests using pytest and FastAPI TestClient
├── requirements.txt     # All Python dependencies with pinned versions
├── students.db          # SQLite database file (created on first run)
└── README.md            # This file
```

---

## Setup (macOS)

### 1. Clone or navigate to the project folder

```zsh
cd student_db
```

### 2. Create a virtual environment

```zsh
python3 -m venv .venv
```

### 3. Activate the virtual environment

```zsh
source .venv/bin/activate
```

Your terminal prompt will change to show `(.venv)` — this means the virtual
environment is active. All packages you install go here and do not affect
the rest of your system.

### 4. Install dependencies

```zsh
pip install -r requirements.txt
```

### 5. Start the API server

```zsh
uvicorn main:app --reload
```

`--reload` restarts the server automatically when you save a file. Useful
during development.

You should see output like:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### 6. Open the interactive API documentation

Visit **http://127.0.0.1:8000/docs** in your browser.

FastAPI generates this page automatically from your code. You can use it to
send real requests to every endpoint, inspect request bodies and responses,
and see all validation rules — without writing any frontend code.

---

## API Endpoints

### Base URL: `http://127.0.0.1:8000`

| Method | Path | Description | Success code |
|---|---|---|---|
| `GET` | `/` | Health check — confirms the API is running | 200 |
| `POST` | `/students/` | Create a new student | 201 |
| `GET` | `/students/` | List all students (empty list if none) | 200 |
| `GET` | `/students/{student_id}` | Get one student by ID | 200 |
| `PUT` | `/students/{student_id}` | Partially update a student | 200 |
| `DELETE` | `/students/{student_id}` | Delete a student | 204 |

### Error codes

| Code | Meaning |
|---|---|
| 404 Not Found | The `student_id` does not exist |
| 409 Conflict | A student with that `student_id` already exists (POST only) |
| 422 Unprocessable | Input validation failed — response body explains what is wrong |
| 500 Internal Server Error | Unexpected server error |

---

## Example Requests

### Create a student — POST /students/

```json
{
  "student_id": "STU001",
  "name": "Alice Johnson",
  "date_of_birth": "2003-06-15",
  "email": "alice@example.com",
  "phone": null
}
```

**Response — 201 Created:**

```json
{
  "student_id": "STU001",
  "name": "Alice Johnson",
  "date_of_birth": "2003-06-15",
  "email": "alice@example.com",
  "phone": null
}
```

---

### Create a student with phone only — POST /students/

```json
{
  "student_id": "STU002",
  "name": "Bob Smith",
  "date_of_birth": "2002-01-10",
  "email": null,
  "phone": "9876543210"
}
```

---

### Update a student's name only — PUT /students/STU001

Only the fields you send are changed. `date_of_birth`, `email`, and `phone`
stay exactly as they were.

```json
{
  "name": "Alice Wong"
}
```

**Response — 200 OK:**

```json
{
  "student_id": "STU001",
  "name": "Alice Wong",
  "date_of_birth": "2003-06-15",
  "email": "alice@example.com",
  "phone": null
}
```

---

### Add a phone number to an existing student — PUT /students/STU001

```json
{
  "phone": "5550001111"
}
```

---

### Clear a field — PUT /students/STU001

Send `null` to remove a value. The request below clears the email address.
This is only allowed if the student still has a phone number — the contact
method rule is checked after the change is applied.

```json
{
  "email": null
}
```

---

### Invalid request examples

**Missing contact method — returns 422:**

```json
{
  "student_id": "STU099",
  "name": "No Contact",
  "date_of_birth": "2003-01-01"
}
```

**Non-zero-padded date — returns 422:**

```json
{
  "student_id": "STU099",
  "name": "Bad Date",
  "date_of_birth": "2003-6-5",
  "email": "test@example.com"
}
```

---

## Running the Tests

The test suite uses `pytest` and FastAPI's `TestClient`. Each test runs
against its own isolated temporary SQLite database — the real `students.db`
file is never touched.

From inside the `student_db/` folder with the virtual environment active:

```zsh
python3 -m pytest tests/test_crud.py -v
```

### Latest test results

```
collected 37 items

tests/test_crud.py::TestHealthCheck::test_root_returns_200 PASSED
tests/test_crud.py::TestCreateStudent::test_create_with_email_returns_201 PASSED
tests/test_crud.py::TestCreateStudent::test_create_with_phone_only_returns_201 PASSED
tests/test_crud.py::TestCreateStudent::test_create_with_both_contacts_returns_201 PASSED
tests/test_crud.py::TestCreateStudent::test_create_duplicate_id_returns_409 PASSED
tests/test_crud.py::TestCreateStudent::test_create_missing_student_id_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_blank_student_id_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_single_char_name_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_no_contact_method_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_non_padded_date_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_impossible_date_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_future_date_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_invalid_email_returns_422 PASSED
tests/test_crud.py::TestCreateStudent::test_create_blank_phone_returns_422 PASSED
tests/test_crud.py::TestListStudents::test_list_empty_database_returns_empty_list PASSED
tests/test_crud.py::TestListStudents::test_list_returns_all_students PASSED
tests/test_crud.py::TestListStudents::test_list_is_sorted_by_student_id PASSED
tests/test_crud.py::TestListStudents::test_list_response_contains_correct_fields PASSED
tests/test_crud.py::TestGetStudent::test_get_existing_student_returns_200 PASSED
tests/test_crud.py::TestGetStudent::test_get_nonexistent_student_returns_404 PASSED
tests/test_crud.py::TestGetStudent::test_get_phone_only_student_returns_null_email PASSED
tests/test_crud.py::TestUpdateStudent::test_update_name_only_changes_name_preserves_others PASSED
tests/test_crud.py::TestUpdateStudent::test_update_date_of_birth_preserves_name_and_contacts PASSED
tests/test_crud.py::TestUpdateStudent::test_update_add_phone_to_email_only_student PASSED
tests/test_crud.py::TestUpdateStudent::test_update_clear_email_when_phone_present_succeeds PASSED
tests/test_crud.py::TestUpdateStudent::test_update_nonexistent_student_returns_404 PASSED
tests/test_crud.py::TestUpdateStudent::test_update_empty_body_returns_422 PASSED
tests/test_crud.py::TestUpdateStudent::test_update_contact_guard_email_only_student PASSED
tests/test_crud.py::TestUpdateStudent::test_update_contact_guard_phone_only_student PASSED
tests/test_crud.py::TestUpdateStudent::test_update_invalid_date_format_returns_422 PASSED
tests/test_crud.py::TestUpdateStudent::test_update_single_char_name_returns_422 PASSED
tests/test_crud.py::TestUpdateStudent::test_update_multiple_fields_at_once PASSED
tests/test_crud.py::TestDeleteStudent::test_delete_existing_student_returns_204 PASSED
tests/test_crud.py::TestDeleteStudent::test_deleted_student_is_no_longer_retrievable PASSED
tests/test_crud.py::TestDeleteStudent::test_delete_nonexistent_student_returns_404 PASSED
tests/test_crud.py::TestDeleteStudent::test_delete_already_deleted_student_returns_404 PASSED
tests/test_crud.py::TestDeleteStudent::test_delete_does_not_affect_other_students PASSED

37 passed in 1.59s
```

### What the tests cover

| Area | Cases tested |
|---|---|
| POST — valid creation | Email only, phone only, both contacts |
| POST — invalid input | Missing ID, blank ID, short name, no contact method, non-padded date, impossible date, future date, invalid email, blank phone |
| POST — duplicate ID | 409 returned, ID appears in error detail |
| GET list | Empty database returns `[]`, sorted by `student_id`, all fields present |
| GET by ID | Existing student returns 200, missing student returns 404 |
| PUT — partial update | Name-only preserves others, date-only preserves others, multiple fields at once |
| PUT — error cases | Empty body, non-existent student, contact method guard (email-only and phone-only), invalid date, single-char name |
| DELETE | Existing student returns 204, missing student returns 404, already-deleted returns 404, other records unaffected |
| Health check | Root `/` returns 200 |

---

## Technology Stack

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.13 | Language |
| FastAPI | 0.143.0 | Web framework and automatic API documentation |
| Pydantic | 2.14.1 | Request validation and response serialization |
| SQLite (built-in) | — | File-based database, no separate server needed |
| Uvicorn | 0.54.0 | ASGI server to run the FastAPI app |
| pytest | 9.1.1 | Test runner |
| email-validator | 2.3.0 | Email format validation for Pydantic's `EmailStr` |
