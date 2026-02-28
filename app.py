from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

@app.route("/api/combined", methods=["GET"])
def get_combined():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    orders, err1 = fetch_from_uniconta(company_id, auth, "DebtorOrderLineClient")
    inventory, _ = fetch_from_uniconta(company_id, auth, "InvItemClient")
    if err1:
        return jsonify({"error": err1}), 401 if "adgangskode" in err1 else 502
    stock = {}
    if inventory:
        for item in inventory:
            key = item.get("Item") or item.get("ItemNumber") or item.get("_Item")
            if key:
                stock[str(key)] = {
                    "available": item.get("Available") or 0,
                    "onStock":   item.get("QtyOnStock") or item.get("Qty") or 0,
                    "reserved":  item.get("QtyReserved") or 0,
                    "ordered":   item.get("QtyOrdered") or 0,
                }
    return jsonify({"orders": orders or [], "stock": stock})

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

@app.route("/api/production", methods=["GET"])
def get_production():
    company_id = request.args.get("company")
    auth = request.headers.get("Authorization")
    if not company_id or not auth:
        return jsonify({"error": "Mangler company ID eller Authorization"}), 400
    orders, err1 = fetch_from_uniconta(company_id, auth, "ProductionOrderClient")
    lines, err2  = fetch_from_uniconta(company_id, auth, "ProductionOrderLineClient")
    if err1 and err2:
        return jsonify({"error": err1}), 401 if "adgangskode" in err1 else 502
    return jsonify({"orders": orders or [], "lines": lines or []})

@app.route("/api/send-report", methods=["POST"])
def send_report():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    body = request.get_json()
    if not body:
        return jsonify({"error": "Mangler rapport-data"}), 400

    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not smtp_user or not smtp_pass:
        return jsonify({"error": "SMTP ikke konfigureret på serveren"}), 500

    subject = body.get("subject", "Produktionsordre færdigmeldt")
    html_body = body.get("html", "")
    to_email = "info@hennodahl.com"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = "produktion@hennodahl.com"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": f"Kunne ikke sende mail: {str(e)}"}), 500

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
    return jsonify({"antal": len(data), "første_post": data[0]})

@app.route("/api/swagger_endpoints", methods=["GET"])
def swagger_endpoints():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    headers = {"Authorization": auth, "Accept": "application/json"}
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
                paths = list(data.get("paths", {}).keys())
                prod_paths = [p for p in paths if any(x in p.lower() for x in ['prod', 'manufactur', 'work', 'bom', 'assembly'])]
                return jsonify({
                    "url": url,
                    "alle_endpoints_antal": len(paths),
                    "prod_relaterede": prod_paths,
                    "alle_endpoints": paths[:100]
                })
        except Exception:
            continue
    return jsonify({"error": "Kunne ikke hente Swagger dokumentation"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
