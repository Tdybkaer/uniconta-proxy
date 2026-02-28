from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

UNICONTA_ODATA = "https://odata.uniconta.com/odata"
UNICONTA_API   = "https://api.uniconta.com/api/Entities"

def fetch_from_uniconta(company_id, auth, entity):
    headers = {"Authorization": auth, "Accept": "application/json"}
    urls = [
        f"{UNICONTA_ODATA}/{company_id}/{entity}",
        f"{UNICONTA_API}/{entity}",
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
        except requests.exceptions.RequestException:
            continue
    return None, f"Kunne ikke hente {entity}"

@app.route("/api/combined", methods=["GET"])
def get_combined():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    orders, err1 = fetch_from_uniconta(company_id, auth, "DebtorOrderLineClient")
    inventory, err2 = fetch_from_uniconta(company_id, auth, "InvItemClient")
    if err1:
        return jsonify({"error": err1}), 401 if "adgangskode" in err1 else 502
    # Byg lager-opslag: varenummer -> available
    stock = {}
    if inventory:
        for item in inventory:
            key = item.get("Item") or item.get("ItemNumber") or item.get("_Item")
            val = item.get("Available") or item.get("_Available") or 0
            if key:
                stock[str(key)] = val
    return jsonify({"orders": orders or [], "stock": stock})

@app.route("/api/orders", methods=["GET"])
def get_orders():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    data, err = fetch_from_uniconta(company_id, auth, "DebtorOrderLineClient")
    if err:
        return jsonify({"error": err}), 401 if "adgangskode" in err else 502
    return jsonify(data)

@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    data, err = fetch_from_uniconta(company_id, auth, "InvItemClient")
    if err:
        return jsonify({"error": err}), 401 if "adgangskode" in err else 502
    return jsonify(data)

@app.route("/api/debug", methods=["GET"])
def debug():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    entity = request.args.get("entity", "DebtorOrderLineClient")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    data, err = fetch_from_uniconta(company_id, auth, entity)
    if err:
        return jsonify({"error": err}), 401 if "adgangskode" in err else 502
    if not data:
        return jsonify({"info": "Ingen data fundet"})
    return jsonify({
        "antal": len(data),
        "første_post": data[0]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
