import io
import json
import unittest
from unittest.mock import Mock, patch

from api import main


ROWS = [
    dict(date="2026-09-03", average=100, highest=120, lowest=80, order_count=10, volume=20),
    dict(date="2026-09-05", average=200, highest=240, lowest=160, order_count=30, volume=60),
    dict(date="2026-09-04", average=150, highest=180, lowest=120, order_count=20, volume=40),
]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.names = patch.object(main, "market_name_id", side_effect=lambda name, category: 24698 if category == "inventory_types" else 10000002)
        self.names.start()
        self.addCleanup(self.names.stop)
        self.cache = patch.dict(main.buy_price_cache, {}, clear=True)
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def test_summary_and_latest_days(self):
        with patch.object(main, "esi_request", return_value=(ROWS, {})) as esi:
            result = main.market_history_response("Drake", "The Forge", "2")
        esi.assert_called_once_with("/markets/10000002/history/", params={"type_id": 24698})
        self.assertEqual(result["history"], [ROWS[2], ROWS[1]])
        self.assertEqual(result["summary"], dict(
            average_price=175, average_daily_volume=50, total_volume=100,
            lowest_price=120, highest_price=240, average_order_count=25,
            days_returned=2, current_vs_average=None))

    def test_all_history_and_oversized_limit(self):
        for days in (None, "999"):
            with self.subTest(days=days), patch.object(main, "esi_request", return_value=(ROWS, {})):
                result = main.market_history_response("Drake", "JITA", days)
                self.assertEqual(result["summary"]["days_returned"], 3)
                self.assertEqual(result["summary"]["average_price"], 150)
                self.assertEqual(result["region_id"], 10000002)

    def test_validation_before_network(self):
        for name, region, days in [(None, "Jita", None), ("Drake", None, None),
                                   (" ", "Jita", None), ("Drake", " ", None)]:
            with self.subTest(name=name, region=region), self.assertRaises(main.MarketError):
                main.market_history_response(name, region, days)
        for days in ("0", "-1", "bad", "1.5", ""):
            with self.subTest(days=days), patch.object(main, "esi_request") as esi:
                with self.assertRaisesRegex(main.MarketError, "days must"):
                    main.market_history_response("Drake", "Jita", days)
                esi.assert_not_called()

    def test_empty_history(self):
        with patch.object(main, "esi_request", return_value=([], {})):
            result = main.market_history_response("Drake", "Jita")
        self.assertEqual(result["history"], [])
        self.assertEqual(result["summary"]["total_volume"], 0)
        self.assertEqual(result["summary"]["days_returned"], 0)
        for field in ("average_price", "average_daily_volume", "lowest_price",
                      "highest_price", "average_order_count", "current_vs_average"):
            self.assertIsNone(result["summary"][field])

    def test_optional_comparison_does_not_fetch_prices(self):
        main.buy_price_cache["24698"] = 180
        with patch.object(main, "esi_request", return_value=(ROWS, {})), patch.object(main, "get_buy_price") as price:
            comparison = main.market_history_response("Drake", "Jita")["summary"]["current_vs_average"]
        price.assert_not_called()
        self.assertEqual(comparison["difference"], 30)
        self.assertEqual(comparison["difference_percent"], 20)
        self.assertEqual(comparison["freshness"], "unknown")
        self.assertEqual(len(comparison["region_ids"]), 4)

    def test_zero_average(self):
        main.buy_price_cache["24698"] = 180
        with patch.object(main, "esi_request", return_value=([{**ROWS[0], "average": 0}], {})):
            self.assertIsNone(main.market_history_response("Drake", "Jita")["summary"]["current_vs_average"])

    def test_invalid_upstream_data(self):
        for data in ({}, [None], [{"date": "2026-09-01"}], [{**ROWS[0], "volume": -1}],
                     [{**ROWS[0], "average": float("nan")}], [{**ROWS[0], "date": "invalid"}]):
            with self.subTest(data=data), patch.object(main, "esi_request", return_value=(data, {})):
                with self.assertRaises(main.MarketError) as error:
                    main.market_history_response("Drake", "Jita")
                self.assertEqual(error.exception.status, 502)

    def test_resolution_and_upstream_errors_propagate(self):
        for status in (404, 502, 503, 504):
            with self.subTest(status=status), patch.object(main, "esi_request", side_effect=main.MarketError("failure", status)):
                with self.assertRaises(main.MarketError) as error:
                    main.market_history_response("Drake", "Jita")
                self.assertEqual(error.exception.status, status)
        for side_effect in ([main.MarketError("Unknown item", 404)], [24698, main.MarketError("Unknown region", 404)]):
            with patch.object(main, "market_name_id", side_effect=side_effect), patch.object(main, "get_market_history") as history:
                with self.assertRaises(main.MarketError):
                    main.market_history_response("unknown", "unknown")
                history.assert_not_called()

    def invoke(self, path):
        request = object.__new__(main.handler)
        request.path = path
        request.wfile = io.BytesIO()
        request.send_response = Mock()
        request.send_header = Mock()
        request.end_headers = Mock()
        request.do_GET()
        return request.send_response.call_args.args[0], json.loads(request.wfile.getvalue())

    def test_route_and_vercel_rewrite_preserve_query(self):
        for path in ("/market-history?", "/market-history/?", "/api/main?_route=market-history&"):
            with self.subTest(path=path), patch.object(main, "esi_request", return_value=(ROWS, {})), patch.object(main, "build_response") as build:
                status, result = self.invoke(path + "name=Drake&region_name=The+Forge&days=2&mode=tree&quantity=bad")
                self.assertEqual(status, 200)
                self.assertEqual(result["summary"]["days_returned"], 2)
                build.assert_not_called()

    def test_http_error_statuses(self):
        for status in (400, 404, 502, 503, 504):
            with patch.object(main, "market_history_response", side_effect=main.MarketError("failure", status)):
                self.assertEqual(self.invoke("/market-history"), (status, {"error": "failure"}))


if __name__ == "__main__":
    unittest.main()
