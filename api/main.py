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


def parse_fit(fit_text):
    if not fit_text:
        return []

    items = []
    for line in fit_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        item = line.split(",")[0].strip()
        if item:
            items.append(item)

    return items


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
    rig_time_bonus=0
):
    if depth > max_depth:
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "buildable": False,
            "error": "Max depth reached"
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
            "total_cost": total_cost
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
        base_qty = row["materialQuantity"] * runs_needed
        material_qty = apply_material_modifiers(base_qty, me, pe, structure_material_bonus, rig_material_bonus)
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
                rig_time_bonus=rig_time_bonus
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
            elif decision["build_vs_buy"] == "marginal" and market_total_price is not None and component_total_cost is not None:
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


def collect_hybrid_requirements(tree, hybrid=None):
    if hybrid is None:
        hybrid = {
            "buy_components": [],
            "build_components": [],
            "marginal_components": [],
            "raw_materials": defaultdict(int)
        }

    for material in tree.get("materials", []):
        if material.get("buildable"):
            entry = {
                "name": material.get("name"),
                "quantity": material.get("quantity"),
                "unit_market_price": material.get("unit_market_price"),
                "market_total_price": material.get("market_total_price"),
                "component_total_cost": material.get("components", {}).get("total_cost"),
                "difference_percent": material.get("difference_percent"),
                "savings": material.get("savings")
            }

            decision = material.get("build_vs_buy")
            if decision == "buy":
                hybrid["buy_components"].append(entry)
            elif decision == "build":
                hybrid["build_components"].append(entry)
                collect_raw_materials(material.get("components", {}), hybrid["raw_materials"])
            elif decision == "marginal":
                hybrid["marginal_components"].append(entry)
        else:
            hybrid["raw_materials"][material.get("name")] += material.get("quantity", 0)

    return hybrid


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
    rig_time_bonus=0
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
        "remote_job_range_jumps": supply_chain_management_skill * 5
    }


def build_response(
    conn,
    product_name,
    quantity=1,
    mode="tree",
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
    rig_time_bonus=0
):
    tree = build_tree(
        conn,
        product_name,
        quantity=quantity,
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
        rig_time_bonus=rig_time_bonus
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
        rig_time_bonus=rig_time_bonus
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
            rig_time_bonus=rig_time_bonus
        )
        tree.setdefault("fit_items", []).append(sub)
        if sub.get("total_cost") is not None:
            tree["total_cost"] += sub["total_cost"]

    type_id = resolve_type_id(product_name)
    market_price = get_buy_price(type_id)
    market_total_price = market_price * quantity if market_price is not None else None

    decision = evaluate_build_vs_buy(tree.get("total_cost"), market_total_price)
    decision["unit_market_price"] = market_price
    decision["market_total_price"] = market_total_price

    plan = extract_build_buy_plan(tree)
    hybrid = collect_hybrid_requirements(tree)
    hybrid_raw_list = [
        {"name": name, "quantity": qty}
        for name, qty in sorted(hybrid["raw_materials"].items())
    ]
    hybrid_plan = {
        "buy_components": hybrid["buy_components"],
        "build_components": hybrid["build_components"],
        "marginal_components": hybrid["marginal_components"],
        "raw_materials": hybrid_raw_list
    }

    if mode == "tree":
        return {
            **tree,
            **decision,
            "plan": plan,
            "hybrid_plan": hybrid_plan
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
            "plan": plan,
            "hybrid_plan": hybrid_plan,
            "inputs": tree.get("inputs"),
            "fit_items": tree.get("fit_items", [])
        }

    if mode == "both":
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "tree": tree,
            "raw_materials": raw_list,
            **decision,
            "plan": plan,
            "hybrid_plan": hybrid_plan,
            "inputs": tree.get("inputs"),
            "fit_items": tree.get("fit_items", [])
        }

    return {
        "error": f"Invalid mode '{mode}'. Use tree, raw, or both."
    }


class MarketError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def esi_request(path, names=None, params=None):
    """Keep market failures distinct from an empty market, with bounded I/O."""
    url = "https://esi.evetech.net/latest" + path
    kwargs = {
        "timeout": 10,
        "headers": {"User-Agent": "Eve-Market (https://github.com/MahnaD88/Eve-Market)"},
    }
    try:
        if names is None:
            response = requests.get(url, params=params, **kwargs)
        else:
            response = requests.post(url, json=names, **kwargs)
        if response.status_code == 404:
            raise MarketError("EVE item or location not found", 404)
        if response.status_code in (420, 429, 503):
            raise MarketError("EVE market service temporarily unavailable; retry later", 503)
        response.raise_for_status()
        return response.json(), response.headers
    except requests.Timeout as exc:
        raise MarketError("EVE market service timed out", 504) from exc
    except (requests.RequestException, ValueError) as exc:
        raise MarketError("Unable to retrieve EVE market data", 502) from exc


def market_name_id(name, category):
    data, _ = esi_request("/universe/ids/", names=[name.strip()])
    for item in data.get(category, []):
        if item["name"].casefold() == name.strip().casefold():
            return item["id"]
    raise MarketError(f"Unknown {category.replace('_', ' ')} name: {name}", 404)


def market_response(type_id=None, name=None, region_name=None, scan=None,
                    cheapest=None, top=10):
    """Return public sell orders, ordered by price across the requested scope."""
    if top < 1:
        raise MarketError("top must be a positive integer")
    flag = str(cheapest or "false").strip().lower()
    if flag not in ("true", "false", "1", "0"):
        raise MarketError("cheapest must be true or false")
    check_all = flag in ("true", "1")
    if type_id is not None:
        try:
            type_id = int(type_id)
            if type_id < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise MarketError("typeId must be a positive integer")
    elif name and name.strip():
        type_id = market_name_id(name, "inventory_types")
    else:
        raise MarketError("Provide name or typeId for market mode")

    item, _ = esi_request(f"/universe/types/{type_id}/")
    region_id = None
    if region_name and region_name.strip():
        key = region_name.strip().lower()
        region_id = int(REGIONS[key]) if key in REGIONS else market_name_id(region_name, "regions")

    system_id = None
    if scan and scan.strip():
        system_id = market_name_id(scan, "systems")
        system, _ = esi_request(f"/universe/systems/{system_id}/")
        constellation, _ = esi_request(f"/universe/constellations/{system['constellation_id']}/")
        system_region = constellation["region_id"]
        if region_id is not None and region_id != system_region:
            raise MarketError("scan system is not in region_name")
        region_id = system_region

    if region_id is not None:
        regions = [region_id]
    elif check_all:
        regions = [int(REGIONS[key]) for key in CHECK_REGIONS]
    else:
        regions = [int(REGIONS["jita"])]
    orders = []
    for current_region in regions:
        page = 1
        while True:
            batch, headers = esi_request(
                f"/markets/{current_region}/orders/",
                params={"order_type": "sell", "type_id": type_id, "page": page},
            )
            for order in batch:
                if (not order["is_buy_order"] and order["type_id"] == type_id
                        and (system_id is None or order["system_id"] == system_id)):
                    orders.append({**order, "region_id": current_region})
            if page >= int(headers.get("X-Pages", "1")):
                break
            page += 1

    # Never truncate a page or region before comparing all matching prices.
    orders.sort(key=lambda order: (order["price"], order["order_id"]))
    return {
        "status": "ok", "top": top, "typeId": type_id, "name": item["name"],
        "region_name": region_name, "cheapest": cheapest, "scan": scan,
        "region_ids": regions, "system_id": system_id, "order_type": "sell",
        "total_orders": len(orders), "orders": orders[:top],
        "cheapest_price": orders[0]["price"] if orders else None,
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
        fit = query.get("fit", [""])[0]

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
            me = int(query.get("blueprint_me", ["0"])[0])
            pe = int(query.get("production_efficiency", ["0"])[0])
            blueprint_te = int(query.get("blueprint_te", ["0"])[0])
            industry_skill = int(query.get("industry_skill", ["0"])[0])
            advanced_industry_skill = int(query.get("advanced_industry_skill", ["0"])[0])
            mass_production_skill = int(query.get("mass_production_skill", ["0"])[0])
            advanced_mass_production_skill = int(query.get("advanced_mass_production_skill", ["0"])[0])
            supply_chain_management_skill = int(query.get("supply_chain_management_skill", ["0"])[0])
            structure_material_bonus = int(query.get("structure_material_bonus", ["0"])[0])
            structure_time_bonus = int(query.get("structure_time_bonus", ["0"])[0])
            rig_material_bonus = int(query.get("rig_material_bonus", ["0"])[0])
            rig_time_bonus = int(query.get("rig_time_bonus", ["0"])[0])
        except ValueError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Manufacturing variables must be integers"
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
                response = build_response(
                    conn,
                    name,
                    quantity=quantity,
                    mode=mode,
                    fit_text=fit,
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
                    rig_time_bonus=rig_time_bonus
                )
                conn.close()

                status = 200 if "error" not in response else 400
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                return

            response = market_response(type_id, name, region_name, scan, check_all, top_n)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except MarketError as e:
            self.send_response(e.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": str(e)
            }).encode())
