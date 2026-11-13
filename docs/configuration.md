# Configuration — Karna (Personal AI Chatbot)

All configuration is managed via environment variables, conventionally stored in `.env`
(templated by `.env.example`). Secrets are never hardcoded and never logged.

## Core Environment Variables

### Application & Database
| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `development` | Deployment environment (`development` or `production`) |
| `HOST` | No | `127.0.0.1` | Bind host |
| `PORT` | No | `8000` | Bind port |
| `DATABASE_URL` | No | `sqlite:///./data/chatbot.db` | SQLite database path |
| `MAX_HISTORY_MESSAGES` | No | `12` | Number of previous conversation turns preserved |
| `REQUEST_TIMEOUT_SECONDS` | No | `60` | Network request timeout for external calls |
| `SESSION_TIMEOUT_MINUTES` | No | `30` | Conversation session idle expiry in minutes |

### Telegram Bot API
| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes* | (empty) | Bot API token obtained from `@BotFather` |
| `TELEGRAM_ALLOWED_USER_IDS` | No | (empty) | Comma-separated allowed Telegram user IDs |

### Multi-Stage Local LLM Pipeline
| Variable | Required | Default | Description |
|---|---|---|---|
| `USE_PIPELINE` | No | `false` | Enable multi-stage pipeline routing (set `true` in local `.env`) |
| `LLM_FAST_URL` | No | `http://127.0.0.1:8081` | Base URL for Fast 2B/4B model (planning & quote filtering) |
| `LLM_SMART_URL` | No | `http://127.0.0.1:8082` | Base URL for Smart 9B model (factual synthesis & persona) |
| `MAX_PAGES` | No | `6` | Maximum web pages scraped during parallel gather |
| `PAGE_CHARS` | No | `6000` | Maximum characters processed per evidence bundle |
| `STAGE_TIMEOUT` | No | `180` | Stage execution timeout in seconds |
| `PIPELINE_MAX_CONCURRENT_JOBS` | No | `1` | Maximum parallel background research tasks |

### Legacy Local LLM (Single Model)
| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_BASE_URL` | No | (empty) | llama.cpp OpenAI-compatible base URL (used when `USE_PIPELINE=false`) |
| `LLM_MODEL` | No | (empty) | Discovered at runtime via `/v1/models` if unset |
| `LLM_API_KEY` | No | (empty) | Optional API key |

### Web Search & Information Retrieval
| Variable | Required | Default | Description |
|---|---|---|---|
| `SEARXNG_BASE_URL` | No | `http://127.0.0.1:8080` | SearXNG instance URL for web research |
| `SEARCH_CACHE_TTL_SECONDS` | No | `3600` | SQLite cache expiration for search results |
| `CRAWLER_TIMEOUT_SECONDS` | No | `15` | Timeout for individual webpage fetching |

---

## How Values Are Loaded

1. `config/settings.py` (`pydantic-settings`) reads `.env` then environment variables.
2. `app/config.py` exposes a typed `Config` wrapper across the codebase.
3. Secret fields (`TELEGRAM_BOT_TOKEN`, `LLM_API_KEY`, etc.) are masked in `__repr__` and logs.

## Security Notes

- `.env` is strictly excluded from version control in `.gitignore`.
- Only senders in `TELEGRAM_ALLOWED_USER_IDS` are processed; unauthorized messages are dropped.
- SSRF protections in `fetcher.py` prevent fetching localhost, private loopback, or LAN IPs.