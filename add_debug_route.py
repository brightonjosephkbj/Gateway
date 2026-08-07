SRC = "app.py"

with open(SRC) as f:
    src = f.read()

old = '''@app.route("/ping")
def ping():
    return jsonify({"service": "b24-gateway", "status": "ready"})'''

new = '''@app.route("/ping")
def ping():
    return jsonify({"service": "b24-gateway", "status": "ready"})


@app.route("/debug/token")
def debug_token():
    """TEMPORARY - confirms Render actually loaded the token, without
    exposing the full secret. Remove after debugging."""
    token = INTERNAL_AUTH_TOKEN
    return jsonify({
        "token_set": bool(token),
        "token_length": len(token),
        "token_prefix": token[:4] if token else None,
        "token_suffix": token[-4:] if token else None,
        "app_keys_configured": len(APP_KEYS),
    })'''

assert old in src, "pattern not found"
src = src.replace(old, new, 1)

with open(SRC, "w") as f:
    f.write(src)

print("Debug route added")
