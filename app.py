from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

UNICONTA_ODATA = "https://odata.uniconta.com/odata"
UNICONTA_API   = "https://api.uniconta.com/api/Entities"

def fetch_order_lines(company_id, auth):
    headers = {"Authorization": auth, "Accept": "application/json"}
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
                return data, None
            elif r.status_code in (401, 403):
                return None, "Forkert brugernavn eller adgangskode"
        except requests.exceptions.RequestException as e:
            continue
    return None, "Kunne ikke forbinde til Uniconta"

@app.route("/api/orders", methods=["GET"])
def get_orders():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    data, err = fetch_order_lines(company_id, auth)
    if err:
        return jsonify({"error": err}), 401 if "adgangskode" in err else 502
    return jsonify(data)

@app.route("/api/debug", methods=["GET"])
def debug():
    """Viser rå feltnavne og værdier fra første ordrelinje"""
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    data, err = fetch_order_lines(company_id, auth)
    if err:
        return jsonify({"error": err}), 401 if "adgangskode" in err else 502
    if not data:
        return jsonify({"info": "Ingen ordrelinjer fundet"})
    # Returner kun første post så vi kan se feltnavne
    return jsonify({
        "antal_linjer": len(data),
        "felter_i_første_linje": data[0]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
