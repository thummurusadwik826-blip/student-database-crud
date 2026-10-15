"""
tests/test_crud.py
------------------
Automated tests for the Student Database CRUD API.

HOW THESE TESTS WORK
---------------------
We use FastAPI's TestClient to send real HTTP requests through the full stack
(router → crud → SQLite) without starting an actual server.

WHY SIMPLE MONKEYPATCHING DOESN'T WORK HERE
--------------------------------------------
crud.py imports DATABASE_FILE from database.py at module load time:

    from database import DATABASE_FILE, get_connection

Python copies the string value "students.db" into crud's namespace.
Each crud function has a default argument:

    def create_student(student_data: dict, db_file: str = DATABASE_FILE) -> dict:

Python evaluates default arguments ONCE when the function is defined — not
on every call. So `db_file` is permanently bound to "students.db" regardless
of what we later assign to crud.DATABASE_FILE or database.DATABASE_FILE.

THE CORRECT FIX
----------------
We patch `crud.get_connection` — the function that every crud operation calls
to open a database connection. By replacing it with a version that ignores
whatever db_file it receives and always opens our temp file instead, we
guarantee every read and write goes to the test database. The real students.db
is never touched.

FIXTURE EXECUTION ORDER (per test)
------------------------------------
1. `tmp_db`  — mkstemp creates a unique empty file; create_tables() creates
               the students table in it; yields the path; deletes the file.
2. `client`  — patches crud.get_connection to always use tmp_db; creates a
               TestClient; yields it; patch is undone automatically.

Each test gets its own isolated empty database. No test shares state with
another test.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import crud
import database
from main import app


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db():
    """
    Creates a fresh, empty temporary SQLite database file for one test.

    mkstemp() returns a file descriptor and a unique path in the system's
    temp directory (e.g. /tmp/tmpXXXXXX.db on macOS).
    We close the file descriptor immediately — sqlite3 will open the file
    by path. Then we create the students table and hand the path to the test.
    After the test finishes, we delete the file.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)  # Release the OS file descriptor; sqlite3 uses the path

    database.create_tables(path)  # Create the students table in the temp file

    yield path

    # Cleanup: remove the temp file after the test (and its teardown) finish
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def client(tmp_db, monkeypatch):
    """
    Provides a TestClient whose database calls are redirected to tmp_db.

    WHY WE PATCH get_connection:
    crud.py's function defaults are baked in at import time, so patching
    DATABASE_FILE after the fact has no effect on those defaults.
    Instead we replace crud.get_connection with a wrapper that ignores the
    db_file argument it receives and always opens tmp_db.

    monkeypatch undoes this replacement automatically after each test, so
    the next test gets a fresh patch pointing at its own tmp_db.
    """
    # Keep a reference to the real get_connection so we can call it
    real_get_connection = database.get_connection

    def get_connection_for_test(_db_file=None):
        """Always open the test database, regardless of what was requested."""
        return real_get_connection(tmp_db)

    # Patch the get_connection that crud.py imported and uses
    monkeypatch.setattr(crud, "get_connection", get_connection_for_test)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# SAMPLE DATA — fictional students used across tests
# ---------------------------------------------------------------------------

ALICE = {
    "student_id": "STU001",
    "name": "Alice Johnson",
    "date_of_birth": "2003-06-15",
    "email": "alice@example.com",
    "phone": None,
}

BOB = {
    "student_id": "STU002",
    "name": "Bob Smith",
    "date_of_birth": "2002-01-10",
    "email": None,
    "phone": "9876543210",
}

CAROL = {
    "student_id": "STU003",
    "name": "Carol Tran",
    "date_of_birth": "2001-11-22",
    "email": "carol@example.com",
    "phone": "1112223333",
}


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def create(client, data: dict):
    """Post a student creation request. Used to set up test preconditions."""
    return client.post("/students/", json=data)


# ===========================================================================
# HEALTH CHECK
# ===========================================================================

class TestHealthCheck:

    def test_root_returns_200(self, client):
        """The root endpoint confirms the API is running."""
        response = client.get("/")

        assert response.status_code == 200
        assert "running" in response.json()["message"].lower()


# ===========================================================================
# POST /students/ — Create
# ===========================================================================

class TestCreateStudent:

    def test_create_with_email_returns_201(self, client):
        """
        A valid student with an email address should be created successfully.
        The response body must contain all the stored fields.
        """
        response = create(client, ALICE)

        assert response.status_code == 201
        body = response.json()
        assert body["student_id"] == "STU001"
        assert body["name"] == "Alice Johnson"
        assert body["date_of_birth"] == "2003-06-15"
        assert body["email"] == "alice@example.com"
        assert body["phone"] is None

    def test_create_with_phone_only_returns_201(self, client):
        """
        A student with only a phone number (no email) is valid.
        The contact-method rule requires at least one of email or phone.
        """
        response = create(client, BOB)

        assert response.status_code == 201
        body = response.json()
        assert body["student_id"] == "STU002"
        assert body["phone"] == "9876543210"
        assert body["email"] is None

    def test_create_with_both_contacts_returns_201(self, client):
        """Creating a student with both email and phone is valid."""
        response = create(client, CAROL)

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "carol@example.com"
        assert body["phone"] == "1112223333"

    def test_create_duplicate_id_returns_409(self, client):
        """
        Posting the same student_id twice should return 409 Conflict.
        The SQLite PRIMARY KEY constraint prevents duplicates at the database
        level, and DuplicateStudentError is translated to 409 by the router.
        """
        create(client, ALICE)  # First creation — succeeds

        duplicate = {**ALICE, "name": "Alice Duplicate"}
        response = create(client, duplicate)  # Same student_id — must fail

        assert response.status_code == 409
        assert "STU001" in response.json()["detail"]

    def test_create_missing_student_id_returns_422(self, client):
        """
        student_id is required. Omitting it triggers Pydantic's 422 response
        before the request reaches the database.
        """
        response = client.post("/students/", json={
            "name": "No ID Student",
            "date_of_birth": "2003-01-01",
            "email": "noid@example.com",
        })

        assert response.status_code == 422

    def test_create_blank_student_id_returns_422(self, client):
        """A whitespace-only student_id is rejected by the field validator."""
        response = client.post("/students/", json={
            "student_id": "   ",
            "name": "Blank ID",
            "date_of_birth": "2003-01-01",
            "email": "blank@example.com",
        })

        assert response.status_code == 422

    def test_create_single_char_name_returns_422(self, client):
        """Name must have at least 2 non-whitespace characters."""
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "A",
            "date_of_birth": "2003-01-01",
            "email": "short@example.com",
        })

        assert response.status_code == 422

    def test_create_no_contact_method_returns_422(self, client):
        """
        Sending neither email nor phone is rejected by the model_validator
        in StudentCreate. Both fields are absent → 422.
        """
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "No Contact",
            "date_of_birth": "2003-01-01",
        })

        assert response.status_code == 422

    def test_create_non_padded_date_returns_422(self, client):
        """
        '2003-6-5' looks like a date but is not in YYYY-MM-DD format
        (month and day must be zero-padded). The regex check rejects this.
        """
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "Bad Date",
            "date_of_birth": "2003-6-5",
            "email": "baddate@example.com",
        })

        assert response.status_code == 422

    def test_create_impossible_date_returns_422(self, client):
        """
        '2003-02-30' matches the YYYY-MM-DD pattern but is not a real
        calendar date (February never has 30 days). strptime rejects it.
        """
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "Impossible Date",
            "date_of_birth": "2003-02-30",
            "email": "imp@example.com",
        })

        assert response.status_code == 422

    def test_create_future_date_returns_422(self, client):
        """A date of birth in the future is logically invalid."""
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "Future Student",
            "date_of_birth": "2099-01-01",
            "email": "future@example.com",
        })

        assert response.status_code == 422

    def test_create_invalid_email_returns_422(self, client):
        """EmailStr rejects values that are not valid email addresses."""
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "Bad Email",
            "date_of_birth": "2003-01-01",
            "email": "not-an-email",
        })

        assert response.status_code == 422

    def test_create_blank_phone_returns_422(self, client):
        """A phone value of whitespace only is rejected by the field validator."""
        response = client.post("/students/", json={
            "student_id": "STU099",
            "name": "Blank Phone",
            "date_of_birth": "2003-01-01",
            "phone": "   ",
        })

        assert response.status_code == 422


# ===========================================================================
# GET /students/ — List all
# ===========================================================================

class TestListStudents:

    def test_list_empty_database_returns_empty_list(self, client):
        """
        An empty database must return [] — not 404. An empty list is a valid,
        expected response when no students have been created yet.
        """
        response = client.get("/students/")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_returns_all_students(self, client):
        """After creating three students, the list endpoint returns all three."""
        create(client, ALICE)
        create(client, BOB)
        create(client, CAROL)

        response = client.get("/students/")

        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_list_is_sorted_by_student_id(self, client):
        """
        Results are ordered by student_id (ORDER BY in crud.py).
        We insert in reverse order to confirm sorting is applied.
        """
        create(client, CAROL)   # STU003
        create(client, ALICE)   # STU001
        create(client, BOB)     # STU002

        response = client.get("/students/")
        ids = [s["student_id"] for s in response.json()]

        assert ids == ["STU001", "STU002", "STU003"]

    def test_list_response_contains_correct_fields(self, client):
        """Each student object in the list must have all expected fields."""
        create(client, ALICE)

        student = client.get("/students/").json()[0]

        assert "student_id" in student
        assert "name" in student
        assert "date_of_birth" in student
        assert "email" in student
        assert "phone" in student


# ===========================================================================
# GET /students/{student_id} — Get one
# ===========================================================================

class TestGetStudent:

    def test_get_existing_student_returns_200(self, client):
        """GET /students/STU001 returns the correct student when it exists."""
        create(client, ALICE)

        response = client.get("/students/STU001")

        assert response.status_code == 200
        body = response.json()
        assert body["student_id"] == "STU001"
        assert body["name"] == "Alice Johnson"
        assert body["date_of_birth"] == "2003-06-15"
        assert body["email"] == "alice@example.com"
        assert body["phone"] is None

    def test_get_nonexistent_student_returns_404(self, client):
        """
        GET /students/STU999 returns 404 when STU999 does not exist.
        crud.get_student_by_id returns None, and the router converts that
        to a 404 HTTPException.
        """
        response = client.get("/students/STU999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_phone_only_student_returns_null_email(self, client):
        """A phone-only student should have email: null in the response."""
        create(client, BOB)

        response = client.get("/students/STU002")

        assert response.status_code == 200
        body = response.json()
        assert body["phone"] == "9876543210"
        assert body["email"] is None


# ===========================================================================
# PUT /students/{student_id} — Update
# ===========================================================================

class TestUpdateStudent:

    def test_update_name_only_changes_name_preserves_others(self, client):
        """
        Sending only {"name": "..."} updates the name and leaves every other
        field — email, phone, date_of_birth — exactly as they were.
        This is the core partial-update behaviour driven by model_fields_set.
        """
        create(client, ALICE)

        response = client.put("/students/STU001", json={"name": "Alice Smith"})

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Alice Smith"            # changed
        assert body["date_of_birth"] == "2003-06-15"    # preserved
        assert body["email"] == "alice@example.com"     # preserved
        assert body["phone"] is None                    # preserved

    def test_update_date_of_birth_preserves_name_and_contacts(self, client):
        """Updating only date_of_birth leaves name and contact fields unchanged."""
        create(client, ALICE)

        response = client.put(
            "/students/STU001",
            json={"date_of_birth": "2003-07-20"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["date_of_birth"] == "2003-07-20"     # changed
        assert body["name"] == "Alice Johnson"            # preserved
        assert body["email"] == "alice@example.com"      # preserved

    def test_update_add_phone_to_email_only_student(self, client):
        """
        Alice was created with email only. Adding a phone should succeed,
        and the email should still be present after the update.
        """
        create(client, ALICE)

        response = client.put("/students/STU001", json={"phone": "5550001111"})

        assert response.status_code == 200
        body = response.json()
        assert body["phone"] == "5550001111"
        assert body["email"] == "alice@example.com"  # email untouched

    def test_update_clear_email_when_phone_present_succeeds(self, client):
        """
        Carol has both email and phone. Clearing the email via explicit null
        should succeed because a phone number still satisfies the contact
        method requirement.
        """
        create(client, CAROL)

        response = client.put("/students/STU003", json={"email": None})

        assert response.status_code == 200
        body = response.json()
        assert body["email"] is None              # cleared
        assert body["phone"] == "1112223333"      # phone still present

    def test_update_nonexistent_student_returns_404(self, client):
        """
        Updating a student that does not exist returns 404.
        crud.update_student returns None for a missing record, and the
        router converts that to a 404 HTTPException.
        """
        response = client.put(
            "/students/STU999",
            json={"name": "Ghost Student"}
        )

        assert response.status_code == 404

    def test_update_empty_body_returns_422(self, client):
        """
        {} is rejected by StudentUpdate.reject_empty_update, which checks
        model_fields_set. An empty set means nothing to update.
        """
        create(client, ALICE)

        response = client.put("/students/STU001", json={})

        assert response.status_code == 422

    def test_update_contact_guard_email_only_student(self, client):
        """
        Alice has email only (no phone). Sending {"email": null} would clear
        the only contact method. crud.update_student raises ValueError, which
        the router converts to 422.
        """
        create(client, ALICE)
        # Confirm Alice has no phone before the test
        assert client.get("/students/STU001").json()["phone"] is None

        response = client.put("/students/STU001", json={"email": None})

        assert response.status_code == 422
        assert "contact method" in response.json()["detail"].lower()

    def test_update_contact_guard_phone_only_student(self, client):
        """
        Bob has phone only (no email). Sending {"phone": null} would clear
        the only contact method → 422.
        """
        create(client, BOB)

        response = client.put("/students/STU002", json={"phone": None})

        assert response.status_code == 422

    def test_update_invalid_date_format_returns_422(self, client):
        """
        A non-zero-padded date in the update body is rejected by StudentUpdate's
        date validator before the request reaches the database.
        """
        create(client, ALICE)

        response = client.put(
            "/students/STU001",
            json={"date_of_birth": "2003-7-4"}
        )

        assert response.status_code == 422

    def test_update_single_char_name_returns_422(self, client):
        """A single-character name is not allowed, even in an update."""
        create(client, ALICE)

        response = client.put("/students/STU001", json={"name": "X"})

        assert response.status_code == 422

    def test_update_multiple_fields_at_once(self, client):
        """
        Updating name and phone together should apply both changes.
        The email field was not sent, so it must remain unchanged.
        """
        create(client, ALICE)

        response = client.put("/students/STU001", json={
            "name": "Alice Wong",
            "phone": "4441112222",
        })

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Alice Wong"
        assert body["phone"] == "4441112222"
        assert body["email"] == "alice@example.com"  # not sent — must be preserved


# ===========================================================================
# DELETE /students/{student_id} — Delete
# ===========================================================================

class TestDeleteStudent:

    def test_delete_existing_student_returns_204(self, client):
        """
        Deleting a student that exists returns 204 No Content.
        HTTP 204 means success with an empty body — do not call .json() here.
        """
        create(client, ALICE)

        response = client.delete("/students/STU001")

        assert response.status_code == 204

    def test_deleted_student_is_no_longer_retrievable(self, client):
        """
        After a successful delete, GET /students/{id} returns 404.
        This confirms the row was actually removed from the database.
        """
        create(client, ALICE)
        client.delete("/students/STU001")

        response = client.get("/students/STU001")

        assert response.status_code == 404

    def test_delete_nonexistent_student_returns_404(self, client):
        """
        Deleting a student that was never created returns 404.
        crud.delete_student returns False when no row matched, and the
        router converts that to a 404 HTTPException.
        """
        response = client.delete("/students/STU999")

        assert response.status_code == 404

    def test_delete_already_deleted_student_returns_404(self, client):
        """
        Deleting the same student twice: the second request returns 404
        because the row no longer exists after the first delete.
        """
        create(client, ALICE)
        client.delete("/students/STU001")           # First — succeeds (204)

        response = client.delete("/students/STU001")  # Second — 404

        assert response.status_code == 404

    def test_delete_does_not_affect_other_students(self, client):
        """
        Deleting one student must not remove others from the database.
        """
        create(client, ALICE)
        create(client, BOB)
        create(client, CAROL)

        client.delete("/students/STU002")  # Delete only Bob

        remaining_ids = [
            s["student_id"] for s in client.get("/students/").json()
        ]

        assert "STU001" in remaining_ids   # Alice still here
        assert "STU002" not in remaining_ids  # Bob is gone
        assert "STU003" in remaining_ids   # Carol still here
