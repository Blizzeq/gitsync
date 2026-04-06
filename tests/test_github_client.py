"""Tests for GitHub git operations."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gitsync.core.github_client import GitHubClient
from gitsync.core.models import EventType, GitLabEvent


def _run(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.mark.asyncio
async def test_github_client_creates_and_pushes_commit(
    test_settings, monkeypatch, tmp_path
) -> None:
    """GitHub client should create a timestamped commit and push it to the target branch."""
    remote_repo = tmp_path / "remote.git"
    seed_repo = tmp_path / "seed"

    _run(["git", "init", "--bare", str(remote_repo)])
    _run(["git", "init", "-b", "main", str(seed_repo)])
    _run(["git", "config", "user.name", "Seed User"], cwd=seed_repo)
    _run(["git", "config", "user.email", "seed@example.com"], cwd=seed_repo)
    (seed_repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed_repo)
    _run(["git", "commit", "-m", "Initial commit"], cwd=seed_repo)
    _run(["git", "remote", "add", "origin", str(remote_repo)], cwd=seed_repo)
    _run(["git", "push", "origin", "main"], cwd=seed_repo)

    monkeypatch.setattr(
        type(test_settings),
        "github_remote_url",
        property(lambda self: str(remote_repo)),
    )

    client = GitHubClient(test_settings)
    event = GitLabEvent(
        source_id="commit:123",
        event_type=EventType.COMMIT,
        title="Fix database pooling",
        project_name="group/project",
        timestamp=datetime(2026, 4, 6, 12, 30, tzinfo=UTC),
    )

    sha = await client.create_contribution(event)
    await client.push_contributions()
    await client.cleanup()

    log_output = _run(
        ["git", "--git-dir", str(remote_repo), "log", "main", "--pretty=%s"]
    )

    assert sha
    assert "[commit] group/project: Fix database pooling" in log_output
