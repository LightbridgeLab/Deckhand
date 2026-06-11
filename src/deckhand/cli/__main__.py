"""Allow ``python -m deckhand`` as a CLI entry point."""

from deckhand.cli.main import app

if __name__ == "__main__":
    app()
