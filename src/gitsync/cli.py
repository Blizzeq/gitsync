"""Typer CLI for GitSync."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from gitsync.core.config import Settings, get_settings
from gitsync.core.github_client import GitHubClient
from gitsync.core.gitlab_client import GitLabClient
from gitsync.core.storage import Storage
from gitsync.core.sync_engine import SyncEngine
from gitsync.web.app import create_app

app = typer.Typer(help="Synchronize GitLab activity into GitHub contributions.")
ENV_FILE_OPTION = typer.Option(Path(".env"), help="Path to the generated .env file.")


async def _run_sync_command(settings: Settings) -> None:
    settings.require_sync_configuration()
    storage = Storage(settings.db_path)
    async with GitLabClient(settings) as gitlab_client:
        engine = SyncEngine(
            gitlab_client=gitlab_client,
            github_client=GitHubClient(settings),
            storage=storage,
        )
        sync_run = await engine.run_sync()
    typer.echo(
        f"Sync finished with status={sync_run.status} events_synced={sync_run.events_synced}"
    )


@app.command()
def sync() -> None:
    """Run a single synchronization cycle."""
    asyncio.run(_run_sync_command(get_settings()))


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Host to bind the web UI to."),
    port: int | None = typer.Option(None, help="Port to bind the web UI to."),
) -> None:
    """Start the local FastAPI web UI."""
    settings = get_settings()
    application = create_app(settings)
    uvicorn.run(
        application,
        host=host or settings.app_host,
        port=port or settings.app_port,
        log_level="info",
    )


@app.command()
def status() -> None:
    """Show the most recent synchronization status."""
    settings = get_settings()
    storage = Storage(settings.db_path)

    async def _status() -> None:
        await storage.initialize()
        sync_run = await storage.get_last_sync_run()
        if sync_run is None:
            typer.echo("No syncs have been recorded yet.")
            return
        typer.echo(
            " | ".join(
                [
                    f"id={sync_run.id}",
                    f"status={sync_run.status}",
                    f"events={sync_run.events_synced}",
                    f"finished_at={sync_run.finished_at}",
                ]
            )
        )

    asyncio.run(_status())


@app.command()
def init(
    env_file: Path = ENV_FILE_OPTION,
) -> None:
    """Generate a local .env configuration file interactively."""
    gitlab_url = typer.prompt("GitLab URL", default="https://gitlab.com")
    gitlab_username = typer.prompt("GitLab username")
    gitlab_token = typer.prompt("GitLab PAT (read_api)", hide_input=True)
    github_repo = typer.prompt("GitHub repository (owner/name)")
    github_token = typer.prompt("GitHub token", hide_input=True)
    github_email = typer.prompt("GitHub email used for contributions")
    github_branch = typer.prompt("GitHub branch", default="main")
    db_default = str(get_settings().db_path)
    db_path = typer.prompt("SQLite DB path", default=db_default)

    content = "\n".join(
        [
            f"GITSYNC_GITLAB_URL={gitlab_url}",
            f"GITSYNC_GITLAB_USERNAME={gitlab_username}",
            f"GITSYNC_GITLAB_TOKEN={gitlab_token}",
            f"GITSYNC_GITHUB_REPO={github_repo}",
            f"GITSYNC_GITHUB_TOKEN={github_token}",
            f"GITSYNC_GITHUB_EMAIL={github_email}",
            f"GITSYNC_GITHUB_BRANCH={github_branch}",
            f"GITSYNC_DB_PATH={db_path}",
        ]
    )
    env_file.write_text(f"{content}\n", encoding="utf-8")
    typer.echo(f"Configuration written to {env_file}")
