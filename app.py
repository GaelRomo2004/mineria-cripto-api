import os
from flask import Flask, jsonify, request
from core import procesar

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify(status="up")

@app.post("/analyze")
def analyze():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        fuente = payload.get("fuente", "api")
        payload = payload.get("data")
    else:
        fuente = "api"

    if not isinstance(payload, list):
        return jsonify(status="error", mensaje="Se esperaba una lista JSON de registros"), 400

    return jsonify(procesar(payload, fuente))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))