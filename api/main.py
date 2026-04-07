from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlparse, parse_qs
import requests

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        type_id = query.get("typeId", [None])[0]
        region = query.get("region", ["10000002"])[0]

        if not type_id:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing typeId"}).encode())
            return

        r = requests.get(
            "https://market.fuzzwork.co.uk/aggregates/",
            params={"region": region, "types": type_id},
            timeout=10
        )
        data = r.json()
        item = data[str(type_id)]

        body = {
            "typeId": int(type_id),
            "region": int(region),
            "buy_max": item["buy"]["max"],
            "sell_min": item["sell"]["min"]
        }

        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
