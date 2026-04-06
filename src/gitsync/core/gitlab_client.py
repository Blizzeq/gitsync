"""Async GitLab client responsible for collecting user activity."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from gitsync.core.config import Settings
from gitsync.core.models import EventType, GitLabEvent, deduplicate_events

logger = logging.getLogger(__name__)


class GitLabClient:
    """Fetch activity data from GitLab REST APIs."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        *,
        backoff_base_seconds: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self.settings = settings
        self._external_client = client
        self._client: httpx.AsyncClient | None = client
        self._backoff_base_seconds = backoff_base_seconds
        self._max_retries = max_retries
        self._user_id: int | None = None

    async def __aenter__(self) -> GitLabClient:
        """Open the underlying HTTP client if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the internal HTTP client."""
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def fetch_all_activity(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[GitLabEvent]:
        """Collect and normalize all configured activity types."""
        events: list[GitLabEvent] = []
        events.extend(await self.fetch_user_events(after=after, before=before))
        logger.debug("Collected %d user events", len(events))
        if self.settings.sync_merge_requests:
            mr_events = await self.fetch_merge_requests(
                created_after=after, updated_after=after
            )
            logger.debug("Collected %d merge request events", len(mr_events))
            events.extend(mr_events)
        if self.settings.sync_commits:
            commit_events = await self.fetch_user_commits(after=after, before=before)
            logger.debug("Collected %d commit events", len(commit_events))
            events.extend(commit_events)
        deduplicated = deduplicate_events(events)
        logger.info(
            "Total activity: %d events (%d after deduplication)",
            len(events),
            len(deduplicated),
        )
        return deduplicated

    async def fetch_user_events(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[GitLabEvent]:
        """Fetch user event feed and map it into normalized domain events."""
        user_id = await self._get_user_id()
        params = self._date_params(after=after, before=before)
        events: list[GitLabEvent] = []
        async for payload in self._paginate(f"/users/{user_id}/events", params=params):
            event = self._map_event_payload(payload)
            if event is not None:
                events.append(event)
        return events

    async def fetch_merge_requests(
        self,
        created_after: datetime | None = None,
        updated_after: datetime | None = None,
    ) -> list[GitLabEvent]:
        """Fetch authored merge requests for created and merged activity."""
        if self.settings.gitlab_username is None:
            return []
        params: dict[str, Any] = {
            "scope": "all",
            "author_username": self.settings.gitlab_username,
            "order_by": "updated_at",
            "sort": "asc",
        }
        if created_after is not None:
            params["created_after"] = created_after.astimezone(UTC).isoformat()
        if updated_after is not None:
            params["updated_after"] = updated_after.astimezone(UTC).isoformat()
        events: list[GitLabEvent] = []
        async for payload in self._paginate("/merge_requests", params=params):
            project_name = payload.get("references", {}).get("full", "unknown/project")
            created_at = self._parse_datetime(payload["created_at"])
            merged_at = payload.get("merged_at")
            iid = payload["iid"]
            web_url = payload.get("web_url")
            events.append(
                GitLabEvent(
                    source_id=f"mr-created:{payload['project_id']}:{iid}",
                    event_type=EventType.MR_CREATED,
                    title=payload["title"],
                    project_name=project_name,
                    timestamp=created_at,
                    url=web_url,
                )
            )
            if merged_at:
                events.append(
                    GitLabEvent(
                        source_id=f"mr-merged:{payload['project_id']}:{iid}",
                        event_type=EventType.MR_MERGED,
                        title=payload["title"],
                        project_name=project_name,
                        timestamp=self._parse_datetime(merged_at),
                        url=web_url,
                    )
                )
        return events

    async def fetch_user_commits(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[GitLabEvent]:
        """Fetch authored commits across user projects."""
        if self.settings.gitlab_username is None:
            return []
        projects = await self._fetch_user_projects()
        events: list[GitLabEvent] = []
        for project in projects:
            params: dict[str, Any] = {
                "author": self.settings.gitlab_username,
                "all": True,
            }
            if after is not None:
                params["since"] = after.astimezone(UTC).isoformat()
            if before is not None:
                params["until"] = before.astimezone(UTC).isoformat()
            path = f"/projects/{project['id']}/repository/commits"
            async for payload in self._paginate(path, params=params):
                sha = payload["id"]
                events.append(
                    GitLabEvent(
                        source_id=f"commit:{sha}",
                        event_type=EventType.COMMIT,
                        title=payload["title"],
                        project_name=project["path_with_namespace"],
                        timestamp=self._parse_datetime(payload["created_at"]),
                        url=payload.get("web_url"),
                    )
                )
        return events

    async def get_current_user(self) -> dict[str, Any]:
        """Fetch the current GitLab user profile for connection checks."""
        response = await self._request("GET", "/user")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("GitLab /user response did not return an object")
        return cast(dict[str, Any], payload)

    def _build_client(self) -> httpx.AsyncClient:
        headers = (
            {"PRIVATE-TOKEN": self.settings.gitlab_token.get_secret_value()}
            if self.settings.gitlab_token
            else {}
        )
        return httpx.AsyncClient(
            base_url=f"{self.settings.gitlab_url.rstrip('/')}/api/v4",
            headers=headers,
            timeout=30.0,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = await self._get_client()
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response = await client.request(method, path, params=params)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after
                else self._backoff_base_seconds * (2**attempt)
            )
            logger.warning(
                "Rate limited on %s %s, retrying in %.1fs (attempt %d/%d)",
                method,
                path,
                delay,
                attempt + 1,
                self._max_retries,
            )
            last_error = httpx.HTTPStatusError(
                "GitLab rate limit exceeded",
                request=response.request,
                response=response,
            )
            await asyncio.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Unexpected HTTP retry state")

    async def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        page = 1
        while True:
            current_params = {**(params or {}), "page": page, "per_page": 100}
            response = await self._request("GET", path, params=current_params)
            payload = response.json()
            if not payload:
                break
            for item in payload:
                yield item
            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            page = int(next_page)

    async def _get_user_id(self) -> int:
        if self._user_id is not None:
            return self._user_id
        if self.settings.gitlab_username is None:
            raise ValueError("GITSYNC_GITLAB_USERNAME must be configured")
        response = await self._request(
            "GET",
            "/users",
            params={"username": self.settings.gitlab_username},
        )
        users = response.json()
        if not users:
            raise ValueError("GitLab user not found")
        self._user_id = int(users[0]["id"])
        return self._user_id

    async def _fetch_user_projects(self) -> list[dict[str, Any]]:
        user_id = await self._get_user_id()
        projects: list[dict[str, Any]] = []
        async for payload in self._paginate(
            f"/users/{user_id}/projects",
            params={"membership": True, "simple": True, "order_by": "last_activity_at"},
        ):
            projects.append(payload)
        return projects

    def _map_event_payload(self, payload: dict[str, Any]) -> GitLabEvent | None:
        target_type = payload.get("target_type")
        action_name = payload.get("action_name")
        project_name = payload.get("project", {}).get(
            "path_with_namespace", "unknown/project"
        )
        timestamp = self._parse_datetime(payload["created_at"])
        if target_type == "MergeRequest":
            event_type = (
                EventType.MR_REVIEWED
                if action_name in {"approved", "commented"}
                else EventType.MR_CREATED
            )
            if action_name == "merged":
                event_type = EventType.MR_MERGED
            iid = payload.get("target_iid", payload.get("id"))
            return GitLabEvent(
                source_id=f"mr-event:{event_type}:{project_name}:{iid}",
                event_type=event_type,
                title=payload.get("target_title") or "Merge request activity",
                project_name=project_name,
                timestamp=timestamp,
                url=payload.get("target_url") or None,
            )
        if target_type == "Issue":
            event_type = (
                EventType.ISSUE_CLOSED
                if action_name == "closed"
                else EventType.ISSUE_CREATED
            )
            iid = payload.get("target_iid", payload.get("id"))
            return GitLabEvent(
                source_id=f"issue:{event_type}:{project_name}:{iid}",
                event_type=event_type,
                title=payload.get("target_title") or "Issue activity",
                project_name=project_name,
                timestamp=timestamp,
                url=payload.get("target_url") or None,
            )
        push_data = payload.get("push_data")
        if push_data:
            sha = push_data.get("commit_to") or f"event-{payload['id']}"
            return GitLabEvent(
                source_id=f"commit:{sha}",
                event_type=EventType.COMMIT,
                title=push_data.get("commit_title") or "Push event",
                project_name=project_name,
                timestamp=timestamp,
                url=None,
            )
        if target_type == "Note":
            return GitLabEvent(
                source_id=f"comment:{project_name}:{payload['id']}",
                event_type=EventType.COMMENT,
                title=payload.get("target_title") or "Commented on activity",
                project_name=project_name,
                timestamp=timestamp,
                url=None,
            )
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

    @staticmethod
    def _date_params(
        *,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> dict[str, str]:
        params: dict[str, str] = {}
        if after is not None:
            params["after"] = after.astimezone(UTC).isoformat()
        if before is not None:
            params["before"] = before.astimezone(UTC).isoformat()
        return params
