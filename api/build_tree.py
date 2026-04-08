import json
import math
import sqlite3
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = "eve-indy.sqlite"

# CACHES
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

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        name = query.get("name", [None])[0]

        try:
            quantity = int(query.get("quantity", ["1"])[0])
            if quantity < 1:
                raise ValueError
        except ValueError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "quantity must be a positive integer"}).encode())
            return

        if not name:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Provide name"}).encode())
            return

        try:
            conn = get_connection()
            tree = build_tree(conn, name, quantity=quantity)
            conn.close()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(tree).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
