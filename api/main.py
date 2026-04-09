class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        mode = query.get("mode", [None])[0]
        type_id = query.get("typeId", [None])[0]
        name = query.get("name", [None])[0]

        # NORMALISE
        if mode:
            mode = mode.strip().lower()

        # DEBUG BLOCK (TEMP)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "debug_mode": mode,
            "debug_name": name,
            "debug_path": self.path
        }).encode())
        return
