"""Activity history routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from gitsync.core.models import EventType
from gitsync.web.dependencies import get_storage, get_templates

router = APIRouter()


def _parse_event_type(raw_value: str | None) -> EventType | None:
    if not raw_value:
        return None
    try:
        return EventType(raw_value)
    except ValueError:
        return None


@router.get("/activity", response_class=HTMLResponse)
async def activity_view(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    event_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> HTMLResponse:
    """Render the activity history page."""
    storage = get_storage(request)
    templates = get_templates(request)
    parsed_event_type = _parse_event_type(event_type)
    records = await storage.get_activity_log(
        page=page,
        per_page=per_page,
        event_type=parsed_event_type,
        search=search,
    )
    total = await storage.count_activity(event_type=parsed_event_type, search=search)
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "records": records,
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_more": page * per_page < total,
            "event_types": [item for item in EventType if item is not EventType.OTHER],
            "selected_event_type": parsed_event_type.value if parsed_event_type else "",
            "search": search or "",
        },
    )


@router.get("/activity/rows", response_class=HTMLResponse)
async def activity_rows(
    request: Request,
    page: int = Query(default=2, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    event_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> HTMLResponse:
    """Return more activity rows for the HTMX load-more interaction."""
    storage = get_storage(request)
    templates = get_templates(request)
    parsed_event_type = _parse_event_type(event_type)
    records = await storage.get_activity_log(
        page=page,
        per_page=per_page,
        event_type=parsed_event_type,
        search=search,
    )
    total = await storage.count_activity(event_type=parsed_event_type, search=search)
    return templates.TemplateResponse(
        request,
        "partials/activity_rows.html",
        {
            "records": records,
            "page": page,
            "per_page": per_page,
            "has_more": page * per_page < total,
            "selected_event_type": parsed_event_type.value if parsed_event_type else "",
            "search": search or "",
        },
    )
