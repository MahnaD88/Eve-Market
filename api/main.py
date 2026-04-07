from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlparse, parse_qs
import requests

REGIONS = {
    "jita": "10000002",
    "amarr": "10000043",
    "dodixie": "10000032",
    "hek": "10000042"
}


CHECK_REGIONS = ["jita", "amarr", "dodixie", "hek"]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        type_id = query.get("typeId", [None])[0]
        name = query.get("name", [None])[0]
        region_name = query.get("region_name", [None])[0]
        check_all = query.get("cheapest", [None])[0]
        scan = query.get("scan", [None])[0]

        if check_all:
            regions_to_check = CHECK_REGIONS
        else:
            regions_to_check = [region_name.lower()] if region_name else ["jita"]

        if not type_id and not name:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Provide either typeId or name"
            }).encode())
            return

        try:
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
