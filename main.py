"""
main.py
-------
Entry point for the Student Database API.

Serves two things:
  1. The REST API under /students/ (handled by routers/students.py)
  2. The HTML dashboard at / (rendered from templates/dashboard.html)

Static files (CSS, JS) are served from the /static directory.

To run the server:
    uvicorn main:app --reload

Then open:
  http://127.0.0.1:8000          → Dashboard UI
  http://127.0.0.1:8000/docs     → Interactive API documentation
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from routers.students import router as students_router

# Absolute path to this file's directory — works regardless of where the
# server is launched from or where tests are run from.
BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Create the FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Student Database API",
    description="CRUD API for managing student records. Built with FastAPI and SQLite.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Static files — CSS, JavaScript
# Served at /static/...  (e.g. /static/css/dashboard.css)
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ---------------------------------------------------------------------------
# Jinja2 templates — HTML pages
# ---------------------------------------------------------------------------
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ---------------------------------------------------------------------------
# Register the students API router
# ---------------------------------------------------------------------------
# All routes defined in routers/students.py (with prefix="/students") are
# now available on this app:
#   POST   /students/
#   GET    /students/
#   GET    /students/{student_id}
#   PUT    /students/{student_id}
#   DELETE /students/{student_id}
app.include_router(students_router)


# ---------------------------------------------------------------------------
# Dashboard route — serves the HTML frontend
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    """
    Serves the student management dashboard.

    include_in_schema=False hides this from the /docs API explorer since
    it returns HTML, not JSON.

    Starlette 1.x new-style TemplateResponse: request is the first argument,
    context dict does not need to include the request object.
    """
    return templates.TemplateResponse(request, "dashboard.html")


# ---------------------------------------------------------------------------
# Health-check endpoint — returns JSON, useful for the API docs page
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
def health_check():
    """Returns a JSON message confirming the API is running."""
    return {"status": "ok", "message": "Student Database API is running."}
