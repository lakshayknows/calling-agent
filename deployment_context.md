# Deployment Context

Operational reference for deploying and running the Agentic Calling Platform backend.
Secrets are referenced by **name only** — real values live in `.env` (git-ignored) and
the host's environment. Do not commit values.

Last updated: 2026-07-10.

---

## 1. Current hosting — Windows VPS (primary)

- **Domain:** `https://call.karbonz.com`  →  VPS IP `66.94.119.5`
- **OS:** Windows Server, **IIS 10** (shares the box with other sites)
- **App runtime:** Python venv at `C:\inetpub\callkarbonzapi\` (currently Python 3.14; project targets 3.12), `uvicorn app.main:app` bound to **`127.0.0.1:8000`** (localhost only — IIS fronts it).
- **Reverse proxy:** IIS + **ARR (Application Request Routing)** + **URL Rewrite**, with the **WebSocket Protocol** feature enabled. A `web.config` in the site's physical folder rewrites all paths to `http://127.0.0.1:8000/{R:1}` and enables `<webSocket>`. ARR **Server Proxy Settings → Enable proxy** must be ON.
- **TLS:** Let's Encrypt cert via **win-acme** (`wacs.exe`), bound to the `call.karbonz.com:443` IIS binding, auto-renewing. (Required: Plivo audio streaming only connects over `wss://` with a valid cert.)

### web.config (site physical path)
```xml
<configuration>
  <system.webServer>
    <webSocket enabled="true" />
    <rewrite><rules>
      <rule name="FastAPI" stopProcessing="true">
        <match url="(.*)" />
        <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
      </rule>
    </rules></rewrite>
  </system.webServer>
</configuration>
```

### Run / restart on the VPS
```powershell
cd C:\inetpub\callkarbonzapi
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt        # after dependency changes
alembic upgrade head                    # after model/migration changes (also auto-runs on startup)
uvicorn app.main:app --host 127.0.0.1 --port 8000        # dev
# Production: run WITHOUT --reload as an NSSM service so it survives logoff/reboot:
#   nssm install CallingAgent "<venv>\Scripts\python.exe" "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
#   nssm set CallingAgent AppDirectory "C:\inetpub\callkarbonzapi"
```
`.env` changes require a **full restart** (settings are cached at startup; `--reload` only watches `.py`).

---

## 2. Previous hosting — Render (reference)

- URL: `https://calling-agent-dq4a.onrender.com` (service `calling-agent-dq4a`).
- Native Python 3.12 build, Root Directory = `backend`, `Procfile` provides the uvicorn start cmd.
- **Free tier (0.1 vCPU) proved too weak for real-time voice** — the pipeline worked but had heavy latency/audio drops. That's why we moved to the VPS (dedicated CPU). Render remains a valid host if upgraded to Standard (~1 vCPU).
- `render.yaml` blueprint + `preDeployCommand: alembic upgrade head` exist but only apply to Blueprint-created services (the live one was created manually, and migrations self-apply on startup anyway).

---

## 3. Datastores

- **Postgres — Supabase.** MUST use the **Session Pooler** connection string, not the direct host.
  - ✅ `postgresql://postgres.<project-ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres`
  - ❌ `db.<project-ref>.supabase.co` — direct host has no reachable A record → `getaddrinfo failed` from Render and the VPS.
  - `config.py` auto-rewrites `postgresql://` → `postgresql+asyncpg://` and adds SSL (`db_ssl_verify=false`, i.e. encrypt-without-verify) for Supabase hosts.
- **Redis — Upstash.** `config.py` forces `rediss://` (TLS) for any `upstash.io` host, and sanitizes a shell-command-style value (`redis-cli --tls -u redis://…`).

---

## 4. Providers

- **Telephony — Plivo.** Owned caller-ID number: **`918031149481`** (voice-enabled). Account is funded/live (not trial-restricted). Outbound call → `answer_url` returns Plivo XML; for agentic calls it's a `<Stream bidirectional keepCallAlive contentType="audio/x-mulaw;rate=8000">wss://…/calls/stream?agent_id=…</Stream>`.
- **Speech — Sarvam** (via Pipecat): STT `saarika:v2.5`, TTS `bulbul:v2`. Valid `bulbul:v2` voices: `anushka, abhilash, manisha, vidya, arya, karun, hitesh` (unknown voices fall back to `anushka`). Languages via `Language.EN_IN` / `HI_IN`.
- **LLM — OpenRouter** through Pipecat's `OpenAILLMService(base_url=…)`. Default model `openai/gpt-4o-mini`.
- **Storage — Cloudflare R2** (recordings) — NOT yet wired; add R2 keys when enabling recording.

---

## 5. Environment variables (set in `.env` / host env)

| Name | Notes |
|------|-------|
| `DATABASE_URL` | Supabase **Session Pooler** URL |
| `REDIS_URL` | Upstash `rediss://…` |
| `JWT_SECRET` | long random string |
| `SARVAM_API_KEY`, `OPENROUTER_API_KEY`, `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | provider keys |
| `PLIVO_CALLER_ID` | `918031149481` |
| `PUBLIC_BASE_URL` | **`https://call.karbonz.com`** — https, **no** trailing slash. Drives webhook + `wss` URLs. |
| `ENVIRONMENT` | `production` on the server (JSON logs, prod behavior) |
| `SMOKE_TEST_TOKEN` | optional; guards `/calls/test` and `/calls/numbers` |
| R2_* | when recording is enabled |

---

## 6. Verification

```bash
curl https://call.karbonz.com/api/v1/health          # {"status":"ok"}
curl https://call.karbonz.com/api/v1/health/ready     # db/redis ok, voice ready|loading
curl "https://call.karbonz.com/api/v1/calls/stream-answer?agent_id=<id>"
#  -> <Stream ...>wss://call.karbonz.com/api/v1/calls/stream?agent_id=<id></Stream>
```
`health/ready` reports `voice: ready` once the Pipecat stack has pre-warmed at startup — only place calls once it's `ready`.

Place an agentic call (via Plivo REST, using the caller ID + the stream-answer URL as `answer_url`):
`POST https://api.plivo.com/v1/Account/<auth_id>/Call/` with
`from=918031149481, to=<E164>, answer_url=<base>/api/v1/calls/stream-answer?agent_id=<id>, answer_method=GET`.

**Demo agent (Mobikonnect / Oreo × BTS verification):**
`8c3e6c03-566c-4e18-8cf1-9b2b0033fe48` (voice `manisha`, `interruptible=false`).

---

## 7. Gotchas & fixes learned (chronological)

1. **Redis URL** was a shell command → sanitized to `rediss://` in config.
2. **Supabase SSL** cert fails full verification behind the pooler → `db_ssl_verify=false` (encrypt, no verify).
3. **Startup crash**: mixed `structlog.stdlib.*` processors with `PrintLoggerFactory` → use plain processors.
4. **Migrations** don't run unless triggered → app now runs `alembic upgrade head` on startup (`run_migrations_on_startup`).
5. **Preview 500**: OpenRouter `usage` has floats/nested dicts → schema field is `dict[str, Any]`.
6. **Voice first-call latency (~38s)**: lazy Pipecat import mid-call → pre-warm the import + Silero VAD at startup (background thread); gated on `voice: ready`.
7. **Silent agent / greeting wiped**: callee pickup audio fired a VAD interruption clearing the greeting → `InputGate` half-duplex processor.
8. **Speakerphone echo / noise interruptions**: bot transcribed its own echo → `InputGate` drops inbound audio **whenever the bot speaks** (`interruptible=false` on the agent too). VAD tightened (confidence 0.85 / start 0.35 / stop 0.8 / min_volume 0.7).
9. **Real-time latency on Render free**: 0.1 vCPU can't run the pipeline in real time → moved to VPS. Also set STT/TTS to 8 kHz to skip per-frame resampling.
10. **VPS/IIS**: app must run + IIS ARR reverse-proxy with WebSocket + valid win-acme cert. `PUBLIC_BASE_URL` must be `https://` with no trailing slash (stream-answer now forces `wss://` + rstrips defensively).
11. **Known open bug**: `PATCH /agents/{id}` returns 500 (update path) — GET/POST/preview fine. Workaround: create a fresh agent. Needs the traceback to fix.

---

## 8. Feature status

1. Foundation ✅  2. Auth & tenancy ✅  3. AI agents + OpenRouter ✅  4. Real-time voice (Pipecat: Plivo⇄Sarvam⇄LLM, VAD/echo gate) ✅ built — final integration/tuning on VPS in progress.
Next: 5. Contacts & campaigns · 6. Post-call (transcripts/summaries/CRM/analytics, recordings→R2) · 7. Frontend (Next.js on Vercel).
