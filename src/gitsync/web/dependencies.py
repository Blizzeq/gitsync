"""Shared web-layer helpers and dependency accessors."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from fastapi.templating import Jinja2Templates

from gitsync.core.config import Settings
from gitsync.core.github_client import GitHubClient
from gitsync.core.gitlab_client import GitLabClient
from gitsync.core.storage import Storage
from gitsync.core.sync_engine import SyncEngine


def get_app_settings(request: Request) -> Settings:
    """Return runtime settings from the app state."""
    return cast(Settings, request.app.state.settings)


def get_storage(request: Request) -> Storage:
    """Return storage from the app state."""
    return cast(Storage, request.app.state.storage)


def get_templates(request: Request) -> Jinja2Templates:
    """Return Jinja templates from the app state."""
    return cast(Jinja2Templates, request.app.state.templates)


def build_sync_engine(request: Request) -> SyncEngine:
    """Create a sync engine using the current app state."""
    settings = get_app_settings(request)
    storage = get_storage(request)
    return SyncEngine(
        gitlab_client=GitLabClient(settings),
        github_client=GitHubClient(settings),
        storage=storage,
    )
