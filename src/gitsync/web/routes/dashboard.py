"""Dashboard routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from gitsync.web.dependencies import get_storage, get_templates

router = APIRouter()


def _next_daily_sync(now: datetime | None = None) -> datetime:
    current = now or datetime.now(tz=UTC)
    candidate = current.replace(hour=6, minute=17, second=0, microsecond=0)
    if candidate <= current:
        candidate = candidate + timedelta(days=1)
    return candidate


@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request) -> HTMLResponse:
    """Render the dashboard page."""
    storage = get_storage(request)
    templates = get_templates(request)
    snapshot = await storage.get_dashboard_snapshot(days=30)
    recent_runs = await storage.get_recent_sync_runs(limit=5)
    max_count = max((item.count for item in snapshot.daily_activity), default=0)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "snapshot": snapshot,
            "recent_runs": recent_runs,
            "max_count": max_count,
            "next_sync_at": _next_daily_sync(),
        },
    )


@router.get("/partials/sync-status", response_class=HTMLResponse)
async def sync_status_partial(request: Request) -> HTMLResponse:
    """Render the dashboard sync status partial."""
    storage = get_storage(request)
    templates = get_templates(request)
    return templates.TemplateResponse(
        request,
        "partials/sync_status.html",
        {
            "last_sync": await storage.get_last_sync_run(),
            "next_sync_at": _next_daily_sync(),
            "toast": None,
        },
    )
