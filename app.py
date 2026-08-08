"""
b24-gateway
The one service every B24 app calls. Doesn't do real work itself - looks at
the request, decides which backing service should handle it, forwards it,
and returns the response. Backing services (fetch, db, downloads, ota, ai)
are never called directly by an app; they only trust requests carrying this
gateway's internal auth header.

Why this exists: B24music, Messenger, Browser, Scanner each used to talk to
their own backend directly, each with its own copy of auth.py / ota.py /
fetch logic. Splitting that out means fixing something once here instead of
in every app's own copy.

Two layers of auth:
  - APP -> GATEWAY: caller sends X-Gateway-Key, checked against
    GATEWAY_API_KEYS (comma separated, one per app or one shared).
  - GATEWAY -> BACKING SERVICE: gateway attaches X-Internal-Auth so a
    backing service can tell the request actually came through the
    gateway, not directly from the open internet.
"""

import os
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Secret the gateway uses to prove its own identity to backing services.
INTERNAL_AUTH_TOKEN = os.environ.get("B24_INTERNAL_AUTH_TOKEN", "")

# Keys apps use to prove their identity to the gateway. Comma separated,
# e.g. "b24music:xxx,messenger:yyy" or just a single shared key.
_raw_app_keys = os.environ.get("B24_GATEWAY_API_KEYS", "")
APP_KEYS = set(k.strip() for k in _raw_app_keys.split(",") if k.strip())

# Registry of backing services. Add a new one here and it's immediately
# reachable at /api/<name>/... - no new route code needed.
SERVICES = {
    "fetch": {
        "base_url": os.environ.get("B24_FETCH_SERVICE_URL", ""),
        "health_path": "/ping",
    },
    "db": {
        "base_url": os.environ.get("B24_DB_SERVICE_URL", ""),
        "health_path": "/health",
    },
    "downloads": {
        "base_url": os.environ.get("B24_DOWNLOADS_SERVICE_URL", ""),
        "health_path": "/ping",
    },
    "ota": {
        "base_url": os.environ.get("B24_OTA_SERVICE_URL", ""),
        "health_path": "/ping",
    },
    "ai": {
        "base_url": os.environ.get("B24_AI_SERVICE_URL", ""),
        "health_path": "/ping",
    },
    "apicache": {
        "base_url": os.environ.get("B24_APICACHE_SERVICE_URL", ""),
        "health_path": "/",
    },
}


def require_app_auth():
    """Apps calling the gateway must send a valid X-Gateway-Key. Skipped
    entirely if no keys are configured yet (useful while wiring things up),
    so don't forget to set B24_GATEWAY_API_KEYS once real apps point here."""
    if not APP_KEYS:
        return None
    key = request.headers.get("X-Gateway-Key", "")
    if key not in APP_KEYS:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route("/ping")
def ping():
    return jsonify({"service": "b24-gateway", "status": "ready"})


@app.route("/health")
def health():
    """One dashboard for every backing service's status, instead of
    checking each HF Space's logs separately. A slow response here is
    your first sign a Space cold-started."""
    results = {}
    for name, cfg in SERVICES.items():
        if not cfg["base_url"]:
            results[name] = {"status": "not_configured"}
            continue
        start = time.time()
        try:
            resp = requests.get(
                f"{cfg['base_url']}{cfg['health_path']}",
                headers={"X-Internal-Auth": INTERNAL_AUTH_TOKEN},
                timeout=15,  # generous - a cold HF Space can take a while to wake
            )
            elapsed_ms = round((time.time() - start) * 1000)
            results[name] = {
                "status": "up" if resp.ok else "error",
                "http_status": resp.status_code,
                "latency_ms": elapsed_ms,
            }
        except requests.RequestException as e:
            results[name] = {"status": "down", "error": str(e)}

    all_up = all(r.get("status") == "up" for r in results.values() if r.get("status") != "not_configured")
    return jsonify({"gateway": "ready", "all_up": all_up, "services": results})


@app.route("/api/<service_name>/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(service_name, subpath):
    """Generic passthrough: /api/fetch/info -> fetch service's /info,
    /api/ota/b24music/latest -> ota service's /b24music/latest, etc.
    Adding a new backing service never needs a new route - just an
    entry in SERVICES."""
    auth_fail = require_app_auth()
    if auth_fail:
        return auth_fail

    cfg = SERVICES.get(service_name)
    if not cfg or not cfg["base_url"]:
        return jsonify({"error": f"'{service_name}' service not configured"}), 503

    url = f"{cfg['base_url']}/{subpath}"
    headers = {"X-Internal-Auth": INTERNAL_AUTH_TOKEN}
    incoming_auth = request.headers.get("Authorization")
    if incoming_auth:
        headers["Authorization"] = incoming_auth

    # 950s matches Downloads' own worst-case (yt-dlp + video enhance can take
    # up to ~900s) - the old 30s cap silently killed any real fetch/trending
    # scrape before the backend even finished.
    PROXY_TIMEOUT = 950
    try:
        if request.method == "GET":
            resp = requests.get(url, params=request.args, headers=headers, timeout=PROXY_TIMEOUT)
        elif request.method == "DELETE":
            resp = requests.delete(url, params=request.args, headers=headers, timeout=PROXY_TIMEOUT)
        else:
            resp = requests.request(
                request.method, url,
                json=request.get_json(silent=True),
                params=request.args, headers=headers, timeout=PROXY_TIMEOUT,
            )
    except requests.RequestException as e:
        return jsonify({"error": f"'{service_name}' service unreachable: {str(e)}"}), 502

    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    passthrough_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded_headers]
    return (resp.content, resp.status_code, passthrough_headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
