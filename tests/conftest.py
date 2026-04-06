"""Shared pytest fixtures for GitSync tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from gitsync.core.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Return settings configured for tests."""
    return Settings(
        gitlab_token=SecretStr("gitlab-token"),
        gitlab_username="jakub",
        github_repo="jakub/gitlab-activity",
        github_token=SecretStr("github-token"),
        github_email="jakub@example.com",
        db_path=tmp_path / "gitsync.db",
    )
