from http.server import BaseHTTPRequestHandler
import json
import math
import sqlite3
from urllib.parse import urlparse, parse_qs
import requests

DB_PATH = "api/eve-indy.sqlite"

# --- SIMPLE SKILL DEFAULTS ---
DEFAULT_SKILLS = {
    "industry": 0,              # time reduction
    "advanced_industry": 0,     # time reduction
    "production_efficiency": 0  # material reduction
}

# --- DB ---
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- NAME CLEAN ---
def normalize_name(name):
    if not name:
        return name
    name = name.strip()
    if name.lower().endswith("s"):
        name = name[:-1]
    return name

# --- BLUEPRINT ---
def get_materials(conn, product_name):
    query = """
    SELECT
        p.quantity AS outputQuantity,
        mat.typeName AS materialName,
        m.quantity AS materialQuantity
    FROM industryActivityProducts p
    JOIN industryActivityMaterials m
        ON p.typeID = m.typeID
        AND p.activityID = m.activityID
    JOIN invTypes prod
        ON p.productTypeID = prod.typeID
    JOIN invTypes mat
        ON m.materialTypeID = mat.typeID
    WHERE p.activityID = 1
      AND prod.typeName = ?
    """
    return conn.execute(query, (product_name,)).fetchall()

# --- BUILDABLE CHECK ---
def is_buildable(conn, name):
    q = """
    SELECT 1 FROM industryActivityProducts p
    JOIN invTypes prod ON p.productTypeID = prod.typeID
    WHERE p.activityID = 1 AND prod.typeName = ?
    LIMIT 1
    """
    return conn.execute(q, (name,)).fetchone() is not None

# --- TYPE ID ---
def resolve_type_id(name):
    try:
        r = requests.get("https://www.fuzzwork.co.uk/api/typeid.php",
                         params={"typename": name}, timeout=5)
        return str(r.json().get("typeID"))
    except:
        return None

# --- PRICE ---
def get_price(type_id):
    if not type_id:
        return 0
    try:
        r = requests.get("https://market.fuzzwork.co.uk/aggregates/",
                         params={"region": "10000002", "types": type_id},
                         timeout=5)
        data = r.json()
        return float(data[type_id]["sell"]["percentile"])
    except:
        return 0

# --- MATERIAL MODIFIER ---
def apply_material_modifiers(base, me, skills):
    me_reduction = me / 100
    skill_reduction = skills["production_efficiency"] * 0.01
    total_reduction = me_reduction + skill_reduction
    return math.ceil(base * (1 - total_reduction))

# --- TIME MODIFIER ---
def apply_time_modifiers(base_time, te, skills):
    te_reduction = te / 100
    skill_reduction = (skills["industry"] * 0.04) + (skills["advanced_industry"] * 0.03)
    total = te_reduction + skill_reduction
    return base_time * (1 - total)

# --- BUILD TREE ---
def build_tree(conn, name, qty, me, te, skills):
    rows = get_materials(conn, name)

    if not rows:
        return {"name": name, "total_cost": 0, "materials": []}

    runs = math.ceil(qty / rows[0]["outputQuantity"])

    node = {
        "name": name,
        "materials": [],
        "total_cost": 0,
        "time": 1  # placeholder base time
    }

    for row in rows:
        mat = row["materialName"]
        base = row["materialQuantity"] * runs

        adjusted = apply_material_modifiers(base, me, skills)

        if is_buildable(conn, mat):
            comp = build_tree(conn, mat, adjusted, me, te, skills)
            cost = comp["total_cost"]
        else:
            price = get_price(resolve_type_id(mat))
            cost = price * adjusted
            comp = None

        node["materials"].append({
            "name": mat,
            "quantity": adjusted,
            "components": comp
        })

        node["total_cost"] += cost

    node["time"] = apply_time_modifiers(node["time"], te, skills)

    return node

# --- RESPONSE ---
def build_response(conn, name, qty, me, te, skills):
    tree = build_tree(conn, name, qty, me, te, skills)

    return {
        "name": name,
        "quantity": qty,
        "blueprint_me": me,
        "blueprint_te": te,
        "skills": skills,
        "tree": tree
    }

# --- HANDLER ---
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)

        name = normalize_name(q.get("name", [None])[0])
        qty = int(q.get("quantity", ["1"])[0])
        me = int(q.get("blueprint_me", ["0"])[0])
        te = int(q.get("blueprint_te", ["0"])[0])

        skills = {
            "industry": int(q.get("industry", ["0"])[0]),
            "advanced_industry": int(q.get("advanced_industry", ["0"])[0]),
            "production_efficiency": int(q.get("production_efficiency", ["0"])[0])
        }

        if not name:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"name required"}')
            return

        conn = get_connection()
        result = build_response(conn, name, qty, me, te, skills)
        conn.close()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
