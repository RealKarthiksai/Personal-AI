# Local AI Chatbot (Karna)

A lightweight AI chatbot that receives Telegram messages, replies through a
locally hosted llama.cpp LLM, and persists conversation history in SQLite.

Built with Python, python-telegram-bot, FastAPI, llama.cpp OpenAI-compatible API,
HTTPX, and SQLite.

## Quick start

```bash
cd /home/vhanghar/Karna
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Telegram bot token and allowed user IDs
./scripts/start_all.sh
./scripts/health_check.sh
```

## Services & Endpoints

- **Telegram Bot**: Long polling listener (`python -m app.telegram_bot`)
- **Local LLM**: OpenAI-compatible server at `http://127.0.0.1:8001/v1`
- **FastAPI**: Health endpoint at `GET /health` (`http://127.0.0.1:8000/health`)

## Tests

```bash
. .venv/bin/activate
python -m pytest tests/ -v
```

## Constraints

- No LangChain / LangGraph / Redis / Qdrant.
- Telegram long polling (no webhooks or public ports required).
- No cloud LLM fallback — local llama.cpp only.
- Secrets never logged; `.env` excluded from Git.