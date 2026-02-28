from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
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

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/api/swagger_endpoints", methods=["GET"])
def swagger_endpoints():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400

    headers = {"Authorization": auth, "Accept": "application/json"}

    # Hent Swagger JSON fra Web API
    urls = [
        "https://api.uniconta.com/swagger/v1/swagger.json",
        "https://api.uniconta.com/swagger/v2/swagger.json",
        "https://api.uniconta.com/api-docs",
        "https://api.uniconta.com/openapi.json",
    ]

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                # Udtræk kun endpoint-navne så det ikke bliver for stort
                paths = list(data.get("paths", {}).keys())
                # Filtrer på prod/production/manufacturing
                prod_paths = [p for p in paths if any(
                    x in p.lower() for x in ['prod', 'manufactur', 'work', 'bom', 'assembly']
                )]
                return jsonify({
                    "url": url,
                    "alle_endpoints_antal": len(paths),
                    "prod_relaterede": prod_paths,
                    "alle_endpoints": paths[:100]  # Første 100
                })
        except Exception as e:
            continue

    return jsonify({"error": "Kunne ikke hente Swagger dokumentation", "forsøgte_urls": urls})

@app.route("/api/search_order", methods=["GET"])
def search_order():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400

    headers = {"Authorization": auth, "Accept": "application/json"}

    # Prøv alle mulige entiteter med filter på ordrenummer eller varenummer
    candidates = [
        "InvTransClient", "InvBOMClient", "CreditorOrderClient",
        "CreditorOrderLineClient", "DebtorOrderClient", "DebtorOrderLineClient",
        "InvItemClient", "InvJournalClient",
    ]

    # OData filter URLs at prøve
    search_urls = []
    for entity in candidates:
        search_urls += [
            (entity, f"https://odata.uniconta.com/odata/{company_id}/{entity}?$filter=OrderNumber eq '3027'"),
            (entity, f"https://odata.uniconta.com/odata/{company_id}/{entity}?$filter=OrderNumber eq 3027"),
            (entity, f"https://odata.uniconta.com/odata/{company_id}/{entity}?Name=OrderNumber&Value=3027"),
            (entity, f"https://odata.uniconta.com/odata/{company_id}/{entity}?Name=Item&Value=PLUK_A.E.70020XX"),
        ]

    # Tilføj ukendte entiteter vi ikke har prøvet
    extra_entities = [
        "InvJobJournalClient", "InvJobJournalLineClient",
        "InvProdOrderClient", "InvProdOrderLineClient",
        "InvProductionClient", "InvProductionLineClient",
        "InvManufactureClient", "InvWorkClient",
        "InvWorkLineClient", "InvOrderWorkClient",
    ]
    for entity in extra_entities:
        search_urls.append((entity, f"https://odata.uniconta.com/odata/{company_id}/{entity}"))

    results = {"fundet": {}, "ikke_fundet": []}

    for entity, url in search_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and "value" in data:
                    data = data["value"]
                if isinstance(data, list) and len(data) > 0:
                    text = json.dumps(data)
                    if "3027" in text or "PLUK" in text or "70020" in text:
                        results["fundet"][f"{entity} | {url}"] = data[0]
                    elif entity in extra_entities:
                        results["fundet"][f"{entity} (ny entitet virker!)"] = {
                            "antal": len(data),
                            "første_post": data[0]
                        }
            elif r.status_code not in (404, 400):
                results["ikke_fundet"].append(f"{entity}: HTTP {r.status_code}")
        except Exception as e:
            pass

    return jsonify(results)

@app.route("/api/webapi_debug", methods=["GET"])
def webapi_debug():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    entity = request.args.get("entity", "")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400

    headers = {"Authorization": auth, "Accept": "application/json"}

    # Prøv Web API formater
    urls = [
        f"https://api.uniconta.com/api/Entities/{entity}",
        f"https://api.uniconta.com/api/{entity}",
        f"https://api.uniconta.com/odata/{company_id}/{entity}",
    ]

    results = {}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            results[url] = {
                "status": r.status_code,
                "preview": r.text[:500]
            }
        except Exception as e:
            results[url] = {"error": str(e)}

    return jsonify(results)

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
    stock = {}
    if inventory:
        for item in inventory:
            key = item.get("Item") or item.get("ItemNumber") or item.get("_Item")
            val = item.get("Available") or item.get("_Available") or 0
            if key:
                stock[str(key)] = val
    return jsonify({"orders": orders or [], "stock": stock})

@app.route("/api/production", methods=["GET"])
def get_production():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400

    # Produktionsordrer
    prod_orders, err1 = fetch_from_uniconta(company_id, auth, "ProdOrderClient")
    # Styklister (BOM linjer)
    bom_lines, err2 = fetch_from_uniconta(company_id, auth, "ProdBOMClient")
    # Lagerstatus
    inventory, err3 = fetch_from_uniconta(company_id, auth, "InvItemClient")

    if err1:
        return jsonify({"error": err1}), 502

    stock = {}
    if inventory:
        for item in inventory:
            key = item.get("Item") or item.get("ItemNumber") or item.get("_Item")
            val = item.get("Available") or item.get("_Available") or 0
            if key:
                stock[str(key)] = val

    return jsonify({
        "prod_orders": prod_orders or [],
        "bom_lines": bom_lines or [],
        "stock": stock
    })

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
