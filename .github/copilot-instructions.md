# Copilot Instructions — MAMFast

MAMFast automates audiobook uploads to MAM: Libation discovery → staging (hardlink) → metadata (Audnex + MediaInfo) → torrent (mkbrr in Docker) → upload → Audiobookshelf import. Python 3.11+, strict typing, Pydantic v2.

## CLI (CRITICAL)

Global flags go BEFORE subcommand:
- ✅ `mamfast --dry-run abs-import`
- ❌ `mamfast abs-import --dry-run` (subcommands don't define their own)

## Non-negotiable rules

- Use `from __future__ import annotations`, `pathlib.Path`, and `logger = logging.getLogger(__name__)`.
- User-facing output MUST use `mamfast.console` Rich helpers (no `print()`).
- External calls (HTTP/Docker/qBittorrent/ABS) must have timeouts + `retry_with_backoff(...)` (no infinite retries).
- Never hand-build MAM paths/names. Use `utils/naming` builders + `MamPath` to enforce the 225-char limit (truncation uses hash suffix).
- mkbrr runs in Docker: convert paths with `host_to_container_path()`; never pass `/mnt/user/...` directly to containers.
- Hardlinks require same filesystem: `library_root`, `seed_root`, and ABS library must share mount (else copy + warn).
- Config precedence: `config/config.yaml` > `config/.env` > defaults. NEVER commit `.env`, `config.yaml`, `data/`, `logs/`.

## Changing behavior

- Prefer updates in `config/naming.json` + golden tests over editing `utils/naming*`.
- ABS import: ASIN drives duplicate detection; folders without `{ASIN...}` follow "unknown ASIN" policy.

## Contributing

- New CLI command: add subparser in `cli.py:build_parser()`, `set_defaults(func=...)`, handler returns `int` and respects `args.dry_run`.
- New config option: update `config.py` dataclass → `schemas/config.py` → `config.yaml.example` → tests.
- Tests: pytest; one test module per source module; mock Docker/qbit/network; use `tests/conftest.py` helpers (e.g., `make_cmd_result()`).

Key modules: `models.py` (AudiobookRelease, NormalizedBook, MamPath, ReleaseStatus, SeriesInfo), `workflow.py`, `abs/`, `schemas/`, `console.py`, `utils/retry.py`, `utils/naming*`.
