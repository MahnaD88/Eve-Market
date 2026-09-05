import sqlite3
import unittest
from unittest.mock import patch
from api import main


class ReactionTests(unittest.TestCase):
    def setUp(self):
        main.blueprint_cache.clear()
        main.buildable_cache.clear()
        self.conn = main.get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(main.blueprint_cache.clear)
        self.addCleanup(main.buildable_cache.clear)
        for target, value in [('resolve_type_id', '1'), ('get_buy_price', 10)]:
            mock = patch.object(main, target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_known_carbon_fiber_formula_from_bundled_sde(self):
        self.assertTrue(main.is_buildable(self.conn, 'Carbon Fiber'))
        tree = main.build_tree(self.conn, 'Carbon Fiber', quantity=201, me=10, pe=5)
        self.assertTrue(tree['buildable'])
        self.assertEqual(tree['blueprint'], 'Carbon Fiber Reaction Formula')
        self.assertEqual((tree['activity'], tree['activity_id']), ('reaction', 11))
        self.assertEqual((tree['output_quantity'], tree['runs_needed']), (200, 2))
        self.assertEqual({m['name']: m['quantity'] for m in tree['materials']},
                         {'Hydrogen Fuel Block': 10, 'Hydrocarbons': 200, 'Evaporite Deposits': 200})
        self.assertGreater(tree['total_cost'], 0)
        fuel = next(m for m in tree['materials'] if m['name'] == 'Hydrogen Fuel Block')
        self.assertEqual(fuel['components']['activity'], 'manufacturing')
        self.assertIsNotNone(fuel['build_vs_buy'])

    def fixture(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE invTypes(typeID INTEGER, typeName TEXT);
            CREATE TABLE industryActivityProducts(typeID INTEGER, activityID INTEGER, productTypeID INTEGER, quantity INTEGER);
            CREATE TABLE industryActivityMaterials(typeID INTEGER, activityID INTEGER, materialTypeID INTEGER, quantity INTEGER);
            INSERT INTO invTypes VALUES (1,'Final'),(2,'Intermediate'),(3,'Raw'),(4,'Wrong'),(10,'Final Formula'),(20,'Intermediate Formula'),(30,'Alternate Formula');
            INSERT INTO industryActivityProducts VALUES (10,11,1,10),(20,11,2,5),(30,11,1,99);
            INSERT INTO industryActivityMaterials VALUES (10,11,2,3),(10,1,4,999),(20,11,3,4),(30,11,4,888);
        ''')
        self.addCleanup(conn.close)
        return conn

    def test_reaction_chain_cost_and_no_cross_activity_or_recipe_rows(self):
        conn = self.fixture()
        rows = main.get_blueprint_and_materials(conn, 'Final')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['activityID'], rows[0]['blueprintTypeID']), (11, 10))
        tree = main.build_tree(conn, 'Final', quantity=11)
        material = tree['materials'][0]
        self.assertEqual(material['quantity'], 6)
        self.assertEqual(material['components']['activity'], 'reaction')
        self.assertEqual(material['components']['runs_needed'], 2)
        self.assertEqual(material['components']['materials'][0]['quantity'], 8)
        self.assertEqual(material['components']['total_cost'], 80)
        self.assertEqual(material['build_vs_buy'], 'buy')
        self.assertEqual(tree['total_cost'], 60)

    def test_manufacturing_preferred_without_mixing_reaction_rows(self):
        conn = self.fixture()
        conn.execute('INSERT INTO industryActivityProducts VALUES (10,1,1,1)')
        tree = main.build_tree(conn, 'Final', me=10)
        self.assertEqual(tree['activity'], 'manufacturing')
        self.assertEqual(tree['output_quantity'], 1)
        self.assertEqual([(m['name'], m['quantity']) for m in tree['materials']], [('Wrong', 900)])
        self.assertEqual(tree['total_cost'], 9000)

    def test_all_bundled_reactions_are_recognised(self):
        names = self.conn.execute('SELECT DISTINCT t.typeName FROM industryActivityProducts p JOIN invTypes t ON t.typeID=p.productTypeID WHERE p.activityID=11').fetchall()
        self.assertGreater(len(names), 0)
        for row in names:
            with self.subTest(name=row[0]):
                self.assertTrue(main.is_buildable(self.conn, row[0]))
                recipe = main.get_blueprint_and_materials(self.conn, row[0])
                self.assertTrue(recipe)
                self.assertEqual(len({(r['blueprintTypeID'], r['activityID']) for r in recipe}), 1)

    def test_reaction_through_all_build_response_modes(self):
        for mode in ('tree', 'raw', 'both'):
            result = main.build_response(self.conn, 'Carbon Fiber', mode=mode)
            self.assertNotIn('error', result)
            self.assertIn('hybrid_plan', result)
            if mode == 'tree':
                self.assertEqual(result['activity'], 'reaction')
            if mode == 'both':
                self.assertEqual(result['tree']['activity'], 'reaction')

if __name__ == '__main__':
    unittest.main()
