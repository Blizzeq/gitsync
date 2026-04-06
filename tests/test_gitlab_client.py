"""Tests for GitLab API collection and normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from gitsync.core.gitlab_client import GitLabClient
from gitsync.core.models import EventType


def _json_response(data: Any) -> httpx.Response:
    return httpx.Response(200, json=data, headers={"X-Next-Page": ""})


@pytest.mark.asyncio
async def test_gitlab_client_fetches_commits_and_merged_mrs(test_settings) -> None:
    """Activity should contain real commits and merged MRs only."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/repository/commits"):
            return _json_response(
                [
                    {
                        "id": "deadbeef",
                        "title": "Refactor API endpoints",
                        "created_at": "2026-04-05T09:00:00Z",
                        "parent_ids": ["abc123"],
                        "web_url": "https://gitlab.com/group/project/-/commit/deadbeef",
                    },
                    {
                        "id": "aabbccdd",
                        "title": "Merge branch 'feature' into 'main'",
                        "created_at": "2026-04-05T09:30:00Z",
                        "parent_ids": ["abc123", "def456"],
                        "web_url": "https://gitlab.com/group/project/-/commit/aabbccdd",
                    },
                ]
            )
        if path.endswith("/merge_requests"):
            return _json_response(
                [
                    {
                        "iid": 34,
                        "project_id": 11,
                        "title": "Add user authentication flow",
                        "created_at": "2026-04-05T10:00:00Z",
                        "merged_at": "2026-04-05T12:00:00Z",
                        "web_url": "https://gitlab.com/group/project/-/merge_requests/34",
                        "references": {"full": "group/project!34"},
                    },
                    {
                        "iid": 35,
                        "project_id": 11,
                        "title": "WIP: draft MR",
                        "created_at": "2026-04-05T11:00:00Z",
                        "merged_at": None,
                        "web_url": "https://gitlab.com/group/project/-/merge_requests/35",
                        "references": {"full": "group/project!35"},
                    },
                ]
            )
        if path == "/api/v4/projects":
            return _json_response([{"id": 11, "path_with_namespace": "group/project"}])
        raise AssertionError(f"Unexpected path: {path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://gitlab.com/api/v4",
    ) as client:
        gitlab = GitLabClient(test_settings, client=client)
        events = await gitlab.fetch_all_activity(
            after=datetime(2026, 4, 4, tzinfo=UTC),
            before=datetime(2026, 4, 6, tzinfo=UTC),
        )

    assert len(events) == 2
    types = {e.event_type for e in events}
    assert types == {EventType.COMMIT, EventType.MR_MERGED}
    commit = next(e for e in events if e.event_type == EventType.COMMIT)
    assert commit.title == "Refactor API endpoints"
    assert commit.project_name == "group/project"


@pytest.mark.asyncio
async def test_noise_commit_filter() -> None:
    """Merge commits and empty titles should be filtered out."""
    assert GitLabClient._is_noise_commit("Merge branch 'x' into 'main'", ["a", "b"])
    assert GitLabClient._is_noise_commit("Push event", [])
    assert GitLabClient._is_noise_commit("", [])
    assert not GitLabClient._is_noise_commit("Fix database pooling", ["a"])
    assert not GitLabClient._is_noise_commit("Merge branch docs", ["a"])
