---
title: B24 Gateway
emoji: 🚪
colorFrom: blue
colorTo: gray
sdk: docker
pinned: false
---

# b24-gateway

Single entry point for every B24 app (B24music, Messenger, Browser, Scanner).
Apps never call a backing service directly - they call the gateway, and the
gateway forwards to whichever service should handle it.

## Routing

    /api/<service>/<anything> -> forwarded to SERVICES[<service>]["base_url"] + /<anything>

Examples:
    /api/fetch/info                  -> fetch service /info
    /api/ota/b24music/latest         -> ota service /b24music/latest
    /api/db/users/123                -> db service /users/123

Adding a new backing service = one new entry in the `SERVICES` dict in
app.py. No new route code needed.

## Env vars

| Var | Purpose |
|---|---|
| `B24_INTERNAL_AUTH_TOKEN` | Shared secret gateway sends to backing services (`X-Internal-Auth`) |
| `B24_GATEWAY_API_KEYS` | Comma-separated keys apps must send as `X-Gateway-Key`. Leave empty while testing. |
| `B24_FETCH_SERVICE_URL` | Cache + external API service (yt-dlp, Lightning.ai, Spotify, search) |
| `B24_DB_SERVICE_URL` | Database service |
| `B24_DOWNLOADS_SERVICE_URL` | Download job lifecycle service |
| `B24_OTA_SERVICE_URL` | OTA manifest/bundle service, namespaced per app |
| `B24_AI_SERVICE_URL` | JOY AI inference service |

## Endpoints

- `GET /ping` - gateway's own liveness check
- `GET /health` - pings every configured backing service, reports status + latency
- `ANY /api/<service>/<path>` - proxied to the matching backing service
