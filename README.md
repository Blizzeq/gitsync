# GitSync

Mirror your GitLab activity into a private GitHub repository so your contribution graph reflects the work you actually do.

GitSync fetches commits, merge requests, issues and reviews from GitLab, then creates timestamped empty commits in a GitHub repo. Each GitLab event becomes one commit with the original message and date, keeping your GitHub profile green and your history readable.

## Features

- Async core engine (httpx + aiosqlite)
- CLI with `sync`, `serve`, `status` and `init` commands
- Web dashboard (FastAPI + Jinja2 + HTMX + Tailwind CSS)
- GitHub Actions workflow for daily scheduled sync
- 1:1 event mapping (each GitLab activity = one GitHub commit)
- Deduplication across event sources
- Rate limit handling with exponential backoff

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Interactive configuration
gitsync init

# Run a single sync
gitsync sync

# Start the web dashboard
gitsync serve
```

Dashboard available at `http://127.0.0.1:8765`

## Required environment variables

| Variable | Description |
|----------|-------------|
| `GITSYNC_GITLAB_TOKEN` | GitLab personal access token (`read_api` scope) |
| `GITSYNC_GITLAB_USERNAME` | Your GitLab username |
| `GITSYNC_GITHUB_REPO` | Target GitHub repository (`owner/name`) |
| `GITSYNC_GITHUB_TOKEN` | GitHub personal access token |
| `GITSYNC_GITHUB_EMAIL` | Email linked to your GitHub account |

Optional:

| Variable | Default |
|----------|---------|
| `GITSYNC_GITLAB_URL` | `https://gitlab.com` |
| `GITSYNC_DB_PATH` | `~/.gitsync/gitsync.db` |
| `GITSYNC_GITHUB_BRANCH` | `main` |
| `GITSYNC_APP_HOST` | `127.0.0.1` |
| `GITSYNC_APP_PORT` | `8765` |

## GitHub Actions setup

1. Create a private GitHub repository (e.g. `gitlab-activity`)
2. Add secrets in the repo settings:
   - `GITLAB_TOKEN` - your GitLab PAT
   - `GITLAB_USERNAME` - your GitLab username
   - `GIT_EMAIL` - email linked to your GitHub account
3. Copy `.github/workflows/sync.yml` to your repo
4. The workflow runs daily at 06:17 UTC (configurable via cron)

The built-in `GITHUB_TOKEN` handles push access automatically.

## Architecture

```text
GitLab API  -->  [Sync Engine]  -->  GitHub (git push)
                      |
                 [SQLite DB]
                      |
                  [Web UI]
```

`src/gitsync/core` has zero web dependencies and runs standalone in CLI and GitHub Actions.

## Commit format

Each mirrored event produces a commit like:

```
[commit] group/project: Fix database connection pooling
[mr-merged] group/project: Add user authentication flow
[issue-created] group/project: Bug: login fails on Safari
[mr-reviewed] group/project: Refactor API endpoints
```

The commit timestamp matches the original GitLab event date.

## GitHub contribution graph requirements

For commits to count on the contribution graph:

- The repository must belong to you (not a fork)
- Commits must land on the default branch
- The commit email must be linked to your GitHub account
- Enable **Include private contributions** in your GitHub profile settings

## Development

```bash
# Format
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Tests with coverage
pytest --cov=src/gitsync --cov-report=term-missing --cov-fail-under=80

# All checks
make check
```

## License

MIT
