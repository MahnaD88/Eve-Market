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
            "materials": []
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

    for row in rows:
        material_name = row["materialName"]
        material_qty = row["materialQuantity"] * runs_needed
        material_buildable = is_buildable(conn, material_name)

        material_node = {
            "name": material_name,
            "quantity": material_qty,
            "buildable": material_buildable
        }

        if material_buildable:
            material_node["components"] = build_tree(
                conn,
                material_name,
                quantity=material_qty,
                depth=depth + 1,
                max_depth=max_depth
            )

        node["materials"].append(material_node)

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

    if mode == "tree":
        return tree

    raw_totals = collect_raw_materials(tree)
    raw_list = [
        {"name": name, "quantity": qty}
        for name, qty in sorted(raw_totals.items())
    ]

    if mode == "raw":
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "raw_materials": raw_list
        }

    if mode == "both":
        return {
            "name": product_name,
            "quantity_requested": quantity,
            "tree": tree,
            "raw_materials": raw_list
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
            # BUILD MODE
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

            # LEGACY BUILD MODE SUPPORT
            if mode == "build_tree":
                if not name:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": "Provide name for build_tree mode"
                    }).encode())
                    return

                conn = get_connection()
                response = build_response(conn, name, quantity=quantity, mode="tree")
                conn.close()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                return

            # MARKET MODE
            if check_all:
                regions_to_check = CHECK_REGIONS
            else:
                regions_to_check = [region_name.lower()] if region_name else ["jita"]

            if not type_id and not name and not scan:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Provide name, typeId, or scan"
                }).encode())
                return

            if scan:
                item_names = [item.strip() for item in scan.split(",") if item.strip()]
                results = []

                for item_name in item_names:
                    resolved_name = item_name
                    current_type_id = None
                    volume = None

                    r = requests.get(
                        "https://www.fuzzwork.co.uk/api/typeid.php",
                        params={"typename": item_name},
                        timeout=10
                    )
                    r.raise_for_status()
                    resolved = r.json()

                    if "typeID" not in resolved:
                        continue

                    current_type_id = str(resolved["typeID"])
                    resolved_name = resolved.get("typeName", item_name)

                    esi = requests.get(
                        f"https://esi.evetech.net/latest/universe/types/{current_type_id}/",
                        params={"datasource": "tranquility"},
                        timeout=10
                    )
                    esi.raise_for_status()
                    esi_data = esi.json()
                    volume = esi_data.get("volume")

                    prices = []
                    best_price = None
                    best_region = None
                    best_buy = None
                    best_buy_region = None

                    for r_name in CHECK_REGIONS:
                        r_id = REGIONS.get(r_name)

                        if not r_id:
                            continue

                        market_r = requests.get(
                            "https://market.fuzzwork.co.uk/aggregates/",
                            params={"region": r_id, "types": current_type_id},
                            timeout=10
                        )
                        market_r.raise_for_status()
                        data = market_r.json()

                        if str(current_type_id) not in data:
                            continue

                        sell_price = round(float(data[str(current_type_id)]["sell"]["percentile"]), 2)
                        buy_price = round(float(data[str(current_type_id)]["buy"]["percentile"]), 2)
                        sell_volume = float(data[str(current_type_id)]["sell"]["volume"])
                        buy_volume = float(data[str(current_type_id)]["buy"]["volume"])

                        prices.append({
                            "region": r_name,
                            "sell_min": sell_price,
                            "buy_max": buy_price,
                            "sell_volume": sell_volume,
                            "buy_volume": buy_volume,
                            "sell_orders": data[str(current_type_id)]["sell"].get("orders"),
                            "buy_orders": data[str(current_type_id)]["buy"].get("orders")
                        })

                        if best_price is None or sell_price < best_price:
                            best_price = sell_price
                            best_region = r_name

                        if best_buy is None or buy_price > best_buy:
                            best_buy = buy_price
                            best_buy_region = r_name

                    if best_price is None or best_buy is None:
                        continue

                    profit_per_m3 = None
                    if volume and best_buy is not None and best_price is not None:
                        try:
                            profit_per_m3 = round((best_buy - best_price) / float(volume), 2)
                        except Exception:
                            profit_per_m3 = None

                    results.append({
                        "typeId": int(current_type_id),
                        "name": resolved_name,
                        "volume": volume,
                        "best_sell_region": best_region,
                        "best_sell_min": best_price,
                        "best_buy_region": best_buy_region,
                        "best_buy_max": best_buy,
                        "profit_per_m3": profit_per_m3,
                        "prices": prices
                    })

                results = [r for r in results if r.get("profit_per_m3") is not None]
                results.sort(key=lambda x: x["profit_per_m3"], reverse=True)

                body = {
                    "results": results[:top_n]
                }

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())
                return

            resolved_name = name
            volume = None

            if not type_id and name:
                r = requests.get(
                    "https://www.fuzzwork.co.uk/api/typeid.php",
                    params={"typename": name},
                    timeout=10
                )
                r.raise_for_status()
                resolved = r.json()

                if "typeID" not in resolved:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": f"Item not found: {name}"
                    }).encode())
                    return

                type_id = str(resolved["typeID"])
                resolved_name = resolved.get("typeName", name)

            esi = requests.get(
                f"https://esi.evetech.net/latest/universe/types/{type_id}/",
                params={"datasource": "tranquility"},
                timeout=10
            )
            esi.raise_for_status()
            esi_data = esi.json()
            volume = esi_data.get("volume")

            prices = []
            best_price = None
            best_region = None
            best_buy = None
            best_buy_region = None

            for r_name in regions_to_check:
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

                sell_price = round(float(data[str(type_id)]["sell"]["percentile"]), 2)
                buy_price = round(float(data[str(type_id)]["buy"]["percentile"]), 2)
                sell_volume = float(data[str(type_id)]["sell"]["volume"])
                buy_volume = float(data[str(type_id)]["buy"]["volume"])

                prices.append({
                    "region": r_name,
                    "sell_min": sell_price,
                    "buy_max": buy_price,
                    "sell_volume": sell_volume,
                    "buy_volume": buy_volume,
                    "sell_orders": data[str(type_id)]["sell"].get("orders"),
                    "buy_orders": data[str(type_id)]["buy"].get("orders")
                })

                if best_price is None or sell_price < best_price:
                    best_price = sell_price
                    best_region = r_name

                if best_buy is None or buy_price > best_buy:
                    best_buy = buy_price
                    best_buy_region = r_name

            if best_price is None or best_buy is None:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "No market data found"
                }).encode())
                return

            profit_per_m3 = None
            if volume and best_buy is not None and best_price is not None:
                try:
                    profit_per_m3 = round((best_buy - best_price) / float(volume), 2)
                except Exception:
                    profit_per_m3 = None

            body = {
                "typeId": int(type_id),
                "name": resolved_name,
                "volume": volume,
                "best_sell_region": best_region,
                "best_sell_min": best_price,
                "best_buy_region": best_buy_region,
                "best_buy_max": best_buy,
                "profit_per_m3": profit_per_m3,
                "prices": prices
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": str(e)
            }).encode())
