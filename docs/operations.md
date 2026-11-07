# Operations — Local WhatsApp AI Chatbot

## Start / stop / health

```bash
# Start
./scripts/start.sh

# Health check
./scripts/health_check.sh

# Stop
./scripts/stop.sh
```

## systemd user service (optional)

A user-level systemd unit is provided at `service/karna-chatbot.service`.

Install (after the app is operational):

```bash
mkdir -p ~/.config/systemd/user
cp service/karna-chatbot.service ~/.config/systemd/user/karna-chatbot.service
systemctl --user daemon-reload
systemctl --user enable --now karna-chatbot.service
```

The service:
- Runs as the invoking user (`User=%i`), never root.
- Uses the project virtual environment.
- Loads `.env` via `EnvironmentFile`.
- Restarts on failure (`Restart=on-failure`).
- Binds only to `127.0.0.1:8000` (Cloudflare Tunnel handles public ingress).

## Logs

Logs are structured single-line JSON-ish output to stdout with `request_id` and
`message_id` fields for tracing. Secret values are redacted.

## Database

SQLite database lives at `data/chatbot.db` (configurable via `DATABASE_URL`).
Schema is auto-created on startup (`senders`, `messages` tables).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Application health (no secrets) |
| GET | `/webhook/whatsapp` | Meta webhook challenge verification |
| POST | `/webhook/whatsapp` | Inbound WhatsApp message events |

## No cloud fallback

The application only uses the verified local llama.cpp endpoint. No cloud LLM
is used under any circumstance.