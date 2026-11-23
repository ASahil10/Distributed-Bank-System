"""Read-only dashboard gateway for locally running branch servers."""
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import json
import socket
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent
PORTS = {"A": 5001, "B": 5002, "C": 5003}

@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")

@app.get("/<path:filename>")
def assets(filename):
    if filename not in {"style.css", "script.js"}:
        return jsonify(error="Not found"), 404
    return send_from_directory(ROOT, filename)

@app.get("/api/branches/<branch_id>/<endpoint>")
def branch_api(branch_id, endpoint):
    branch_id = branch_id.upper()
    if branch_id not in PORTS or endpoint not in {"status", "transactions"}:
        return jsonify(error="Unknown branch or endpoint"), 404
    url = f"http://127.0.0.1:{PORTS[branch_id]}/{endpoint}"
    try:
        with urlopen(url, timeout=2) as response:
            return jsonify(json.load(response))
    except HTTPError as exc:
        return jsonify(error=f"Branch returned HTTP {exc.code}"), 502
    except (URLError, TimeoutError, socket.timeout, ValueError, OSError):
        return jsonify(error="Branch unavailable", branch_id=branch_id), 503

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
