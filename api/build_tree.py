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

        # resolve type_id
        type_id = None
        try:
            r = requests.get(
                "https://www.fuzzwork.co.uk/api/typeid.php",
                params={"typename": material_name},
                timeout=5
            )
            resolved = r.json()
            if "typeID" in resolved:
                type_id = str(resolved["typeID"])
        except Exception:
            type_id = None

        buy_price = None
        if type_id:
            try:
                buy_price = get_buy_price(type_id)
            except Exception:
                buy_price = None

        material_node = {
            "name": material_name,
            "quantity": material_qty,
            "buildable": material_buildable,
            "buy_price": buy_price
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
