# Installation — Local WhatsApp AI Chatbot

Prerequisites:
- Python 3.10+ (tested with Python 3.14)
- A running llama.cpp server (OpenAI-compatible API) for local inference
- Meta WhatsApp Business Cloud API credentials (see STAGE2_SETUP.md)

## 1. Clone / create the project

```bash
cd /home/vhanghar/Karna
```

## 2. Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## 3. Configure the environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `LLM_BASE_URL` — verified llama.cpp endpoint (e.g. `http://127.0.0.1:8001/v1`)
- WhatsApp Cloud API credentials (from Meta dashboard)
- `WHATSAPP_VERIFY_TOKEN` — a secret string you choose for webhook verification
- `WHATSAPP_ALLOWED_SENDER_IDS` — comma-separated E.164 phone numbers allowed to talk to the bot

Never commit `.env`. It is excluded by `.gitignore`.

## 4. Verify the local LLM endpoint

```bash
python scripts/verify_llama.py
```

This confirms `GET {LLM_BASE_URL}/models` works and discovers the model identifier.

## 5. Start the application

```bash
./scripts/start.sh
```

Or manually:

```bash
. .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 6. Verify it is running

```bash
./scripts/health_check.sh
```

Expected: HTTP 200 on `GET /health` with `{"status": "ok", ...}`.

## 7. Stop the application

```bash
./scripts/stop.sh
```

## Notes

- The app binds only to `127.0.0.1:8000`. Public HTTPS exposure is handled by
  Cloudflare Tunnel (see STAGE2_SETUP.md).
- No frontend is built. WhatsApp is the only user-facing interface.
- No cloud LLM is used; only the verified local llama.cpp endpoint.