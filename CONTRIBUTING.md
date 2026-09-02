# Contributing

Thanks for helping improve Deckhand.

## Before you start

- **Bugs and features:** [open an issue](https://github.com/LightbridgeLab/Deckhand/issues) before large changes so we can align on scope.
- **Architecture and conventions:** read [AGENTS.md](AGENTS.md) — especially the "AI coding agents are the point" principle.

## Development setup

```bash
uv sync --all-extras
make config
make dev
```

## Quality gate

```bash
make check         # ruff lint + format check + pytest
```

All PRs should pass `make check`.

## Pull requests

1. Branch from `main` (or follow the branch model your team uses).
2. Keep changes focused — one concern per PR.
3. Update docs when behavior or user-facing setup changes.
4. Link the issue in the PR description.

Shipped changes are documented in [GitHub Releases](https://github.com/LightbridgeLab/Deckhand/releases), not a changelog file.

## Extending Deckhand

- **Core plugins** (actions, signals, state pollers): [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md)
- **OpenDeck bridge** (Stream Deck actions): [opendeck-plugin/README.md](opendeck-plugin/README.md)
- **HTTP / WebSocket API**: [docs/API.md](docs/API.md), [docs/EVENTS.md](docs/EVENTS.md)

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.
