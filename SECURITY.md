# Security Policy

## Scope

Deckhand is a **local-first** service. By default it binds to `127.0.0.1` and is not exposed to the network.

## What Deckhand accesses locally

- Claude Code OAuth credentials (macOS Keychain) for usage polling
- Cursor IDE JWT from local `state.vscdb` for usage polling
- Antigravity (`agy`) OAuth from Keychain for usage polling
- Session hooks from Claude Code and Cursor (stdin JSON piped to local ingest)
- AppleScript / `open` for focusing iTerm and Cursor windows

Deckhand does **not** include opt-in telemetry, cloud sync, or remote agent execution in core.

## API authentication

Core uses optional API keys with `read` or `write` scope. If none are configured, a temporary write key is generated at startup and logged to the console.

- Keep `config.toml` permissions restrictive (`chmod 600` recommended).
- Do not commit API keys or `config.toml` to version control.
- Hook commands reference `--config /abs/path/to/config.toml`; do not embed keys in hook shell commands.

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Report privately via [GitHub Security Advisories](https://github.com/LightbridgeLab/Deckhand/security/advisories/new) on this repository.

Include:

- Description of the issue and potential impact
- Steps to reproduce
- Your environment (macOS version, Deckhand version from `pyproject.toml`)

We aim to acknowledge reports within a few business days.

## Supported versions

Security fixes land on the latest release on `main`. Older tags may not receive backports unless noted in the advisory.
