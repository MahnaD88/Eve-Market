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
        region = query.get("region", [None])[0]
        region_name = query.get("region_name", [None])[0]

        if region_name:
            region = REGIONS.get(region_name.lower())

        if not region:
            region = "10000002"

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

            r = requests.get(
                "https://market.fuzzwork.co.uk/aggregates/",
                params={"region": region, "types": type_id},
                timeout=10
            )
            r.raise_for_status()
            data = r.json()

            if str(type_id) not in data:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": f"No market data found for typeId {type_id} in region {region}"
                }).encode())
                return

            item = data[str(type_id)]

            body = {
                "typeId": int(type_id),
                "name": resolved_name,
                "region": int(region),
                "region_name": region_name,
                "buy_max": item["buy"]["max"],
                "sell_min": item["sell"]["min"]
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
