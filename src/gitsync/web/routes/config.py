"""Configuration routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import SecretStr

from gitsync.core.gitlab_client import GitLabClient
from gitsync.web.dependencies import get_app_settings, get_storage, get_templates

router = APIRouter()


def _settings_payload(settings: Any) -> dict[str, Any]:
    return {
        "gitlab_url": settings.gitlab_url,
        "gitlab_username": settings.gitlab_username or "",
        "github_repo": settings.github_repo or "",
        "github_email": settings.github_email or "",
        "github_branch": settings.github_branch,
        "sync_commits": settings.sync_commits,
        "sync_merge_requests": settings.sync_merge_requests,
        "sync_issues": settings.sync_issues,
        "sync_reviews": settings.sync_reviews,
    }


@router.get("/settings", response_class=HTMLResponse)
async def settings_view(request: Request) -> HTMLResponse:
    """Render the settings page."""
    templates = get_templates(request)
    settings = get_app_settings(request)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings_data": _settings_payload(settings),
            "toast": None,
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    gitlab_url: str = Form(...),
    gitlab_username: str = Form(...),
    gitlab_token: str = Form(default=""),
    github_repo: str = Form(...),
    github_token: str = Form(default=""),
    github_email: str = Form(...),
    github_branch: str = Form(default="main"),
    sync_commits: bool = Form(default=False),
    sync_merge_requests: bool = Form(default=False),
    sync_issues: bool = Form(default=False),
    sync_reviews: bool = Form(default=False),
) -> HTMLResponse:
    """Persist settings in memory and SQLite."""
    settings = get_app_settings(request)
    storage = get_storage(request)
    templates = get_templates(request)

    settings.gitlab_url = gitlab_url
    settings.gitlab_username = gitlab_username
    settings.github_repo = github_repo
    settings.github_email = github_email
    settings.github_branch = github_branch
    settings.sync_commits = sync_commits
    settings.sync_merge_requests = sync_merge_requests
    settings.sync_issues = sync_issues
    settings.sync_reviews = sync_reviews
    if gitlab_token:
        settings.gitlab_token = SecretStr(gitlab_token)
    if github_token:
        settings.github_token = SecretStr(github_token)

    await storage.save_config(
        {
            "gitlab_url": gitlab_url,
            "gitlab_username": gitlab_username,
            "github_repo": github_repo,
            "github_email": github_email,
            "github_branch": github_branch,
            "sync_commits": str(sync_commits),
            "sync_merge_requests": str(sync_merge_requests),
            "sync_issues": str(sync_issues),
            "sync_reviews": str(sync_reviews),
        }
    )
    return templates.TemplateResponse(
        request,
        "partials/toast.html",
        {
            "tone": "success",
            "message": "Configuration saved in local runtime and SQLite.",
        },
    )


@router.post("/settings/test", response_class=HTMLResponse)
async def test_settings_connection(request: Request) -> HTMLResponse:
    """Validate the current GitLab connection settings."""
    templates = get_templates(request)
    settings = get_app_settings(request)
    try:
        settings.require_sync_configuration()
        async with GitLabClient(settings) as client:
            user = await client.get_current_user()
        message = (
            f"GitLab connection OK for {user.get('username', 'unknown')}. "
            "GitHub configuration looks complete."
        )
        tone = "success"
    except Exception as exc:
        message = f"Connection check failed: {exc}"
        tone = "error"
    return templates.TemplateResponse(
        request,
        "partials/toast.html",
        {
            "tone": tone,
            "message": message,
        },
    )
