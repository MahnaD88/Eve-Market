import io
import json
import unittest
from unittest.mock import Mock, patch

import requests

from api import main


def order(order_id, price, system=30000142, buy=False):
    return dict(order_id=order_id, price=price, system_id=system,
                type_id=24698, is_buy_order=buy, location_id=60003760,
                volume_remain=3)


class MarketTests(unittest.TestCase):
    def fake_esi(self, path, names=None, params=None):
        if names is not None:
            categories = {
                "drake": ("inventory_types", 24698),
                "the forge": ("regions", 10000002),
                "jita": ("systems", 30000142),
            }
            match = categories.get(names[0].lower())
            return ({match[0]: [{"id": match[1], "name": names[0]}]} if match else {}), {}
        if path == "/universe/types/24698/":
            return {"name": "Drake"}, {}
        if path == "/universe/systems/30000142/":
            return {"constellation_id": 20000020}, {}
        if path == "/universe/constellations/20000020/":
            return {"region_id": 10000002}, {}
        if path.startswith("/markets/"):
            if params["page"] == 1:
                return [order(1, 100), order(2, 1, system=30000144), order(3, 2, buy=True)], {"X-Pages": "2"}
            return [order(4, 50), order(5, 75)], {"X-Pages": "2"}
        raise AssertionError(path)

    def test_drake_jita_pagination_filter_sort_limit(self):
        with patch.object(main, "esi_request", side_effect=self.fake_esi) as esi:
            result = main.market_response(name=" Drake ", region_name="The Forge",
                                          scan="Jita", cheapest="true", top=2)
        self.assertEqual([o["order_id"] for o in result["orders"]], [4, 5])
        self.assertEqual(result["total_orders"], 3)
        self.assertEqual(result["cheapest_price"], 50)
        self.assertEqual(result["region_ids"], [10000002])
        self.assertEqual(result["typeId"], 24698)
        self.assertEqual(esi.call_args.kwargs["params"]["page"], 2)

    def test_type_id_precedes_name_and_default_region(self):
        with patch.object(main, "esi_request", side_effect=self.fake_esi):
            result = main.market_response(type_id="24698", name="invalid", cheapest="false")
        self.assertEqual(result["name"], "Drake")
        self.assertEqual(result["region_ids"], [10000002])
        self.assertEqual(result["cheapest_price"], 1)

    def test_cheapest_compares_all_configured_regions(self):
        def esi(path, **kwargs):
            if path.startswith("/markets/"):
                price = 1 if "/10000042/" in path else 10
                return [order(int(path.split('/')[2]), price)], {}
            return self.fake_esi(path, **kwargs)
        with patch.object(main, "esi_request", side_effect=esi):
            result = main.market_response(type_id="24698", cheapest="TRUE", top=1)
        self.assertEqual(len(result["region_ids"]), 4)
        self.assertEqual(result["orders"][0]["region_id"], 10000042)

    def test_scan_derives_region(self):
        with patch.object(main, "esi_request", side_effect=self.fake_esi):
            result = main.market_response(name="Drake", scan="Jita")
        self.assertEqual(result["region_ids"], [10000002])
        self.assertEqual(result["system_id"], 30000142)

    def test_region_alias_and_mismatched_scan(self):
        with patch.object(main, "esi_request", side_effect=self.fake_esi):
            self.assertEqual(main.market_response(name="Drake", region_name=" JITA ")["region_ids"], [10000002])
            with self.assertRaisesRegex(main.MarketError, "not in region_name"):
                main.market_response(name="Drake", region_name="Amarr", scan="Jita")

    def test_bad_inputs(self):
        for args in ({}, {"type_id": "bad"}, {"type_id": "0"},
                     {"name": "Drake", "top": 0},
                     {"name": "Drake", "cheapest": "maybe"}):
            with self.subTest(args=args), patch.object(main, "esi_request") as esi:
                with self.assertRaises(main.MarketError):
                    main.market_response(**args)
                esi.assert_not_called()

    def test_unknown_names(self):
        for args in ({"name": "missing"}, {"name": "Drake", "scan": "missing"},
                     {"name": "Drake", "region_name": "missing"}):
            with self.subTest(args=args), patch.object(main, "esi_request", side_effect=self.fake_esi):
                with self.assertRaises(main.MarketError) as error:
                    main.market_response(**args)
                self.assertEqual(error.exception.status, 404)

    def test_empty_orders_are_success(self):
        def esi(path, **kwargs):
            return ([], {}) if path.startswith("/markets/") else self.fake_esi(path, **kwargs)
        with patch.object(main, "esi_request", side_effect=esi):
            result = main.market_response(name="Drake")
        self.assertEqual(result["orders"], [])
        self.assertEqual(result["total_orders"], 0)
        self.assertIsNone(result["cheapest_price"])

    def test_later_page_failure_never_returns_partial_results(self):
        def esi(path, **kwargs):
            if kwargs.get("params", {}).get("page") == 2:
                raise main.MarketError("unavailable", 503)
            return self.fake_esi(path, **kwargs)
        with patch.object(main, "esi_request", side_effect=esi):
            with self.assertRaises(main.MarketError):
                main.market_response(name="Drake")

    def test_upstream_errors(self):
        for status, expected in ((404, 404), (420, 503), (429, 503), (503, 503), (500, 502)):
            response = Mock(status_code=status)
            response.raise_for_status.side_effect = requests.HTTPError()
            with self.subTest(status=status), patch.object(main.requests, "get", return_value=response):
                with self.assertRaises(main.MarketError) as error:
                    main.esi_request("/test/")
                self.assertEqual(error.exception.status, expected)
        for failure, expected in ((requests.Timeout(), 504), (requests.ConnectionError(), 502)):
            with patch.object(main.requests, "get", side_effect=failure):
                with self.assertRaises(main.MarketError) as error:
                    main.esi_request("/test/")
                self.assertEqual(error.exception.status, expected)

    def test_request_methods_and_json_failure(self):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {}
        with patch.object(main.requests, "post", return_value=response) as post:
            main.esi_request("/universe/ids/", names=["Drake"])
            self.assertEqual(post.call_args.kwargs["json"], ["Drake"])
            self.assertEqual(post.call_args.kwargs["timeout"], 10)
        response.json.side_effect = ValueError()
        with patch.object(main.requests, "get", return_value=response):
            with self.assertRaises(main.MarketError) as error:
                main.esi_request("/test/")
            self.assertEqual(error.exception.status, 502)


class HandlerTests(unittest.TestCase):
    def invoke(self, query):
        request = object.__new__(main.handler)
        request.path = "/api/main?" + query
        request.wfile = io.BytesIO()
        request.send_response = Mock()
        request.send_header = Mock()
        request.end_headers = Mock()
        request.do_GET()
        return request.send_response.call_args.args[0], json.loads(request.wfile.getvalue())

    def test_market_dispatch_and_legacy_invalid_top_default(self):
        with patch.object(main, "market_response", return_value={"orders": []}) as market:
            status, body = self.invoke("name=Drake&region_name=The+Forge&scan=Jita&cheapest=true&top=invalid")
        market.assert_called_once_with(None, "Drake", "The Forge", "Jita", "true", 10)
        self.assertEqual((status, body), (200, {"orders": []}))

    def test_market_error_status(self):
        with patch.object(main, "market_response", side_effect=main.MarketError("unavailable", 503)):
            self.assertEqual(self.invoke("name=Drake"), (503, {"error": "unavailable"}))

    def test_build_modes_still_use_existing_response(self):
        for mode in ("tree", "raw", "both"):
            with self.subTest(mode=mode), patch.object(main, "get_connection") as connect, \
                    patch.object(main, "build_response", return_value={"original": mode}) as build, \
                    patch.object(main, "market_response") as market:
                status, body = self.invoke(f"mode={mode}&name=Drake&quantity=2&blueprint_me=10")
                self.assertEqual((status, body), (200, {"original": mode}))
                self.assertEqual(build.call_args.kwargs["mode"], mode)
                self.assertEqual(build.call_args.kwargs["quantity"], 2)
                self.assertEqual(build.call_args.kwargs["me"], 10)
                connect.return_value.close.assert_called_once()
                market.assert_not_called()

    def test_existing_validation(self):
        for query in ("mode=tree", "name=Drake&quantity=0", "name=Drake&blueprint_me=bad"):
            with self.subTest(query=query):
                self.assertEqual(self.invoke(query)[0], 400)


if __name__ == "__main__":
    unittest.main()
