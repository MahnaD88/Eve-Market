import json
import sqlite3
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = "eve-indy.sqlite"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_blueprint_and_materials(conn, product_name):
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
    return conn.execute(query, (product_name,)).fetchall()

def is_buildable(conn, item_name):
    query = """
    SELECT 1
    FROM industryActivityProducts p
    JOIN invTypes prod
        ON p.productTypeID = prod.typeID
    WHERE p.activityID = 1
      AND prod.typeName = ?
    LIMIT 1
    """
    return conn.execute(query, (item_name,)).fetchone() is not None

def build_tree(conn, product_name, depth=0, max_depth=10):
    if depth > max_depth:
        return {
            "name": product_name,
            "buildable": False,
            "error": "Max depth reached"
        }

    rows = get_blueprint_and_materials(conn, product_name)

    if not rows:
        return {
            "name": product_name,
            "buildable": False,
            "materials": []
        }

    first = rows[0]

    node = {
        "name": first["productName"],
        "blueprint": first["blueprintName"],
        "output_quantity": first["outputQuantity"],
        "buildable": True,
        "materials": []
    }

    for row in rows:
        material_name = row["materialName"]
        material_qty = row["materialQuantity"]
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
                depth + 1,
                max_depth
            )

        node["materials"].append(material_node)

    return node

class handler(BaseHTTPRequestHandler):
    def do_GET(self):

        # TEST BLOCK
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"test": "build_tree endpoint hit"}).encode())
        return

        query = parse_qs(urlparse(self.path).query)
        name = query.get("name", [None])[0]

        if not name:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Provide name"}).encode())
            return

        try:
            conn = get_connection()
            tree = build_tree(conn, name)
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
