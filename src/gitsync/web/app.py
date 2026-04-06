"""FastAPI application factory for GitSync."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gitsync.core.config import Settings, get_settings
from gitsync.core.storage import Storage
from gitsync.web.routes import activity, api, config, dashboard

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    storage = Storage(resolved_settings.db_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await storage.initialize()
        yield

    app = FastAPI(
        title="GitSync",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.storage = storage
    app.state.templates = templates
    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )

    app.include_router(dashboard.router)
    app.include_router(activity.router)
    app.include_router(config.router)
    app.include_router(api.router)

    return app
