"""Lightweight API endpoints for HTMX interactions."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from gitsync.web.dependencies import build_sync_engine, get_storage, get_templates

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> JSONResponse:
    """Simple health endpoint."""
    return JSONResponse({"status": "ok"})


@router.post("/sync", response_class=HTMLResponse)
async def trigger_sync(request: Request) -> HTMLResponse:
    """Run a sync immediately and return the refreshed status card."""
    templates = get_templates(request)
    storage = get_storage(request)
    engine = build_sync_engine(request)
    toast: dict[str, str] | None = None
    try:
        sync_run = await engine.run_sync()
        toast = {
            "tone": "success",
            "message": f"Sync completed. {sync_run.events_synced} events mirrored.",
        }
    except Exception as exc:
        toast = {
            "tone": "error",
            "message": f"Sync failed: {exc}",
        }
    return templates.TemplateResponse(
        request,
        "partials/sync_status.html",
        {
            "last_sync": await storage.get_last_sync_run(),
            "next_sync_at": None,
            "toast": toast,
        },
    )
