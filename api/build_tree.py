import json
import math
import sqlite3
from collections import defaultdict
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = "eve-indy.sqlite"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class BuildTreeService:
    def __init__(self, conn, max_depth=20):
        self.conn = conn
        self.max_depth = max_depth

        # caches
        self.recipe_cache = {}        # product_name -> recipe dict | None
        self.buildable_cache = {}     # item_name -> bool
        self.expansion_cache = {}     # (product_name) -> base tree for qty=1 run

    def get_recipe(self, product_name):
        if product_name in self.recipe_cache:
            return self.recipe_cache[product_name]

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

        rows = self.conn.execute(query, (product_name,)).fetchall()

        if not rows:
            self.recipe_cache[product_name] = None
            self.buildable_cache[product_name] = False
            return None

        first = rows[0]
        recipe = {
            "name": first["productName"],
            "blueprint": first["blueprintName"],
            "output_quantity": first["outputQuantity"],
            "materials": [
                {
                    "name": row["materialName"],
                    "quantity": row["materialQuantity"],
                }
                for row in rows
            ]
        }

        self.recipe_cache[product_name] = recipe
        self.buildable_cache[product_name] = True
        return recipe

    def is_buildable(self, item_name):
        if item_name in self.buildable_cache:
            return self.buildable_cache[item_name]

        result = self.get_recipe(item_name) is not None
        self.buildable_cache[item_name] = result
        return result

    def build_tree(self, product_name, quantity=1, depth=0, stack=None):
        if stack is None:
            stack = set()

        if depth > self.max_depth:
            return {
                "name": product_name,
                "quantity_requested": quantity,
                "buildable": False,
                "error": "Max depth reached"
            }

        if product_name in stack:
            return {
                "name": product_name,
                "quantity_requested": quantity,
                "buildable": False,
                "error": "Circular reference detected"
            }

        recipe = self.get_recipe(product_name)

        if recipe is None:
            return {
                "name": product_name,
                "quantity_requested": quantity,
                "buildable": False,
                "materials": []
            }

        output_quantity = recipe["output_quantity"]
        runs_needed = math.ceil(quantity / output_quantity)

        node = {
            "name": recipe["name"],
            "blueprint": recipe["blueprint"],
            "output_quantity": output_quantity,
            "quantity_requested": quantity,
            "runs_needed": runs_needed,
            "buildable": True,
            "materials": []
        }

        next_stack = set(stack)
        next_stack.add(product_name)

        for material in recipe["materials"]:
            material_name = material["name"]
            base_qty = material["quantity"]
            total_qty = base_qty * runs_needed
            material_buildable = self.is_buildable(material_name)

            material_node = {
                "name": material_name,
                "quantity": total_qty,
                "buildable": material_buildable
            }

            if material_buildable:
                material_node["components"] = self.build_tree(
                    material_name,
                    quantity=total_qty,
                    depth=depth + 1,
                    stack=next_stack
                )

            node["materials"].append(material_node)

        return node

    def collect_raw_materials(self, tree, totals=None):
        if totals is None:
            totals = defaultdict(int)

        if not tree.get("buildable", False):
            qty = tree.get("quantity_requested", 0)
            if qty:
                totals[tree["name"]] += qty
            return totals

        for material in tree.get("materials", []):
            if material.get("buildable"):
                self.collect_raw_materials(material["components"], totals)
            else:
                totals[material["name"]] += material["quantity"]

        return totals

    def build_response(self, product_name, quantity=1, mode="tree"):
        tree = self.build_tree(product_name, quantity=quantity)

        if mode == "tree":
            return tree

        raw_totals = self.collect_raw_materials(tree)
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

        name = query.get("name", [None])[0]
        mode = query.get("mode", ["tree"])[0].lower()

        try:
            quantity = int(query.get("quantity", ["1"])[0])
            if quantity < 1:
                raise ValueError("quantity must be >= 1")
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
            service = BuildTreeService(conn)
            response = service.build_response(name, quantity=quantity, mode=mode)
            conn.close()

            status = 200 if "error" not in response else 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
