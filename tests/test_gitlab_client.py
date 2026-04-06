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
async def test_gitlab_client_fetches_and_deduplicates_activity(test_settings) -> None:
    """GitLab client should merge events, merge requests and commits into one stream."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users"):
            return _json_response([{"id": 7, "username": "jakub"}])
        if path.endswith("/users/7/events"):
            return _json_response(
                [
                    {
                        "id": 1,
                        "created_at": "2026-04-05T08:00:00Z",
                        "target_type": "Issue",
                        "action_name": "opened",
                        "target_iid": 21,
                        "target_title": "Safari login bug",
                        "target_url": "https://gitlab.com/group/project/-/issues/21",
                        "project": {"path_with_namespace": "group/project"},
                    },
                    {
                        "id": 2,
                        "created_at": "2026-04-05T09:00:00Z",
                        "push_data": {
                            "commit_to": "deadbeef",
                            "commit_title": "Refactor API endpoints",
                        },
                        "project": {"path_with_namespace": "group/project"},
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
                    }
                ]
            )
        if path.endswith("/users/7/projects"):
            return _json_response([{"id": 11, "path_with_namespace": "group/project"}])
        if path.endswith("/projects/11/repository/commits"):
            return _json_response(
                [
                    {
                        "id": "deadbeef",
                        "title": "Refactor API endpoints",
                        "created_at": "2026-04-05T09:00:00Z",
                        "web_url": "https://gitlab.com/group/project/-/commit/deadbeef",
                    }
                ]
            )
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

    assert len(events) == 4
    assert {event.event_type for event in events} == {
        EventType.COMMIT,
        EventType.ISSUE_CREATED,
        EventType.MR_CREATED,
        EventType.MR_MERGED,
    }
    assert events[0].project_name == "group/project"
