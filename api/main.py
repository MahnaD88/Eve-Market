from http.server import BaseHTTPRequestHandler
import json
import math
import sqlite3
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
import requests

REGIONS = {
    "jita": "10000002",
    "amarr": "10000043",
    "dodixie": "10000032",
    "hek": "10000042"
}

CHECK_REGIONS = ["jita", "amarr", "dodixie", "hek"]
DB_PATH = "api/eve-indy.sqlite"

buildable_cache = {}
blueprint_cache = {}
typeid_cache = {}
buy_price_cache = {}

# -------------------------
# CONNECTION
# -------------------------
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------
# BLUEPRINT
# -------------------------
def get_blueprint_and_materials(conn, product_name):
    if product_name in blueprint_cache:
        return blueprint_cache[product_name]

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

    rows = conn.execute(query, (product_name,)).fetchall()
    blueprint_cache[product_name] = rows
    return rows

# -------------------------
# BUILDABLE
# -------------------------
def is_buildable(conn, item_name):
    if item_name in buildable_cache:
        return buildable_cache[item_name]

    query = """
    SELECT 1
    FROM industryActivityProducts p
    JOIN invTypes prod
        ON p.productTypeID = prod.typeID
    WHERE p.activityID = 1
      AND prod.typeName = ?
    LIMIT 1
    """
    result = conn.execute(query, (item_name,)).fetchone() is not None
    buildable_cache[item_name] = result
    return result

# -------------------------
# MARKET
# -------------------------
def resolve_type_id(item_name):
    if item_name in typeid_cache:
        return typeid_cache[item_name]

    try:
        r = requests.get(
            "https://www.fuzzwork.co.uk/api/typeid.php",
            params={"typename": item_name},
            timeout=5
        )
        type_id = str(r.json()["typeID"])
        typeid_cache[item_name] = type_id
        return type_id
    except:
        return None


def get_buy_price(type_id):
    if not type_id:
        return None

    if type_id in buy_price_cache:
        return buy_price_cache[type_id]

    best = None

    for r in CHECK_REGIONS:
        r_id = REGIONS[r]
        data = requests.get(
            "https://market.fuzzwork.co.uk/aggregates/",
            params={"region": r_id, "types": type_id},
            timeout=10
        ).json()

        if type_id not in data:
            continue

        price = float(data[type_id]["sell"]["percentile"])
        if price > 0:
            best = price if best is None else min(best, price)

    buy_price_cache[type_id] = best
    return best

# -------------------------
# MODIFIERS
# -------------------------
def apply_material_modifiers(base, me, skills):
    reduction = (me / 100) + (skills["production_efficiency"] * 0.01)
    return math.ceil(base * (1 - reduction))


def apply_time_modifiers(base, te, skills):
    reduction = (te / 100) + (skills["industry"] * 0.04) + (skills["advanced_industry"] * 0.03)
    return base * (1 - reduction)

# -------------------------
# BUILD VS BUY
# -------------------------
def evaluate_build_vs_buy(total_cost, market_price):
    if not market_price or not total_cost:
        return {}

    margin = market_price * 0.95

    if total_cost < margin:
        decision = "build"
        savings = market_price - total_cost
    elif total_cost > market_price:
        decision = "buy"
        savings = total_cost - market_price
    else:
        decision = "marginal"
        savings = abs(market_price - total_cost)

    return {
        "build_vs_buy": decision,
        "savings": savings
    }

# -------------------------
# BUILD TREE
# -------------------------
def build_tree(conn, name, qty, me, te, skills):
    rows = get_blueprint_and_materials(conn, name)

    if not rows:
        return {"name": name, "materials": [], "total_cost": 0}

    runs = math.ceil(qty / rows[0]["outputQuantity"])

    node = {
        "name": name,
        "materials": [],
        "total_cost": 0,
        "time": 1
    }

    for row in rows:
        mat = row["materialName"]
        base = row["materialQuantity"] * runs

        adjusted = apply_material_modifiers(base, me, skills)

        if is_buildable(conn, mat):
            comp = build_tree(conn, mat, adjusted, me, te, skills)
            cost = comp["total_cost"]
        else:
            price = get_buy_price(resolve_type_id(mat))
            cost = price * adjusted if price else 0
            comp = None

        decision = evaluate_build_vs_buy(
            comp["total_cost"] if comp else cost,
            price * adjusted if not comp else None
        )

        node["materials"].append({
            "name": mat,
            "quantity": adjusted,
            "components": comp,
            **decision
        })

        node["total_cost"] += cost

    node["time"] = apply_time_modifiers(node["time"], te, skills)

    return node

# -------------------------
# HYBRID
# -------------------------
def collect_hybrid(tree, hybrid=None):
    if hybrid is None:
        hybrid = {
            "build_components": [],
            "buy_components": [],
            "marginal_components": [],
            "raw_materials": defaultdict(int)
        }

    for m in tree["materials"]:
        if m.get("components"):
            if m.get("build_vs_buy") == "build":
                hybrid["build_components"].append(m)
                collect_hybrid(m["components"], hybrid)
            elif m.get("build_vs_buy") == "buy":
                hybrid["buy_components"].append(m)
            else:
                hybrid["marginal_components"].append(m)
        else:
            hybrid["raw_materials"][m["name"]] += m["quantity"]

    return hybrid

# -------------------------
# RESPONSE
# -------------------------
def build_response(conn, name, qty, me, te, skills):
    tree = build_tree(conn, name, qty, me, te, skills)
    hybrid = collect_hybrid(tree)

    return {
        "name": name,
        "quantity": qty,
        "blueprint_me": me,
        "blueprint_te": te,
        "skills": skills,
        "tree": tree,
        "hybrid_plan": {
            "build_components": hybrid["build_components"],
            "buy_components": hybrid["buy_components"],
            "marginal_components": hybrid["marginal_components"],
            "raw_materials": [
                {"name": k, "quantity": v}
                for k, v in hybrid["raw_materials"].items()
            ]
        }
    }

# -------------------------
# HANDLER
# -------------------------
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)

        name = q.get("name", [None])[0]
        qty = int(q.get("quantity", ["1"])[0])
        me = int(q.get("blueprint_me", ["0"])[0])
        te = int(q.get("blueprint_te", ["0"])[0])

        skills = {
            "industry": int(q.get("industry", ["0"])[0]),
            "advanced_industry": int(q.get("advanced_industry", ["0"])[0]),
            "production_efficiency": int(q.get("production_efficiency", ["0"])[0])
        }

        conn = get_connection()
        result = build_response(conn, name, qty, me, te, skills)
        conn.close()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
