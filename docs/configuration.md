# Configuration — Local WhatsApp AI Chatbot

All configuration is via environment variables, conventionally stored in `.env`
(templated by `.env.example`). Secrets are never hardcoded and never logged.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENV` | No | `development` | Deployment environment |
| `HOST` | No | `127.0.0.1` | Bind host |
| `PORT` | No | `8000` | Bind port |
| `LLM_BASE_URL` | Yes* | (empty) | llama.cpp OpenAI-compatible base URL |
| `LLM_MODEL` | No | (empty) | Discovered at runtime if unset |
| `LLM_API_KEY` | No | (empty) | API key for llama.cpp (if any) |
| `WHATSAPP_ACCESS_TOKEN` | Yes* | (empty) | Meta WhatsApp access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes* | (empty) | Meta Phone Number ID |
| `WHATSAPP_APP_SECRET` | Yes* | (empty) | Meta App Secret (signature validation) |
| `WHATSAPP_VERIFY_TOKEN` | Yes* | (empty) | Webhook verification token |
| `WHATSAPP_ALLOWED_SENDER_IDS` | No | (empty) | Comma-separated E.164 allowed senders |
| `WHATSAPP_GRAPH_API_VERSION` | No | `v22.0` | Meta Graph API version |
| `DATABASE_URL` | No | `sqlite:///./data/chatbot.db` | SQLite database path |
| `MAX_HISTORY_MESSAGES` | No | `12` | Conversation history window |
| `REQUEST_TIMEOUT_SECONDS` | No | `60` | HTTP request timeout |

\* Required for WhatsApp/LLM functionality; app starts without them but those
features will not work.

## How values are loaded

`config/settings.py` (pydantic-settings) reads `.env` then environment
variables. `app/config.py` exposes a typed `Config` wrapper. Secret fields are
masked in `__repr__`/`__str__` so they never appear in logs.

## Security notes

- `.env` is excluded from Git (see `.gitignore`).
- Webhook signature validation uses `WHATSAPP_APP_SECRET` against the raw body
  (`X-Hub-Signature-256`).
- Only senders in `WHATSAPP_ALLOWED_SENDER_IDS` receive responses.
- The access token is redacted in all log output (`redact()` helper).