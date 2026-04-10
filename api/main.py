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

# BUILD CACHES
buildable_cache = {}
blueprint_cache = {}
typeid_cache = {}
buy_price_cache = {}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_blueprint_and_materials(conn, product_name):
    if product_name in blueprint_cache:
        return blueprint_cache[product_name]

    query = """
    SELECT
        p.typeID AS blueprintTypeID,
        bp.typeName AS blueprintName,
        p.productTypeID,
        prod.typeName AS productName,
        p.quantity AS outputQuantity,
        m.materialTypeID,
        mat.typeName AS materialName,
        m.quantity AS materialQuantity
    FROM industryActivityProducts p
    JOIN industryActivityMaterials m
        ON p.typeID = m.typeID
        AND p.activityID = m.activityID
    JOIN invTypes bp
        ON p.typeID = bp.typeID
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


def resolve_type_id(item_name):
    if item_name in typeid_cache:
        return typeid_cache[item_name]

    try:
        r = requests.get(
            "https://www.fuzzwork.co.uk/api/typeid.php",
            params={"typename": item_name},
            timeout=5
        )
        r.raise_for_status()
        resolved = r.json()

        if "typeID" in resolved:
            type_id = str(resolved["typeID"])
            typeid_cache[item_name] = type_id
            return type_id
    except Exception:
        pass

    typeid_cache[item_name] = None
    return None


def get_buy_price(type_id):
    if not type_id:
        return None

    if type_id in buy_price_cache:
        return buy_price_cache[type_id]

    best_price = None

    for r_name in CHECK_REGIONS:
        r_id = REGIONS.get(r_name)
        if not r_id:
            continue

        r = requests.get(
            "https://market.fuzzwork.co.uk/aggregates/",
            params={"region": r_id, "types": type_id},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

        if str(type_id) not in data:
            continue

        sell_price = float(data[str(type_id)]["sell"]["percentile"])
        if sell_price <= 0:
            continue

        if best_price is None or sell_price < best_price:
            best_price = sell_price

    buy_price_cache[type_id] = best_price
    return best_price


def evaluate_build_vs_buy(total_cost, market_price):
    margin_threshold = None
    difference_percent = None
    build_vs_buy = None
    savings = None

    if market_price is not None and total_cost is not None and market_price > 0:
        margin_threshold = market_price * 0.95
        difference_percent = ((market_price - total_cost) / market_price) * 100

        if total_cost < margin_threshold:
            build_vs_buy = "build"
            savings = market_price - total_cost
        elif total_cost > market_price:
            build_vs_buy = "buy"
            savings = total_cost - market_price
        else:
            build_vs_buy = "marginal"
            savings = abs(market_price - total_cost)

    return {
        "market_price": market_price,
        "margin_threshold": margin_threshold,
        "difference_percent": difference_percent,
        "build_vs_buy": build_vs_buy,
        "savings": savings
    }


def extract_build_buy_plan(tree):
    build = []
    buy = []
    marginal = []

    for material in tree.get("materials", []):
        decision = material.get("build_vs_buy")
        entry = {
            "name": material.get("name"),
            "quantity": material.get("quantity"),
            "unit_market_price": material.get("unit_market_price"),
            "market_total_price": material.get("market_total_price"),
            "component_total_cost": material.get("components", {}).get("total_cost") if material.get("buildable") else None,
            "difference_percent": material.get("difference_percent"),
            "savings": material.get("savings")
        }

        if decision == "build":
            build.append(entry)
        elif decision == "buy":
            buy.append(entry)
        elif decision == "marginal":
            marginal.append(entry)

    return {
        "build": build,
        "buy": buy,
        "marginal": marginal
    }


def build_tree(conn, product_name, quantity=1, depth=0, max_depth=10):
    if depth > max_depth:
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "buildable": False,
            "error": "Max depth reached"
        }

    rows = get_blueprint_and_materials(conn, product_name)

    if not rows:
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "buildable": False,
            "materials": [],
            "total_cost": 0
        }

    first = rows[0]
    output_quantity = first["outputQuantity"]
    runs_needed = math.ceil(quantity / output_quantity)

    node = {
        "name": first["productName"],
        "blueprint": first["blueprintName"],
        "output_quantity": output_quantity,
        "quantity_requested": quantity,
        "runs_needed": runs_needed,
        "buildable": True,
        "materials": []
    }

    total_cost = 0

    for row in rows:
        material_name = row["materialName"]
        material_qty = row["materialQuantity"] * runs_needed
        material_buildable = is_buildable(conn, material_name)

        material_node = {
            "name": material_name,
            "quantity": material_qty,
            "buildable": material_buildable,
            "buy_price": None,
            "line_total": None
        }

        if material_buildable:
            component = build_tree(
                conn,
                material_name,
                quantity=material_qty,
                depth=depth + 1,
                max_depth=max_depth
            )
            material_node["components"] = component

            component_total_cost = component.get("total_cost")
            if component_total_cost is not None:
                total_cost += component_total_cost

            component_type_id = resolve_type_id(material_name)
            unit_market_price = get_buy_price(component_type_id)
            market_total_price = unit_market_price * material_qty if unit_market_price is not None else None

            decision = evaluate_build_vs_buy(component_total_cost, market_total_price)
            decision["unit_market_price"] = unit_market_price
            decision["market_total_price"] = market_total_price
            material_node.update(decision)
        else:
            type_id = resolve_type_id(material_name)
            buy_price = get_buy_price(type_id)
            line_total = buy_price * material_qty if buy_price is not None else None

            material_node["buy_price"] = buy_price
            material_node["line_total"] = line_total

            if line_total is not None:
                total_cost += line_total

        node["materials"].append(material_node)

    node["total_cost"] = total_cost
    return node


def collect_raw_materials(tree, totals=None):
    if totals is None:
        totals = defaultdict(int)

    if not tree.get("buildable", False):
        qty = tree.get("quantity_requested", 0)
        if qty:
            totals[tree["name"]] += qty
        return totals

    for material in tree.get("materials", []):
        if material.get("buildable"):
            collect_raw_materials(material["components"], totals)
        else:
            totals[material["name"]] += material["quantity"]

    return totals


def build_response(conn, product_name, quantity=1, mode="tree"):
    tree = build_tree(conn, product_name, quantity=quantity)

    type_id = resolve_type_id(product_name)
    market_price = get_buy_price(type_id)
    market_total_price = market_price * quantity if market_price is not None else None

    decision = evaluate_build_vs_buy(tree.get("total_cost"), market_total_price)
    decision["unit_market_price"] = market_price
    decision["market_total_price"] = market_total_price

    plan = extract_build_buy_plan(tree)

    if mode == "tree":
        return {
            **tree,
            **decision,
            "plan": plan
        }

    raw_totals = collect_raw_materials(tree)
    raw_list = [
        {"name": name, "quantity": qty}
        for name, qty in sorted(raw_totals.items())
    ]

    if mode == "raw":
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "raw_materials": raw_list,
            **decision,
            "plan": plan
        }

    if mode == "both":
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "tree": tree,
            "raw_materials": raw_list,
            **decision,
            "plan": plan
        }

    return {
        "error": f"Invalid mode '{mode}'. Use tree, raw, or both."
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        mode = query.get("mode", [None])[0]
        type_id = query.get("typeId", [None])[0]
        name = query.get("name", [None])[0]
        region_name = query.get("region_name", [None])[0]
        check_all = query.get("cheapest", [None])[0]
        scan = query.get("scan", [None])[0]

        if mode:
            mode = mode.strip().lower()

        try:
            top_n = int(query.get("top", ["10"])[0])
        except ValueError:
            top_n = 10

        try:
            quantity = int(query.get("quantity", ["1"])[0])
            if quantity < 1:
                raise ValueError
        except ValueError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "quantity must be a positive integer"
            }).encode())
            return

        try:
            if mode in ["tree", "raw", "both"]:
                if not name:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": "Provide name for build mode"
                    }).encode())
                    return

                conn = get_connection()
                response = build_response(conn, name, quantity=quantity, mode=mode)
                conn.close()

                status = 200 if "error" not in response else 400
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                return

            # MARKET MODE placeholder in canvas version
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "market mode placeholder",
                "top": top_n,
                "typeId": type_id,
                "name": name,
                "region_name": region_name,
                "cheapest": check_all,
                "scan": scan
            }).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": str(e)
            }).encode())
