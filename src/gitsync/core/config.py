"""Configuration management for GitSync."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GITSYNC_",
        extra="ignore",
    )

    gitlab_token: SecretStr | None = None
    gitlab_url: str = "https://gitlab.com"
    gitlab_username: str | None = None
    github_repo: str | None = None
    github_token: SecretStr | None = None
    github_email: str | None = None
    github_branch: str = "main"
    db_path: Path = Field(
        default_factory=lambda: Path("~/.gitsync/gitsync.db").expanduser()
    )
    app_host: str = "127.0.0.1"
    app_port: int = 8765

    sync_commits: bool = True
    sync_merge_requests: bool = True
    sync_issues: bool = False
    sync_reviews: bool = False

    git_author_name: str = "GitSync"

    def ensure_directories(self) -> None:
        """Create directories required by the configured filesystem layout."""
        self.db_path.expanduser().parent.mkdir(parents=True, exist_ok=True)

    def require_sync_configuration(self) -> None:
        """Ensure the settings contain the minimum data required for syncing."""
        missing = []
        if self.gitlab_token is None:
            missing.append("GITSYNC_GITLAB_TOKEN")
        if self.gitlab_username is None:
            missing.append("GITSYNC_GITLAB_USERNAME")
        if self.github_repo is None:
            missing.append("GITSYNC_GITHUB_REPO")
        if self.github_token is None:
            missing.append("GITSYNC_GITHUB_TOKEN")
        if self.github_email is None:
            missing.append("GITSYNC_GITHUB_EMAIL")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required GitSync settings: {joined}")

    @property
    def github_remote_url(self) -> str:
        """Build the authenticated HTTPS remote URL for the target repository."""
        if self.github_repo is None or self.github_token is None:
            raise ValueError("GitHub repository and token must be configured")
        token = self.github_token.get_secret_value()
        return f"https://x-access-token:{token}@github.com/{self.github_repo}.git"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
