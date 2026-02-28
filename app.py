from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import os
import psycopg2
import psycopg2.pool

app = Flask(__name__)
CORS(app)

UNICONTA_ODATA = "https://odata.uniconta.com/odata"
UNICONTA_API   = "https://api.uniconta.com/api/Entities"

# ── DATABASE ──
db_pool = None

def get_db_pool():
    global db_pool
    if db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            return None
        db_pool = psycopg2.pool.SimpleConnectionPool(1, 5, database_url, sslmode="require")
    return db_pool

def get_db():
    pool = get_db_pool()
    if pool is None:
        return None
    return pool.getconn()

def put_db(conn):
    pool = get_db_pool()
    if pool and conn:
        pool.putconn(conn)

def init_db():
    conn = get_db()
    if conn is None:
        print("DATABASE_URL ikke sat — database-funktioner deaktiveret")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                order_number TEXT NOT NULL,
                item_key TEXT NOT NULL DEFAULT '',
                note_text TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(order_number, item_key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS picked (
                id SERIAL PRIMARY KEY,
                prod_number TEXT NOT NULL,
                item_key TEXT NOT NULL,
                qty INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(prod_number, item_key)
            )
        """)
        conn.commit()
        cur.close()
        print("Database-tabeller oprettet/verificeret")
    except Exception as e:
        print(f"Database init fejl: {e}")
        conn.rollback()
    finally:
        put_db(conn)

# Initialiser database ved opstart
with app.app_context():
    init_db()

# ── UNICONTA HELPERS ──

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

# ── ROUTES ──

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
    order_headers, _ = fetch_from_uniconta(company_id, auth, "DebtorOrderClient")
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
    return jsonify({"orders": orders or [], "stock": stock, "orderHeaders": order_headers or []})

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

    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        return jsonify({"error": "RESEND_API_KEY ikke konfigureret på serveren"}), 500

    subject = body.get("subject", "Produktionsordre færdigmeldt")
    html_body = body.get("html", "")
    from_email = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    to_email = "info@hennodahl.com"

    try:
        r = requests.post("https://api.resend.com/emails", json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }, headers={
            "Authorization": f"Bearer {resend_key}",
            "Content-Type": "application/json",
        }, timeout=15)
        if r.status_code in (200, 201):
            return jsonify({"ok": True})
        else:
            return jsonify({"error": f"Resend fejl: {r.text}"}), r.status_code
    except Exception as e:
        return jsonify({"error": f"Kunne ikke sende mail: {str(e)}"}), 500

# ── DATABASE ENDPOINTS: NOTER ──

@app.route("/api/db/notes", methods=["GET"])
def get_notes():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        cur.execute("SELECT order_number, item_key, note_text, updated_by, updated_at FROM notes")
        rows = cur.fetchall()
        cur.close()
        notes = []
        for r in rows:
            notes.append({
                "order_number": r[0],
                "item_key": r[1],
                "text": r[2],
                "author": r[3],
                "updated": r[4].isoformat() if r[4] else None
            })
        return jsonify(notes)
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

@app.route("/api/db/notes", methods=["PUT"])
def put_note():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    body = request.get_json()
    if not body or "order_number" not in body:
        return jsonify({"error": "Mangler data"}), 400
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notes (order_number, item_key, note_text, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (order_number, item_key)
            DO UPDATE SET note_text = EXCLUDED.note_text,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = NOW()
        """, (body["order_number"], body.get("item_key", ""), body.get("text", ""), body.get("author", "")))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

@app.route("/api/db/notes", methods=["DELETE"])
def delete_note():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    body = request.get_json()
    if not body or "order_number" not in body:
        return jsonify({"error": "Mangler data"}), 400
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE order_number = %s AND item_key = %s",
                     (body["order_number"], body.get("item_key", "")))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

# ── DATABASE ENDPOINTS: PLUKKET ──

@app.route("/api/db/picked", methods=["GET"])
def get_picked():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        cur.execute("SELECT prod_number, item_key, qty, updated_by, updated_at FROM picked")
        rows = cur.fetchall()
        cur.close()
        picked = []
        for r in rows:
            picked.append({
                "prod_number": r[0],
                "item_key": r[1],
                "qty": r[2],
                "author": r[3],
                "updated": r[4].isoformat() if r[4] else None
            })
        return jsonify(picked)
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

@app.route("/api/db/picked", methods=["PUT"])
def put_picked():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    body = request.get_json()
    if not body or "prod_number" not in body or "item_key" not in body:
        return jsonify({"error": "Mangler data"}), 400
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO picked (prod_number, item_key, qty, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (prod_number, item_key)
            DO UPDATE SET qty = EXCLUDED.qty,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = NOW()
        """, (body["prod_number"], body["item_key"], body.get("qty", 0), body.get("author", "")))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

@app.route("/api/db/cleanup", methods=["POST"])
def cleanup_picked():
    auth = request.headers.get("Authorization")
    if not auth:
        return jsonify({"error": "Mangler Authorization"}), 400
    body = request.get_json()
    if not body or "active_prod_numbers" not in body:
        return jsonify({"error": "Mangler active_prod_numbers"}), 400
    active = body["active_prod_numbers"]
    if not active:
        return jsonify({"ok": True, "deleted": 0})
    conn = get_db()
    if conn is None:
        return jsonify({"error": "Database ikke konfigureret"}), 500
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(active))
        cur.execute(f"DELETE FROM picked WHERE prod_number NOT IN ({placeholders})", active)
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return jsonify({"ok": True, "deleted": deleted})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        put_db(conn)

# ── DEBUG ──

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
