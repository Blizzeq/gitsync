"""GitHub Action entrypoint."""

from __future__ import annotations

import asyncio

from gitsync.core.config import get_settings
from gitsync.core.github_client import GitHubClient
from gitsync.core.gitlab_client import GitLabClient
from gitsync.core.storage import Storage
from gitsync.core.sync_engine import SyncEngine


async def main() -> None:
    """Run one headless synchronization cycle."""
    settings = get_settings()
    settings.require_sync_configuration()
    engine = SyncEngine(
        gitlab_client=GitLabClient(settings),
        github_client=GitHubClient(settings),
        storage=Storage(settings.db_path),
    )
    await engine.run_sync()


if __name__ == "__main__":
    asyncio.run(main())
