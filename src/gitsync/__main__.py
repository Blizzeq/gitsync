"""Module entrypoint for python -m gitsync."""

from gitsync.cli import app


def main() -> None:
    """Run the CLI application."""
    app()


if __name__ == "__main__":
    main()
