import sqlite3
import unittest
from unittest.mock import patch
from api import main


class CostCompletenessTests(unittest.TestCase):
    def setUp(self):
        main.blueprint_cache.clear()
        main.buildable_cache.clear()
        self.addCleanup(main.blueprint_cache.clear)
        self.addCleanup(main.buildable_cache.clear)
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            CREATE TABLE invTypes(typeID INTEGER, typeName TEXT);
            CREATE TABLE industryActivityProducts(typeID INTEGER, activityID INTEGER, productTypeID INTEGER, quantity INTEGER);
            CREATE TABLE industryActivityMaterials(typeID INTEGER, activityID INTEGER, materialTypeID INTEGER, quantity INTEGER);
            INSERT INTO invTypes VALUES (1,'Final'),(2,'Intermediate'),(3,'Known'),(4,'Missing'),(10,'Blueprint'),(20,'Formula');
            INSERT INTO industryActivityProducts VALUES (10,1,1,1),(20,11,2,1);
            INSERT INTO industryActivityMaterials VALUES (10,1,2,2),(20,11,3,3),(20,11,4,4);
        ''')
        self.prices = {'Final': 1000, 'Intermediate': 100, 'Known': 10}
        for target, effect in [('resolve_type_id', lambda name: name),
                               ('get_buy_price', self.prices.get)]:
            mock = patch.object(main, target, side_effect=effect)
            mock.start()
            self.addCleanup(mock.stop)

    def assert_incomplete(self, result):
        self.assertFalse(result['cost_complete'])
        self.assertIsNone(result['total_cost'])
        self.assertEqual(result['missing_prices'], ['Missing'])

    def test_direct_missing_price_manufacturing_and_reaction(self):
        for activity in (1, 11):
            with self.subTest(activity=activity):
                self.conn.execute('UPDATE industryActivityProducts SET activityID=? WHERE typeID=20', (activity,))
                self.conn.execute('UPDATE industryActivityMaterials SET activityID=? WHERE typeID=20', (activity,))
                main.blueprint_cache.clear()
                result = main.build_response(self.conn, 'Intermediate')
                self.assert_incomplete(result)
                self.assertIsNone(result['build_vs_buy'])
                missing = next(m for m in result['materials'] if m['name'] == 'Missing')
                self.assertFalse(missing['cost_complete'])
                self.assertIsNone(missing['selected_total_cost'])

    def test_recursive_missing_price_in_all_response_modes(self):
        for mode in ('tree', 'raw', 'both'):
            with self.subTest(mode=mode):
                result = main.build_response(self.conn, 'Final', mode=mode)
                self.assert_incomplete(result)
                for key in ('build_vs_buy', 'savings', 'difference_percent', 'margin_threshold'):
                    self.assertIsNone(result[key])
                self.assertFalse(result['plan']['cost_complete'])
                self.assertFalse(result['hybrid_plan']['cost_complete'])
                if mode != 'raw':
                    tree = result if mode == 'tree' else result['tree']
                    material = tree['materials'][0]
                    self.assertFalse(material['cost_complete'])
                    self.assertIsNone(material['build_vs_buy'])
                    self.assertIsNone(material['selected_total_cost'])
                    self.assert_incomplete(material['components'])

    def test_complete_cost_and_existing_buy_selection(self):
        self.prices['Missing'] = 50
        result = main.build_response(self.conn, 'Final')
        self.assertTrue(result['cost_complete'])
        self.assertEqual(result['missing_prices'], [])
        self.assertEqual(result['total_cost'], 200)
        self.assertEqual(result['materials'][0]['components']['total_cost'], 460)
        self.assertEqual(result['materials'][0]['build_vs_buy'], 'buy')
        self.assertEqual(result['build_vs_buy'], 'build')

    def test_missing_comparison_quote_does_not_invalidate_material_cost(self):
        self.prices.update(Missing=1)
        self.prices.pop('Intermediate')
        result = main.build_response(self.conn, 'Intermediate')
        self.assertTrue(result['cost_complete'])
        self.assertEqual(result['total_cost'], 34)
        self.assertIsNone(result['build_vs_buy'])

    def test_missing_fit_price_and_incomplete_root_with_priced_fit(self):
        self.assert_incomplete(main.build_response(self.conn, 'Known', fit_text='Missing'))
        self.assert_incomplete(main.build_response(self.conn, 'Final', fit_text='Known'))

    def test_unresolved_type_id_is_missing_price(self):
        with patch.object(main, 'resolve_type_id', return_value=None):
            self.assert_incomplete(main.build_tree(self.conn, 'Missing'))

    def test_depth_cutoff_propagates_incompleteness(self):
        result = main.build_tree(self.conn, 'Final', max_depth=0)
        self.assertFalse(result['cost_complete'])
        self.assertIsNone(result['total_cost'])
        self.assertEqual(result['missing_prices'], [])
        self.assertEqual(result['incomplete_reasons'], ['Max depth reached'])


if __name__ == '__main__':
    unittest.main()
