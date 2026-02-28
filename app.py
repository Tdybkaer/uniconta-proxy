from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

UNICONTA_ODATA = "https://odata.uniconta.com/odata"
UNICONTA_API   = "https://api.uniconta.com/api/Entities"

@app.route("/api/orders", methods=["GET"])
def get_orders():
    company_id = request.args.get("company")
    auth       = request.headers.get("Authorization")

    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400

    headers = {
        "Authorization": auth,
        "Accept": "application/json"
    }

    urls = [
        f"{UNICONTA_ODATA}/{company_id}/DebtorOrderLineClient",
        f"{UNICONTA_API}/DebtorOrderLineClient",
    ]

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and "value" in data:
                    data = data["value"]
                return jsonify(data)
            elif r.status_code in (401, 403):
                return jsonify({"error": "Forkert brugernavn eller adgangskode"}), 401
        except requests.exceptions.RequestException:
            continue

    return jsonify({"error": "Kunne ikke forbinde til Uniconta"}), 502

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
