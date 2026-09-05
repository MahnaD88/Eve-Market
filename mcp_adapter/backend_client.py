"""Bounded GET-only client. No industry calculations or database access."""
import asyncio
import json
import math
import httpx

BACKEND_URL = "https://eve-market-weld.vercel.app"

class BackendError(Exception):
    pass

class BackendClient:
    def __init__(self, *, transport=None, timeout_seconds=120, max_bytes=1024 * 1024):
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    async def get(self, path, params):
        if path not in ("/api/main", "/market-history"):
            raise ValueError("Unsupported backend route")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self.transport, timeout=httpx.Timeout(30, connect=10),
                    follow_redirects=False, trust_env=False,
                    headers={"Accept": "application/json", "User-Agent": "Eve-Industry-MCP/0.1"},
                ) as client:
                    async with client.stream("GET", BACKEND_URL + path, params=params) as response:
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                raise BackendError(f"Backend HTTP {response.status_code}: response exceeds {self.max_bytes} bytes; no partial result returned. Request fewer orders, history days or a smaller production request.")
                        try:
                            def reject_constant(value):
                                raise ValueError("Non-finite JSON value")
                            def finite_float(value):
                                number = float(value)
                                if not math.isfinite(number):
                                    raise ValueError("Non-finite JSON value")
                                return number
                            data = json.loads(body, parse_constant=reject_constant, parse_float=finite_float)
                        except (ValueError, UnicodeError):
                            excerpt = body[:1000].decode("utf-8", errors="replace")
                            raise BackendError(f"Backend HTTP {response.status_code}: invalid JSON: {excerpt}") from None
                        if not 200 <= response.status_code < 300 or (isinstance(data, dict) and "error" in data):
                            raise BackendError(f"Backend HTTP {response.status_code}: {json.dumps(data, separators=(',', ':'))}")
                        if not isinstance(data, dict):
                            raise BackendError("Backend returned a non-object JSON response")
                        return data
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise BackendError("Backend request timed out; no result returned") from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"Backend connection failed ({type(exc).__name__}); no result returned") from exc
