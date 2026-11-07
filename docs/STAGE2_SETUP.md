# Stage 2 — WhatsApp API, Webhook and Environment Configuration

**Local WhatsApp AI Chatbot** — external service integrations and local
application configuration. No chatbot logic is implemented yet.

> ⚠️ WhatsApp connectivity is NOT operational until a real webhook verification
> (GET /webhook/whatsapp challenge) has succeeded against Meta's servers.
> Do not claim it is operational before that step.

---

## 1. Current status of this repository

| Item | Status |
|------|--------|
| Stage 1 codebase | Not present — workspace was empty when Stage 2 began |
| Python virtual environment | `.venv/` created; FastAPI, uvicorn, python-dotenv, httpx, pydantic-settings installed |
| `.env.example` | Created (template only, no secrets) |
| `.gitignore` | Created — excludes `.env`, `.venv/`, `data/` |
| `config/settings.py` | Created — pydantic-settings loader, secrets masked in repr |
| `scripts/verify_llama.py` | Created — verifies local llama.cpp `/models` endpoint |
| `docs/STAGE2_SETUP.md` | This file |
| `service/karna-chatbot.service` | Created — systemd user service template (not installed/started) |
| Cloudflare Tunnel | Documented below (not yet created — manual) |
| Meta WhatsApp app / webhook | Documented below (manual — credentials not yet obtained) |
| llama.cpp server | Documented below (not verified — not running) |

## 2. Meta WhatsApp Cloud API — prerequisites

Use the official [Meta WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api).
Do not use outdated API versions or unofficial WhatsApp libraries.

### 2.1 Values you must obtain from Meta

| Credential | Where to find it | Manual step required? |
|------------|------------------|----------------------|
| Meta Developer App | Meta for Developers dashboard → My Apps | Yes |
| WhatsApp Business Account | Meta dashboard → WhatsApp → Get Started | Yes |
| Dedicated WhatsApp phone number | Added in Meta dashboard (not your personal SIM) | Yes |
| Phone Number ID | WhatsApp → Phone numbers → your number | Yes |
| Access token | WhatsApp → Get started → "Generate token" | Yes |
| App Secret | Meta Dashboard → Settings → Basic → App Secret | Yes |
| Webhook verify token | You choose any string; set in webhook config | Yes |
| Authorized sender phone number | Your own WhatsApp number (E.164) for testing | Yes |

### 2.2 Exact manual steps (Meta dashboard)

1. Create a **Meta Developer App** at https://developers.facebook.com/ → My Apps → Create App → choose "Business" → complete verification.
2. Add the **WhatsApp** product to your app.
3. Set up a **WhatsApp Business Account** linked to the app.
4. Add a dedicated **WhatsApp phone number** to the account (this is the number users message; it is NOT your personal number).
5. Note the **Phone Number ID** displayed for that number.
6. Generate a long-lived **WhatsApp access token** (WhatsApp → Get started → Generate token). Copy it immediately.
7. Note the **App Secret** (Settings → Basic → App Secret, reveal with password).
8. Choose a **webhook verify token** (any secret string you create, e.g. a random 32-char string). Record it — you will enter it both in Meta and in `.env` as `WHATSAPP_VERIFY_TOKEN`.
9. In the WhatsApp product → Webhooks, subscribe to the `messages` field (incoming message events).

> None of the above values exist in this repository yet. You must complete the manual Meta setup and paste the values into a local `.env` file (see section 6).

## 3. Webhook preparation

The eventual webhook endpoint (to be implemented in a later stage):

```
GET  /webhook/whatsapp
POST /webhook/whatsapp
```

### 3.1 GET — webhook verification challenge

Meta sends a GET request with these query parameters:
- `hub.mode` = `subscribe`
- `hub.challenge` = a random string
- `hub.verify_token` = the token you configured

The endpoint must return `hub.challenge` unchanged when `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN`.

### 3.2 POST — incoming message events

Receives JSON message events from Meta. Must validate the
`X-Hub-Signature-256` header against the raw request body using `WHATSAPP_APP_SECRET`.

### 3.3 Configuration values (go in `.env`)

| Variable | Meaning |
|----------|---------|
| `WHATSAPP_ACCESS_TOKEN` | Token generated in Meta dashboard |
| `WHATSAPP_PHONE_NUMBER_ID` | ID of the dedicated WhatsApp number |
| `WHATSAPP_APP_SECRET` | App Secret for signature validation |
| `WHATSAPP_VERIFY_TOKEN` | Token used for GET challenge verification |
| `WHATSAPP_ALLOWED_SENDER_IDS` | Comma-separated E.164 sender IDs allowed to interact |
| `WHATSAPP_GRAPH_API_VERSION` | Graph API version, e.g. `v22.0` |

### 3.4 Webhook callback URL (documented, not yet configured)

After Cloudflare Tunnel is running, the public callback URL will look like:

```
https://<tunnel-subdomain>.trycloudflare.com/webhook/whatsapp
```

or, with a custom domain:

```
https://<your-domain>/webhook/whatsapp
```

Enter this in Meta dashboard → WhatsApp → Webhooks → Callback URL, with
verify token = `WHATSAPP_VERIFY_TOKEN`.

## 4. Cloudflare Tunnel — local webhook connectivity

The local FastAPI app listens on `127.0.0.1:8000`. Cloudflare Tunnel exposes
only `/webhook/whatsapp` publicly over HTTPS. No other local services are
exposed. A stable named tunnel is preferred; a temporary dev tunnel is
acceptable for initial testing.

### 4.1 Install cloudflared

```bash
# Example for Linux x86_64 (adjust arch/OS as needed)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo install cloudflared-linux-amd64 /usr/local/bin/cloudflared
cloudflared --version
```

### 4.2 Authenticate

```bash
cloudflared tunnel login
# Follow the browser flow to authorize this machine with your Cloudflare account.
```

### 4.3 Create a named tunnel

```bash
cloudflared tunnel create karna-whatsapp
# Note the Tunnel ID printed in the output.
```

### 4.4 Map the tunnel to the local service

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: ~/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: <your-subdomain>.trycloudflare.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

> Replace `<TUNNEL_ID>` and the hostname with your actual values. The catch-all
> `http_status:404` rule ensures nothing beyond the mapped service is exposed.

### 4.5 Route / DNS

In the Cloudflare dashboard (Networking → Tunnels → your tunnel → Routes), add a
published application route mapping your public hostname to
`http://127.0.0.1:8000`. Or use a quick tunnel for testing:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

### 4.6 Startup / shutdown

```bash
# Start (foreground)
cloudflared tunnel run karna-whatsapp

# Or install as a system service (Linux)
sudo cloudflared service install <TOKEN>
sudo systemctl start cloudflared
sudo systemctl stop cloudflared
```

### 4.7 What is NOT exposed

- API credentials / secrets
- Meta management endpoints
- Any local service other than `127.0.0.1:8000` (only the webhook route)

## 5. Local LLM configuration (llama.cpp)

### 5.1 Expected initial configuration

```
LLM_BASE_URL=http://127.0.0.1:8001/v1
```

### 5.2 Verification (mandatory before use)

Run:

```bash
source .venv/bin/activate
python scripts/verify_llama.py
```

The script:
- Reads `LLM_BASE_URL` from `.env` (never hardcoded).
- Calls `GET {LLM_BASE_URL}/models`.
- Inspects and reports the available model identifier.
- Exits non-zero if the endpoint is unreachable or returns no models.
- Does NOT fall back to any cloud LLM.

### 5.3 Rules

- Do not hardcode a model name; discover it at runtime via `/models`.
- If the endpoint differs from `http://127.0.0.1:8001/v1`, update `LLM_BASE_URL`
  in `.env` to the verified actual endpoint.
- The application must not use any cloud LLM as a fallback.

## 6. Environment configuration — populate `.env`

### 6.1 Create `.env` from `.env.example`

```bash
cp .env.example .env
# Edit .env and fill in the real values (see section 2 and section 3.3).
```

### 6.2 Required values you must supply

| Variable | Source |
|----------|--------|
| `WHATSAPP_ACCESS_TOKEN` | Meta dashboard (section 2) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta dashboard |
| `WHATSAPP_APP_SECRET` | Meta dashboard |
| `WHATSAPP_VERIFY_TOKEN` | Value you chose in Meta webhook config |
| `WHATSAPP_ALLOWED_SENDER_IDS` | Your test phone number, E.164, comma-separated |
| `WHATSAPP_GRAPH_API_VERSION` | e.g. `v22.0` |
| `LLM_BASE_URL` | Verified llama.cpp endpoint (section 5) |
| `LLM_MODEL` | Left empty — discovered at runtime via `/models` |

### 6.3 Secrets protection

- `.env` is excluded from Git by `.gitignore` (already created).
- Never print actual API tokens or secrets in terminal logs or reports.
- `config/settings.py` masks all secret fields in `__repr__`/`__str__`.

## 7. Service preparation (systemd user — not yet started)

### 7.1 Template created

`service/karna-chatbot.service` — a Linux user-level systemd unit.

It is **not** installed, enabled, or started. The application code does not
exist yet, so the service must remain inactive until a later stage.

### 7.2 When the app exists (later stage)

```bash
cp service/karna-chatbot.service ~/.config/systemd/user/karna-chatbot.service
systemctl --user daemon-reload
systemctl --user enable --now karna-chatbot.service
```

---

## 8. Completed vs. manual setup still required

### ✅ Completed (in this repository)

- Virtual environment + dependencies installed.
- `.env.example` template with all required variables.
- `.gitignore` excluding `.env`, `.venv`, `data/`.
- `config/settings.py` — configuration loader with masked secrets.
- `scripts/verify_llama.py` — LLM endpoint verification script.
- `service/karna-chatbot.service` — systemd user service template.
- This documentation.

### ⏳ Manual setup still required from you

1. **Meta dashboard**: create app, WhatsApp Business Account, add phone number,
   generate access token, note App Secret, choose verify token, subscribe to
   `messages` webhook. → populate `.env` WhatsApp fields.
2. **llama.cpp server**: start it on `127.0.0.1:8001` (or your actual endpoint),
   then run `python scripts/verify_llama.py` to confirm `LLM_BASE_URL` and
   discover the model identifier.
3. **Cloudflare Tunnel**: install cloudflared, authenticate, create named tunnel,
   map to `127.0.0.1:8000`, obtain public HTTPS URL.
4. **Meta webhook**: enter the public tunnel URL + verify token as the webhook
   callback URL, subscribe to `messages`, and complete the GET challenge
   verification.
5. **`.env`**: copy `.env.example` → `.env` and fill all real values.

---

## 9. Acceptance criteria (Stage 2)

| Criterion | Status |
|-----------|--------|
| Local inference endpoint verified | ⏳ Pending `scripts/verify_llama.py` run |
| Meta integration prerequisites documented | ✅ This document |
| Environment variables defined | ✅ `.env.example` |
| Secrets protected | ✅ `.gitignore`, masked `settings.py` |
| Cloudflare Tunnel prepared | ✅ Documented (not yet created) |
| Webhook callback URL documented | ✅ Section 3.4 |
| No external LLM dependency | ✅ `verify_llama.py` refuses cloud fallback |

Once you complete the manual steps and run the verification script, Stage 2 is
complete and Stage 3 (FastAPI webhook implementation) can begin.
