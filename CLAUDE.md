# CLAUDE.md — context for AI coding agents

This is an AI-driven self-hosted honeypot. Two FastAPI services sharing SQLite + Redis, all wired via `docker-compose.yml`.

## Repo layout

```
honeypot/        # public-facing service on :8888 (where bots come in)
  main.py        # FastAPI factory + lifespan (init_db, redis, retention sweeper)
  routes.py      # / index, /{path} dispatcher, POST credential capture
  link_token.py  # HMAC sign/verify + sanitize_and_sign_links (bs4 + json)
  rate_limit.py  # IpConcurrentLimiter (Redis INCR/EXPIRE)
  slowdown.py    # apply_slowdown (uniform sleep + whitelist)
  error_pages.py # nginx_404/500/429 mimicry
  bait.py        # is_bait + random_login_success
  prompts/       # html_page.j2, api_json.j2, plain_text.j2, index_scenarios.yaml

dashboard/       # admin UI on :8080
  main.py        # FastAPI factory
  routes.py      # / live feed, /ip/{ip}, /baits, /stats
  auth.py        # HTTPBasic constant-time
  metrics.py     # Prometheus collectors (per-scrape from DB aggregates)
  templates/     # Jinja2 (base, live, ip_detail, baits, stats)

shared/          # used by both services
  config.py      # Pydantic v2 Settings + load_config + auto-secret-key
  db.py          # async aiosqlite engine + sessionmaker + init_db
  models.py      # SQLAlchemy 2.0: IpUniverse, Page, LinkEdge, RequestLog, CredentialAttempt
  llm.py         # LLMClient (httpx async, OpenAI-compatible /chat/completions)
  page_type.py   # detect_page_type → "html" | "json" | "text"
  retention.py   # sweep_retention (LRU max_ips + TTL ttl_days)
  ua.py          # parse_ua → bot detection

tests/           # pytest, asyncio_mode=auto, fakeredis + in-memory sqlite
```

## Key invariants (DO NOT BREAK)

1. **Per-IP isolation**: every `Page` row is `UNIQUE(ip, path)`. Page generation is per-IP.
2. **Link gating**: a non-bait URL without a valid `?_t=` → nginx 404. Token = `hmac_sha256(secret, f"{ip}|{path}")[:16].hex()`.
3. **The AI never refers to itself**: prompts in `honeypot/prompts/*.j2` have explicit prohibitions. When adding page types, keep that style.
4. **No OpenAI SDK** — `httpx` only. Endpoint always from `settings.llm.endpoint` (OpenAI-compatible).
5. **LLM error → nginx 500**, never print a traceback or the string "OpenAI".
6. **Dashboard is read-only against the DB**, but it does write to `config.yaml` (via `/settings`) and publishes a `reload` message on the Redis channel `config:reload`.
7. **Whitelist `testclient`** in the test config — otherwise the middleware blocks ASGI tests.

## Hot-reload mechanism

`shared/config_reload.py` defines `publish_reload(redis)` and `subscribe_reload(redis, on_reload)` over the Redis channel `config:reload`.

- The **dashboard** publishes on this channel after every successful `POST /settings` (and after persisting the YAML via `save_config`).
- The **honeypot** spawns a `subscribe_reload(...)` background task in its lifespan. On every message it reloads `Settings` from disk, swaps `app.state.settings` atomically, and rebuilds `app.state.llm` via `app.state.llm_factory(new_settings)` (closing the old client). All middleware and routes must therefore read settings via `request.app.state.settings`, **never** capture them in closures at startup.
- `save_config` is atomic (tempfile + `os.replace`) and rotates the last 10 timestamped backups (`config.yaml.bak-<UTC>`) next to the file. The `secret_key` bytes field is excluded from the YAML dump.

## Workflow

- Dependencies: `python3.12 -m venv .venv && .venv/bin/pip install -e .[dev]`
- Tests: `.venv/bin/pytest -q` (everything must pass before commit)
- Local run:
  - honeypot: `CONFIG_PATH=./config.yaml .venv/bin/uvicorn honeypot.main:create_app --factory --port 8888`
  - dashboard: `CONFIG_PATH=./config.yaml .venv/bin/uvicorn dashboard.main:create_app --factory --port 8080`
- Docker: `docker compose up -d --build`

## Typical changes

- **Add a page type** (e.g. graphql): extend `detect_page_type`, add `prompts/<type>.j2`, wire mapping in `routes.py` generic handler.
- **New bait**: add to `config.yaml` → `honeypot.bait_endpoints`. No code.
- **Change slowdown profile**: `config.yaml` → `honeypot.slowdown`.
- **New metric**: extend `dashboard/metrics.py` with a collector + populate from DB.
- **New index scenario**: add to `honeypot/prompts/index_scenarios.yaml`.

## What NOT to do

- Do not add schema migrations (Alembic). The user backs up SQLite manually; a major schema change = drop the volume.
- Do not cache per-IP responses in Redis — the single source of truth is the SQLite `page` table.
- Do not make synchronous LLM calls (always async).
- Do not log full credential values outside the `credential_attempt` table (no plaintext to stdout).

## Plan and history

Implementation plan and decisions: `~/.hermes/plans/2026-06-02-ai-honeypot.md` (outside the repo).
