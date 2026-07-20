"""FastAPI entrypoint — SHIPPED BY THE PLATFORM. DO NOT MODIFY OR RECREATE.

Serves the agent-generated ``index.html`` at ``/``, exposes ``tip_design.css``
under ``/static/``, and mounts the TIP proxy router at ``/tip-api/...``.
The AI agent writes ONLY ``index.html`` — never this file or ``proxy.py``.
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from proxy import router as tip_proxy_router

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TIP AI Coder generated app")

# TIP proxy (same-origin /tip-api/...) — attaches the API key server-side.
app.include_router(tip_proxy_router)

# tip_design.css and any other static assets.
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> Response:
    """Return the agent-generated page. Falls back to a placeholder if absent."""
    page = BASE_DIR / "index.html"
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse("<h1>TIP AI Coder</h1><p>The AI agent will implement your feature here.</p>")
