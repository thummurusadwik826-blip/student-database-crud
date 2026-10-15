"""
main.py
-------
Entry point for the Student Database API.

This file creates the FastAPI application and registers the students router.
It is intentionally small — all endpoint logic lives in routers/students.py,
all database logic lives in crud.py, and all validation lives in models.py.

To run the server:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs to test all endpoints interactively.
"""

from fastapi import FastAPI

from routers.students import router as students_router

# ---------------------------------------------------------------------------
# Create the FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Student Database API",
    description="CRUD API for managing student records. Built with FastAPI and SQLite.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Register the students router
# ---------------------------------------------------------------------------
# All routes defined in routers/students.py (with prefix="/students") are
# now available on this app. For example:
#   POST   /students/
#   GET    /students/
#   GET    /students/{student_id}
#   PUT    /students/{student_id}
#   DELETE /students/{student_id}
app.include_router(students_router)


# ---------------------------------------------------------------------------
# Root endpoint — quick health check
# ---------------------------------------------------------------------------
@app.get("/", tags=["health"])
def root():
    """Returns a simple message confirming the API is running."""
    return {"message": "Student Database API is running. Visit /docs to explore the endpoints."}
