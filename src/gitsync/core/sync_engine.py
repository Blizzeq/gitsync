"""Synchronization orchestrator."""

from __future__ import annotations

import logging
from datetime import datetime

from gitsync.core.github_client import GitHubClient
from gitsync.core.gitlab_client import GitLabClient
from gitsync.core.models import SyncRun, SyncStatus
from gitsync.core.storage import Storage

logger = logging.getLogger(__name__)


class SyncEngine:
    """Coordinate fetching, mirroring and persisting activity data."""

    def __init__(
        self,
        *,
        gitlab_client: GitLabClient,
        github_client: GitHubClient,
        storage: Storage,
    ) -> None:
        self.gitlab_client = gitlab_client
        self.github_client = github_client
        self.storage = storage

    async def run_sync(
        self,
        *,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> SyncRun:
        """Run one synchronization cycle end to end."""
        await self.storage.initialize()
        sync_run = await self.storage.create_sync_run()
        events_synced = 0
        last_sync = after or await self.storage.get_last_sync_time()
        logger.info("Starting sync (after=%s, before=%s)", last_sync, before)
        try:
            events = await self.gitlab_client.fetch_all_activity(
                after=last_sync, before=before
            )
            logger.info("Fetched %d events from GitLab", len(events))
            for event in events:
                if await self.storage.activity_exists(event.source_id):
                    logger.debug("Skipping known event %s", event.source_id)
                    continue
                sha = await self.github_client.create_contribution(event)
                await self.storage.save_activity(
                    event,
                    sync_run_id=sync_run.id or 0,
                    github_sha=sha,
                )
                events_synced += 1
            if events_synced > 0:
                await self.github_client.push_contributions()
                logger.info("Pushed %d new contributions to GitHub", events_synced)
            else:
                logger.info("No new events to sync")
            return await self.storage.finish_sync_run(
                sync_run.id or 0,
                status=SyncStatus.SUCCESS,
                events_synced=events_synced,
            )
        except Exception as exc:
            logger.error("Sync failed: %s", exc)
            await self.storage.finish_sync_run(
                sync_run.id or 0,
                status=SyncStatus.FAILED,
                events_synced=events_synced,
                error=str(exc),
            )
            raise
        finally:
            await self.github_client.cleanup()
