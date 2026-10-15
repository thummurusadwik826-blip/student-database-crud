"""
database.py
-----------
Handles everything related to the SQLite database:
  - Where the database file lives
  - How to open a connection to it
  - How to create the students table if it doesn't exist yet

SQLite is a file-based database. Unlike PostgreSQL or MySQL, there is no
separate server to start. Python's built-in `sqlite3` module handles it all.
"""

import sqlite3

# ---------------------------------------------------------------------------
# DATABASE FILE PATH
# ---------------------------------------------------------------------------
# This is the name of the SQLite file that will be created in your project
# folder the first time the app runs. All student data is stored here.
# Using a separate name for tests (see tests/test_crud.py) prevents test
# data from mixing with real data.
DATABASE_FILE = "students.db"


# ---------------------------------------------------------------------------
# get_connection()
# ---------------------------------------------------------------------------
def get_connection(db_file: str = DATABASE_FILE) -> sqlite3.Connection:
    """
    Opens and returns a connection to the SQLite database file.

    Parameters:
        db_file: Path to the .db file. Defaults to the main database.
                 Tests will pass a different path so they use their own file.

    What `check_same_thread=False` means:
        SQLite normally complains if you use one connection across multiple
        threads. FastAPI can handle requests in different threads, so we
        disable that restriction. Our usage here is safe because each
        request gets its own connection.

    What `detect_types` means:
        Tells sqlite3 to automatically convert stored values back to the
        correct Python types when you read them (e.g., dates stay as strings
        here since we store them as TEXT).
    """
    connection = sqlite3.connect(
        db_file,
        check_same_thread=False,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )

    # Row factory: makes each row behave like a dictionary instead of a plain
    # tuple. So you can write row["name"] instead of row[1]. Much more
    # readable and less error-prone.
    connection.row_factory = sqlite3.Row

    return connection


# ---------------------------------------------------------------------------
# create_tables()
# ---------------------------------------------------------------------------
def create_tables(db_file: str = DATABASE_FILE) -> None:
    """
    Creates the `students` table in the database if it does not already exist.

    The "IF NOT EXISTS" clause is important: it means you can call this
    function every time the app starts without accidentally wiping your data.

    Column breakdown:
        student_id   TEXT PRIMARY KEY  -- Unique identifier (e.g. "STU001").
                                          PRIMARY KEY means SQLite enforces
                                          uniqueness at the database level.
                                          Inserting a duplicate student_id
                                          will raise an IntegrityError.

        name         TEXT NOT NULL     -- Full name. Cannot be left empty.

        date_of_birth TEXT NOT NULL    -- Stored as "YYYY-MM-DD" text.
                                          We validate the format in models.py.

        email        TEXT              -- Optional. Can be NULL in the database.

        phone        TEXT              -- Optional. Can be NULL in the database.

    Note on email/phone: at least one must be provided — that rule is
    enforced in models.py (Pydantic validation), not here. The database
    stores whatever Python passes to it.
    """
    connection = get_connection(db_file)

    # `with connection` is a context manager. If the SQL succeeds, it
    # automatically commits (saves) the change. If something goes wrong,
    # it automatically rolls back (undoes) the change. Always use this
    # pattern instead of manually calling connection.commit().
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id    TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                email         TEXT,
                phone         TEXT
            )
            """
        )

    connection.close()


# ---------------------------------------------------------------------------
# AUTO-RUN ON IMPORT
# ---------------------------------------------------------------------------
# When any other file does `from database import get_connection`, Python
# runs this module top-to-bottom. Calling create_tables() here means the
# table is guaranteed to exist before any CRUD operation is attempted.
create_tables()
