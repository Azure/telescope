import unittest
from kusto.generate_commands import infer_type, generate_kusto_commands

class TestInferType(unittest.TestCase):
    def test_infer_bool(self):
        self.assertEqual(infer_type('true'), 'bool')
        self.assertEqual(infer_type('false'), 'bool')
        self.assertEqual(infer_type('True'), 'bool')
        self.assertEqual(infer_type('False'), 'bool')
        self.assertNotEqual(infer_type('abc'), 'bool')
        self.assertNotEqual(infer_type('123'), 'bool')
        self.assertNotEqual(infer_type(1234), 'bool')
        self.assertNotEqual(infer_type('4.077777777777777777777'), 'bool')
        self.assertNotEqual(infer_type(4.077777777777777777777), 'bool')

    def test_infer_real(self):
        self.assertEqual(infer_type('123'), 'real')
        self.assertEqual(infer_type(1234), 'real')
        self.assertEqual(infer_type('4.077777777777777777777'), 'real')
        self.assertEqual(infer_type('92233720368547758088888'), 'real')
        self.assertEqual(infer_type(12.25), 'real')
        self.assertNotEqual(infer_type('abc'), 'real')
        self.assertNotEqual(infer_type('true'), 'real')
        self.assertNotEqual(infer_type('{"key": "value"}'), 'real')
        self.assertNotEqual(infer_type('2022-01-01T12:00:00Z'), 'real')

    def test_infer_dynamic(self):
        self.assertEqual(infer_type({"key": "value"}), 'dynamic')
        self.assertEqual(infer_type([1,2,3,4]), 'dynamic')
        self.assertEqual(infer_type('{"key": "value"}'), 'dynamic')
        self.assertEqual(infer_type('[1, 2, 3]'), 'dynamic')
        self.assertNotEqual(infer_type('abc'), 'dynamic')
        self.assertNotEqual(infer_type('123'), 'dynamic')
        self.assertNotEqual(infer_type('true'), 'dynamic')
        self.assertNotEqual(infer_type(123456), 'dynamic')
        self.assertNotEqual(infer_type(12.25), 'dynamic')


    def test_infer_datetime(self):
        self.assertEqual(infer_type('2022-01-01T12:00:00Z'), 'datetime')
        self.assertEqual(infer_type('2024-12-26T12:14:50.637517'), 'datetime')
        self.assertEqual(infer_type('2024-12-26T15:02:17.681161609Z'), 'datetime')
        self.assertNotEqual(infer_type('abc'), 'datetime')
        self.assertNotEqual(infer_type('123'), 'datetime')
        self.assertNotEqual(infer_type(123456), 'datetime')
        self.assertNotEqual(infer_type({"key": "value"}), 'datetime')
        self.assertNotEqual(infer_type([1,2,3,4]), 'datetime')
        self.assertNotEqual(infer_type('true'), 'datetime')
        self.assertNotEqual(infer_type('{"key": "value"}'), 'datetime')

    def test_infer_string(self):
        self.assertEqual(infer_type('hello'), 'string')
        self.assertEqual(infer_type('!@#$%^&*()'), 'string')
        self.assertNotEqual(infer_type('123'), 'string')
        self.assertNotEqual(infer_type('true'), 'string')
        self.assertNotEqual(infer_type('{"key": "value"}'), 'string')
        self.assertNotEqual(infer_type('2022-01-01T12:00:00Z'), 'string')
        self.assertNotEqual(infer_type(123456), 'string')
        self.assertNotEqual(infer_type({"key": "value"}), 'string')
        self.assertNotEqual(infer_type([1,2,3,4]), 'string')

class TestGenerateKustoCommands(unittest.TestCase):
    def test_generate_kusto_commands(self):
        data = {
            'column1': 'value1',
            'column2': '123',
            'column3': '{"key": "value"}',
            'column4': '2022-01-01T12:00:00Z',
            'column5': '4.077777777777777777777',
            'column6': '92233720368547758088888',
        }
        table_name = 'test_table'
        expected_result = (
            ".create table ['test_table'] (['column1']:string, ['column2']:real, "
            "['column3']:dynamic, ['column4']:datetime, ['column5']:real, ['column6']:real)\n\n"
            ".create table ['test_table'] ingestion json mapping 'test_table_mapping' '["
            "{\"column\":\"column1\", \"Properties\":{\"Path\":\"$[\\'column1\\']\"}},"
            "{\"column\":\"column2\", \"Properties\":{\"Path\":\"$[\\'column2\\']\"}},"
            "{\"column\":\"column3\", \"Properties\":{\"Path\":\"$[\\'column3\\']\"}},"
            "{\"column\":\"column4\", \"Properties\":{\"Path\":\"$[\\'column4\\']\"}},"
            "{\"column\":\"column5\", \"Properties\":{\"Path\":\"$[\\'column5\\']\"}},"
            "{\"column\":\"column6\", \"Properties\":{\"Path\":\"$[\\'column6\\']\"}}"
            "]'"
        )

        result = generate_kusto_commands(data, table_name)
        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()
