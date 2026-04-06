"""Git operations used to mirror activity into GitHub commits."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from gitsync.core.config import Settings
from gitsync.core.models import GitLabEvent

logger = logging.getLogger(__name__)


class GitHubClient:
    """Create timestamped commits in a target GitHub repository."""

    def __init__(self, settings: Settings, worktree: Path | None = None) -> None:
        self.settings = settings
        self._worktree = worktree
        self._tempdir: str | None = None

    async def create_contribution(self, event: GitLabEvent) -> str:
        """Create one empty commit mirroring a GitLab activity event."""
        logger.debug("Creating contribution for %s: %s", event.event_type, event.title)
        repo_dir = await self._ensure_repo()
        env = os.environ.copy()
        iso_timestamp = event.timestamp.isoformat()
        env.update(
            {
                "GIT_AUTHOR_NAME": self.settings.git_author_name,
                "GIT_AUTHOR_EMAIL": self.settings.github_email or "",
                "GIT_COMMITTER_NAME": self.settings.git_author_name,
                "GIT_COMMITTER_EMAIL": self.settings.github_email or "",
                "GIT_AUTHOR_DATE": iso_timestamp,
                "GIT_COMMITTER_DATE": iso_timestamp,
            }
        )
        await self._run_git(
            repo_dir,
            "commit",
            "--allow-empty",
            "-m",
            event.commit_message,
            env=env,
        )
        return (await self._run_git(repo_dir, "rev-parse", "HEAD")).strip()

    async def push_contributions(self) -> None:
        """Push mirrored commits to the configured GitHub branch."""
        logger.info("Pushing contributions to origin/%s", self.settings.github_branch)
        repo_dir = await self._ensure_repo()
        await self._run_git(repo_dir, "push", "origin", self.settings.github_branch)

    async def cleanup(self) -> None:
        """Delete the temporary worktree created for syncing."""
        if self._tempdir is not None:
            await asyncio.to_thread(shutil.rmtree, self._tempdir, True)
            self._tempdir = None

    async def _ensure_repo(self) -> Path:
        if self._worktree is not None:
            self._worktree.mkdir(parents=True, exist_ok=True)
            await self._prepare_repo(self._worktree)
            return self._worktree
        if self._tempdir is None:
            self._tempdir = tempfile.mkdtemp(prefix="gitsync-")
        repo_dir = Path(self._tempdir)
        await self._prepare_repo(repo_dir)
        return repo_dir

    async def _prepare_repo(self, repo_dir: Path) -> None:
        if (repo_dir / ".git").exists():
            return
        clone_result = await self._run_git_result(
            None,
            "clone",
            self.settings.github_remote_url,
            str(repo_dir),
        )
        if clone_result.returncode == 0:
            local_branch = await self._run_git_result(
                repo_dir,
                "show-ref",
                "--verify",
                f"refs/heads/{self.settings.github_branch}",
            )
            if local_branch.returncode == 0:
                await self._run_git(repo_dir, "checkout", self.settings.github_branch)
                return
            remote_branch = await self._run_git_result(
                repo_dir,
                "show-ref",
                "--verify",
                f"refs/remotes/origin/{self.settings.github_branch}",
            )
            if remote_branch.returncode == 0:
                await self._run_git(
                    repo_dir,
                    "checkout",
                    "-B",
                    self.settings.github_branch,
                    f"origin/{self.settings.github_branch}",
                )
            else:
                await self._run_git(
                    repo_dir,
                    "checkout",
                    "-b",
                    self.settings.github_branch,
                )
            return
        repo_dir.mkdir(parents=True, exist_ok=True)
        await self._run_git(repo_dir, "init")
        await self._run_git(repo_dir, "checkout", "-b", self.settings.github_branch)
        await self._run_git(
            repo_dir, "remote", "add", "origin", self.settings.github_remote_url
        )

    async def _run_git(
        self,
        repo_dir: Path | None,
        *args: str,
        env: dict[str, str] | None = None,
    ) -> str:
        completed = await self._run_git_result(repo_dir, *args, env=env)
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
        return completed.stdout

    async def _run_git_result(
        self,
        repo_dir: Path | None,
        *args: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["git", *args]
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            cwd=str(repo_dir) if repo_dir is not None else None,
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
        return completed
