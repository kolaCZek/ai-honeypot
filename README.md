# AI Honeypot 🕸️

Self-hosted AI-driven honeypot web. Every source IP gets its own "universe" of LLM-generated pages — a fog-of-war game for scrapers, scanner kiddies, and script bots. The goal is to waste their time, poison their databases with nonsense, and collect stats on who's attacking and how.

## How it works

1. A bot hits `/` → a **per-IP** fake landing page is generated (random scenario out of 10: internal portal, SaaS dashboard, billing, CMS, ...).
2. It follows a link → the LLM generates the next page matching the path (`/settings` = settings UI, `/login` = login form, `/api/users` = JSON).
3. A second visit to the same URL → returns the cached version from DB (no LLM call, no inconsistency).
4. **Link gating**: every internal link carries `?_t=<hmac>`. Without a valid token for that IP+path = nginx-style 404. A bot can't just brute-force URLs.
5. **Bait endpoints** (`/admin`, `/.env`, `/.git/config`, `/backup.sql`, `/wp-login.php`, ...) work directly without a token — we want the bot to "find" something and get stuck.
6. **Fake login**: POST credentials are stored, 75% of attempts "succeed" (redirect to fake admin dashboard), 25% return "Invalid".
7. **Slowdown**: every request sleeps randomly 10–30s (configurable, whitelist for localhost).
8. **Rate limit**: max 3 concurrent / IP via Redis.
9. **Retention**: keeps the last N IPs (LRU) and/or TTL in days — then the IP and its page universe are deleted.

## Architecture

```
            ┌──────────┐
   Bots ───►│ Honeypot │◄─── SQLite ◄─── Dashboard ◄─── Admin
            │  :8888   │       │           :8080
            └────┬─────┘     Redis
                 │             │
                 ▼             │
              OpenAI-compat ───┘
              LLM endpoint
```

Two FastAPI services share SQLite (volume) and Redis. Honeypot serves the bots, dashboard serves you.

## Quick start

```bash
git clone https://github.com/kolaCZek/ai-honeypot.git
cd ai-honeypot
cp config.yaml.example config.yaml
# edit llm.api_key, dashboard.basic_auth.password
docker compose up -d --build
```

- Honeypot: http://localhost:8888
- Dashboard: http://localhost:8080 (basic auth per config)
- Prometheus metrics: http://localhost:8080/metrics

## Configuration

Everything in `config.yaml`. Key blocks:

| Section | Description |
|---------|-------------|
| `llm` | OpenAI-compatible endpoint, model, token, cost estimate |
| `honeypot.slowdown` | min/max sleep per request, on/off |
| `honeypot.rate_limit.max_concurrent_per_ip` | per-IP parallel limit |
| `honeypot.retention.max_ips` + `ttl_days` | LRU + TTL (both nullable) |
| `honeypot.whitelist_ips` | bypass slowdown/rate limit |
| `honeypot.bait_endpoints` | list of directly accessible bait URLs |
| `honeypot.fake_login.success_ratio` | 0.0–1.0 |
| `dashboard.basic_auth` | login for admin UI |

The secret HMAC key for link tokens is auto-generated on first start into `/data/secret.key`. Back it up.

## Dashboard

- **Live feed** — last 100 requests, filters per IP/country/UA/bait
- **Per-IP detail** — Mermaid click-through graph + timeline + credential attempts
- **Top baits** — which bait endpoint hooks the most bots
- **Stats** — tokens spent, estimated $ cost, top countries, bot vs human UA
- **/metrics** — Prometheus (auth required)

## Tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/pytest -q
```

## Ethics / legal

No malware, no real exploits, no tampering with third-party cookies. Just totally made-up content and fake endpoints. Robots.txt can disallow everything (bots ignore it anyway). If you expose the honeypot on a public IP, be mindful of transparent disclosure for security researchers (PoC yes, MITM no).

## License

MIT
