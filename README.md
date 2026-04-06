# GitSync

Mirror your GitLab activity into a private GitHub repository so your contribution graph reflects the work you actually do.

GitSync fetches your real commits and merged MRs from GitLab, then creates timestamped empty commits in a GitHub repo. Each event becomes one commit with the original message and date -- keeping your GitHub profile green and your history readable.

## Why?

If you work on GitLab at your job, your GitHub profile looks empty. GitSync fixes that by syncing your activity daily via a GitHub Action. No code is copied -- only commit messages and timestamps.

## What gets synced

| Source | Synced as | Example commit |
|--------|-----------|----------------|
| Your commits (excluding merge commits) | `[commit]` | `[commit] my-org/backend: fix timezone handling` |
| Your merged MRs | `[mr-merged]` | `[mr-merged] my-org/backend!145: add OAuth2 provider` |

Auto-generated merge commits (`Merge branch 'x' into 'main'`) and generic push events are filtered out automatically.

## Setup guide

### Prerequisites

- Python 3.11+
- A GitLab account with a Personal Access Token
- A GitHub account with a Personal Access Token

### Step 1: Create a private GitHub repository

Go to [github.com/new](https://github.com/new) and create a **private** repository (e.g. `gitlab-activity`). Check "Add a README file" to initialize it.

### Step 2: Create access tokens

**GitLab token:**
1. GitLab -> Edit Profile -> Access Tokens -> Add new token
2. Name: `gitsync`, Expiration: 1 year
3. Scopes: check **`read_api`** only
4. Create and copy the token

**GitHub token:**
1. GitHub -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens
2. Generate new token, name: `gitsync`, expiration: 1 year
3. Repository access: select **only** your `gitlab-activity` repo
4. Permissions: Contents -> **Read and write**
5. Generate and copy the token

### Step 3: Install and configure GitSync

```bash
git clone https://github.com/Blizzeq/gitsync.git
cd gitsync
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Interactive setup -- creates a .env file
gitsync init
```

The `init` command will ask for:
- GitLab URL (default: `https://gitlab.com`)
- GitLab username
- GitLab token (hidden input)
- GitHub repository (`owner/repo-name`)
- GitHub token (hidden input)
- GitHub email (must match your GitHub account)
- GitHub branch (default: `main`)

### Step 4: Run your first sync

```bash
gitsync sync
```

This fetches all your GitLab activity and creates matching commits in your GitHub repo. The first run may take a minute depending on how much history you have.

### Step 5: Set up daily automation (GitHub Actions)

Add three secrets to your **`gitlab-activity`** repository:

1. Go to `github.com/your-username/gitlab-activity/settings/secrets/actions`
2. Click "New repository secret" for each:

| Secret name | Value |
|-------------|-------|
| `GITLAB_TOKEN` | Your GitLab Personal Access Token |
| `GITLAB_USERNAME` | Your GitLab username |
| `GIT_EMAIL` | Email linked to your GitHub account |

Then create `.github/workflows/sync.yml` in your `gitlab-activity` repo:

```yaml
name: GitSync - Daily Activity Sync

on:
  schedule:
    - cron: '17 6 * * *'  # Daily at 06:17 UTC -- adjust to your timezone
  workflow_dispatch:       # Allows manual runs from the Actions tab

permissions:
  contents: write

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install GitSync
        run: pip install git+https://github.com/Blizzeq/gitsync.git

      - name: Run sync
        env:
          GITSYNC_GITLAB_TOKEN: ${{ secrets.GITLAB_TOKEN }}
          GITSYNC_GITLAB_USERNAME: ${{ secrets.GITLAB_USERNAME }}
          GITSYNC_GITLAB_URL: https://gitlab.com
          GITSYNC_GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITSYNC_GITHUB_REPO: ${{ github.repository }}
          GITSYNC_GITHUB_EMAIL: ${{ secrets.GIT_EMAIL }}
        run: python -m gitsync sync
```

`GITHUB_TOKEN` is provided automatically by GitHub Actions -- you don't need to create it.

### Step 6: Enable private contributions on GitHub

Go to your GitHub profile -> click your contribution graph -> check **"Include private contributions on my profile"**. This makes your synced activity visible as green squares without revealing repository details.

## Web dashboard

GitSync includes a local web UI for monitoring and manual sync:

```bash
gitsync serve
```

Open `http://127.0.0.1:8765` to see:
- **Dashboard** -- stats, 90-day activity chart, sync status, one-click manual sync
- **Activity** -- full event history with filters and search
- **Settings** -- configure tokens and sync preferences, test connection

## CLI commands

| Command | Description |
|---------|-------------|
| `gitsync sync` | Run one synchronization cycle |
| `gitsync serve` | Start the web dashboard |
| `gitsync status` | Show the most recent sync result |
| `gitsync init` | Generate a `.env` config file interactively |

## How deduplication works

GitSync never creates duplicate commits. Before syncing, it checks:

1. **Local SQLite database** -- tracks every event that was already mirrored
2. **Git history** -- reads existing commit messages from the target repo

This means the GitHub Action works correctly even though it starts with a fresh filesystem on every run.

## Configuration reference

All settings are read from environment variables (prefixed `GITSYNC_`) or a `.env` file.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITSYNC_GITLAB_TOKEN` | Yes | -- | GitLab PAT with `read_api` scope |
| `GITSYNC_GITLAB_USERNAME` | Yes | -- | Your GitLab username |
| `GITSYNC_GITHUB_REPO` | Yes | -- | Target repo (`owner/name`) |
| `GITSYNC_GITHUB_TOKEN` | Yes | -- | GitHub PAT with contents write access |
| `GITSYNC_GITHUB_EMAIL` | Yes | -- | Email linked to your GitHub account |
| `GITSYNC_GITLAB_URL` | No | `https://gitlab.com` | GitLab instance URL |
| `GITSYNC_GITHUB_BRANCH` | No | `main` | Target branch for commits |
| `GITSYNC_DB_PATH` | No | `~/.gitsync/gitsync.db` | SQLite database path |
| `GITSYNC_SYNC_COMMITS` | No | `true` | Sync commit events |
| `GITSYNC_SYNC_MERGE_REQUESTS` | No | `true` | Sync merged MR events |
| `GITSYNC_APP_HOST` | No | `127.0.0.1` | Web UI host |
| `GITSYNC_APP_PORT` | No | `8765` | Web UI port |

## GitHub contribution graph requirements

For commits to appear on your contribution graph:

- The repository must belong to you (not a fork)
- Commits must land on the default branch
- The commit email must be linked to your GitHub account
- "Include private contributions" must be enabled on your profile

## Architecture

```text
GitLab API  -->  [Sync Engine]  -->  GitHub (git push)
                      |
                 [SQLite DB]
                      |
                  [Web UI]
```

The `core/` package has zero web dependencies and runs standalone in CLI and GitHub Actions. The `web/` package adds FastAPI + Jinja2 + HTMX for the dashboard.

## Development

```bash
pip install -e .[dev]

# Format
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Tests with coverage
pytest --cov=src/gitsync --cov-report=term-missing --cov-fail-under=80

# All checks at once
make check
```

## Tech stack

- **Python 3.11+** with full type annotations
- **httpx** -- async HTTP client for GitLab API
- **aiosqlite** -- async SQLite for persistence
- **FastAPI + Jinja2 + HTMX** -- web dashboard (no JavaScript framework)
- **Tailwind CSS v4** -- styling via CDN
- **Typer** -- CLI framework
- **pydantic-settings** -- configuration management

## License

MIT
