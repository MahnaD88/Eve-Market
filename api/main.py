from http.server import BaseHTTPRequestHandler
import json
import math
import sqlite3
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


# -------- FIT PARSER --------
def parse_fit(fit_text):
    if not fit_text:
        return []

    items = []
    for line in fit_text.split("
"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        item = line.split(",")[0].strip()
        if item:
            items.append(item)

    return items


# -------- MATERIAL MODIFIER --------
def apply_material_modifiers(qty, me, pe, structure_material_bonus=0, rig_material_bonus=0):
    reduction = (me / 100) + (pe * 0.01) + (structure_material_bonus / 100) + (rig_material_bonus / 100)
    reduction = max(0, min(1, reduction))
    return math.ceil(qty * (1 - reduction))


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

    try:
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

            sell_price = float(data[str(type_id)]["sell"].get("percentile", 0) or 0)
            if sell_price <= 0:
                continue

            if best_price is None or sell_price < best_price:
                best_price = sell_price
    except Exception:
        pass

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


def get_manufacturing_context(
    blueprint_me=0,
    blueprint_te=0,
    production_efficiency=0,
    industry_skill=0,
    advanced_industry_skill=0,
    mass_production_skill=0,
    advanced_mass_production_skill=0,
    supply_chain_management_skill=0,
    structure_material_bonus=0,
    structure_time_bonus=0,
    rig_material_bonus=0,
    rig_time_bonus=0,
):
    blueprint_time_multiplier = max(0, 1 - (blueprint_te * 0.02))
    industry_time_multiplier = max(0, 1 - (industry_skill * 0.04))
    advanced_industry_time_multiplier = max(0, 1 - (advanced_industry_skill * 0.03))
    structure_time_multiplier = max(0, 1 - (structure_time_bonus / 100))
    rig_time_multiplier = max(0, 1 - (rig_time_bonus / 100))
    total_time_multiplier = (
        blueprint_time_multiplier
        * industry_time_multiplier
        * advanced_industry_time_multiplier
        * structure_time_multiplier
        * rig_time_multiplier
    )

    return {
        "blueprint_me": blueprint_me,
        "blueprint_te": blueprint_te,
        "production_efficiency": production_efficiency,
        "industry_skill": industry_skill,
        "advanced_industry_skill": advanced_industry_skill,
        "mass_production_skill": mass_production_skill,
        "advanced_mass_production_skill": advanced_mass_production_skill,
        "supply_chain_management_skill": supply_chain_management_skill,
        "structure_material_bonus": structure_material_bonus,
        "structure_time_bonus": structure_time_bonus,
        "rig_material_bonus": rig_material_bonus,
        "rig_time_bonus": rig_time_bonus,
        "blueprint_time_multiplier": blueprint_time_multiplier,
        "industry_time_multiplier": industry_time_multiplier,
        "advanced_industry_time_multiplier": advanced_industry_time_multiplier,
        "structure_time_multiplier": structure_time_multiplier,
        "rig_time_multiplier": rig_time_multiplier,
        "total_manufacturing_time_multiplier": total_time_multiplier,
        "available_manufacturing_jobs": 1 + mass_production_skill + advanced_mass_production_skill,
        "remote_job_range_jumps": supply_chain_management_skill * 5,
    }


def build_tree(
    conn,
    product_name,
    quantity=1,
    depth=0,
    max_depth=10,
    me=0,
    pe=0,
    blueprint_te=0,
    industry_skill=0,
    advanced_industry_skill=0,
    mass_production_skill=0,
    advanced_mass_production_skill=0,
    supply_chain_management_skill=0,
    structure_material_bonus=0,
    structure_time_bonus=0,
    rig_material_bonus=0,
    rig_time_bonus=0,
):
    if depth > max_depth:
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "buildable": False,
            "error": "Max depth reached",
        }

    rows = get_blueprint_and_materials(conn, product_name)

    if not rows:
        type_id = resolve_type_id(product_name)
        buy_price = get_buy_price(type_id)
        total_cost = buy_price * quantity if buy_price is not None else None
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "buildable": False,
            "materials": [],
            "buy_price": buy_price,
            "line_total": total_cost,
            "total_cost": total_cost,
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
        "materials": [],
    }

    total_cost = 0

    for row in rows:
        material_name = row["materialName"]
        base_qty = row["materialQuantity"] * runs_needed
        material_qty = apply_material_modifiers(base_qty, me, pe, structure_material_bonus, rig_material_bonus)

        material_buildable = is_buildable(conn, material_name)

        material_node = {
            "name": material_name,
            "quantity": material_qty,
            "buildable": material_buildable,
            "buy_price": None,
            "line_total": None,
        }

        if material_buildable:
            component = build_tree(
                conn,
                material_name,
                quantity=material_qty,
                depth=depth + 1,
                max_depth=max_depth,
                me=me,
                pe=pe,
                blueprint_te=blueprint_te,
                industry_skill=industry_skill,
                advanced_industry_skill=advanced_industry_skill,
                mass_production_skill=mass_production_skill,
                advanced_mass_production_skill=advanced_mass_production_skill,
                supply_chain_management_skill=supply_chain_management_skill,
                structure_material_bonus=structure_material_bonus,
                structure_time_bonus=structure_time_bonus,
                rig_material_bonus=rig_material_bonus,
                rig_time_bonus=rig_time_bonus,
            )
            material_node["components"] = component

            component_total_cost = component.get("total_cost")
            component_type_id = resolve_type_id(material_name)
            unit_market_price = get_buy_price(component_type_id)
            market_total_price = unit_market_price * material_qty if unit_market_price is not None else None

            decision = evaluate_build_vs_buy(component_total_cost, market_total_price)
            decision["unit_market_price"] = unit_market_price
            decision["market_total_price"] = market_total_price
            material_node.update(decision)

            selected_total_cost = component_total_cost
            if decision["build_vs_buy"] == "buy" and market_total_price is not None:
                selected_total_cost = market_total_price
            elif (
                decision["build_vs_buy"] == "marginal"
                and market_total_price is not None
                and component_total_cost is not None
            ):
                selected_total_cost = min(component_total_cost, market_total_price)

            material_node["selected_total_cost"] = selected_total_cost

            if selected_total_cost is not None:
                total_cost += selected_total_cost
        else:
            type_id = resolve_type_id(material_name)
            buy_price = get_buy_price(type_id)
            line_total = buy_price * material_qty if buy_price is not None else None

            material_node["buy_price"] = buy_price
            material_node["line_total"] = line_total
            material_node["selected_total_cost"] = line_total

            if line_total is not None:
                total_cost += line_total

        node["materials"].append(material_node)

    node["total_cost"] = total_cost
    return node


def build_response(
    conn,
    product_name,
    quantity=1,
    fit_text="",
    me=0,
    pe=0,
    blueprint_te=0,
    industry_skill=0,
    advanced_industry_skill=0,
    mass_production_skill=0,
    advanced_mass_production_skill=0,
    supply_chain_management_skill=0,
    structure_material_bonus=0,
    structure_time_bonus=0,
    rig_material_bonus=0,
    rig_time_bonus=0,
):
    tree = build_tree(
        conn,
        product_name,
        quantity,
        me=me,
        pe=pe,
        blueprint_te=blueprint_te,
        industry_skill=industry_skill,
        advanced_industry_skill=advanced_industry_skill,
        mass_production_skill=mass_production_skill,
        advanced_mass_production_skill=advanced_mass_production_skill,
        supply_chain_management_skill=supply_chain_management_skill,
        structure_material_bonus=structure_material_bonus,
        structure_time_bonus=structure_time_bonus,
        rig_material_bonus=rig_material_bonus,
        rig_time_bonus=rig_time_bonus,
    )

    tree["inputs"] = get_manufacturing_context(
        blueprint_me=me,
        blueprint_te=blueprint_te,
        production_efficiency=pe,
        industry_skill=industry_skill,
        advanced_industry_skill=advanced_industry_skill,
        mass_production_skill=mass_production_skill,
        advanced_mass_production_skill=advanced_mass_production_skill,
        supply_chain_management_skill=supply_chain_management_skill,
        structure_material_bonus=structure_material_bonus,
        structure_time_bonus=structure_time_bonus,
        rig_material_bonus=rig_material_bonus,
        rig_time_bonus=rig_time_bonus,
    )

    fit_items = parse_fit(fit_text)
    for item in fit_items:
        sub = build_tree(
            conn,
            item,
            quantity,
            me=me,
            pe=pe,
            blueprint_te=blueprint_te,
            industry_skill=industry_skill,
            advanced_industry_skill=advanced_industry_skill,
            mass_production_skill=mass_production_skill,
            advanced_mass_production_skill=advanced_mass_production_skill,
            supply_chain_management_skill=supply_chain_management_skill,
            structure_material_bonus=structure_material_bonus,
            structure_time_bonus=structure_time_bonus,
            rig_material_bonus=rig_material_bonus,
            rig_time_bonus=rig_time_bonus,
        )
        fit_node = {
            "name": sub.get("name", item),
            "quantity": quantity,
            "buildable": sub.get("buildable", False),
            "buy_price": sub.get("buy_price"),
            "line_total": sub.get("line_total"),
            "selected_total_cost": sub.get("total_cost"),
            "components": sub,
        }
        tree["materials"].append(fit_node)

        if sub.get("total_cost") is not None:
            tree["total_cost"] += sub["total_cost"]

    return tree


def parse_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None and parsed < minimum:
        parsed = minimum

    if maximum is not None and parsed > maximum:
        parsed = maximum

    return parsed


class LegacyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        conn = None

        try:
            query = parse_qs(urlparse(self.path).query)

            name = query.get("name", [None])[0]
            if not name:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing required parameter: name"}).encode())
                return

            quantity = parse_int(query.get("quantity", ["1"])[0], default=1, minimum=1)
            fit = query.get("fit", [""])[0]
            me = parse_int(query.get("blueprint_me", ["0"])[0], default=0, minimum=0, maximum=100)
            pe = parse_int(query.get("production_efficiency", ["0"])[0], default=0, minimum=0, maximum=100)
            blueprint_te = parse_int(query.get("blueprint_te", ["0"])[0], default=0, minimum=0, maximum=20)
            industry_skill = parse_int(query.get("industry_skill", ["0"])[0], default=0, minimum=0, maximum=5)
            advanced_industry_skill = parse_int(query.get("advanced_industry_skill", ["0"])[0], default=0, minimum=0, maximum=5)
            mass_production_skill = parse_int(query.get("mass_production_skill", ["0"])[0], default=0, minimum=0, maximum=5)
            advanced_mass_production_skill = parse_int(query.get("advanced_mass_production_skill", ["0"])[0], default=0, minimum=0, maximum=5)
            supply_chain_management_skill = parse_int(query.get("supply_chain_management_skill", ["0"])[0], default=0, minimum=0, maximum=5)
            structure_material_bonus = parse_int(query.get("structure_material_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
            structure_time_bonus = parse_int(query.get("structure_time_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
            rig_material_bonus = parse_int(query.get("rig_material_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
            rig_time_bonus = parse_int(query.get("rig_time_bonus", ["0"])[0], default=0, minimum=0, maximum=100)

            conn = get_connection()
            response = build_response(
                conn,
                name,
                quantity,
                fit,
                me,
                pe,
                blueprint_te,
                industry_skill,
                advanced_industry_skill,
                mass_production_skill,
                advanced_mass_production_skill,
                supply_chain_management_skill,
                structure_material_bonus,
                structure_time_bonus,
                rig_material_bonus,
                rig_time_bonus,
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Internal server error", "details": str(e)}).encode())
        finally:
            if conn is not None:
                conn.close()


# WSGI entrypoint for deployment

def app(environ, start_response):
    conn = None

    try:
        query = parse_qs(environ.get("QUERY_STRING", ""))

        name = query.get("name", [None])[0]
        if not name:
            status = "400 Bad Request"
            body = json.dumps({"error": "Missing required parameter: name"}).encode()
            headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
            start_response(status, headers)
            return [body]

        quantity = parse_int(query.get("quantity", ["1"])[0], default=1, minimum=1)
        fit = query.get("fit", [""])[0]
        me = parse_int(query.get("blueprint_me", ["0"])[0], default=0, minimum=0, maximum=100)
        pe = parse_int(query.get("production_efficiency", ["0"])[0], default=0, minimum=0, maximum=100)
        blueprint_te = parse_int(query.get("blueprint_te", ["0"])[0], default=0, minimum=0, maximum=20)
        industry_skill = parse_int(query.get("industry_skill", ["0"])[0], default=0, minimum=0, maximum=5)
        advanced_industry_skill = parse_int(query.get("advanced_industry_skill", ["0"])[0], default=0, minimum=0, maximum=5)
        mass_production_skill = parse_int(query.get("mass_production_skill", ["0"])[0], default=0, minimum=0, maximum=5)
        advanced_mass_production_skill = parse_int(query.get("advanced_mass_production_skill", ["0"])[0], default=0, minimum=0, maximum=5)
        supply_chain_management_skill = parse_int(query.get("supply_chain_management_skill", ["0"])[0], default=0, minimum=0, maximum=5)
        structure_material_bonus = parse_int(query.get("structure_material_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
        structure_time_bonus = parse_int(query.get("structure_time_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
        rig_material_bonus = parse_int(query.get("rig_material_bonus", ["0"])[0], default=0, minimum=0, maximum=100)
        rig_time_bonus = parse_int(query.get("rig_time_bonus", ["0"])[0], default=0, minimum=0, maximum=100)

        conn = get_connection()
        response = build_response(
            conn,
            name,
            quantity,
            fit,
            me,
            pe,
            blueprint_te,
            industry_skill,
            advanced_industry_skill,
            mass_production_skill,
            advanced_mass_production_skill,
            supply_chain_management_skill,
            structure_material_bonus,
            structure_time_bonus,
            rig_material_bonus,
            rig_time_bonus,
        )

        body = json.dumps(response).encode()
        status = "200 OK"
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        start_response(status, headers)
        return [body]
    except Exception as e:
        body = json.dumps({"error": "Internal server error", "details": str(e)}).encode()
        status = "500 Internal Server Error"
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        start_response(status, headers)
        return [body]
    finally:
        if conn is not None:
            conn.close()
