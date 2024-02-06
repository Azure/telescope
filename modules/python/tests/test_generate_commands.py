import unittest
from datetime import datetime
from kusto.generate_commands import infer_type, generate_kusto_commands

class TestInferType(unittest.TestCase):
    def test_infer_bool(self):
        self.assertEqual(infer_type('true'), 'bool')
        self.assertEqual(infer_type('false'), 'bool')

    def test_infer_long(self):
        self.assertEqual(infer_type('123'), 'long')

    def test_infer_dynamic(self):
        self.assertEqual(infer_type('{"key": "value"}'), 'dynamic')
        self.assertEqual(infer_type('[1, 2, 3]'), 'dynamic')

    def test_infer_datetime(self):
        self.assertEqual(infer_type('2022-01-01T12:00:00Z'), 'datetime')

    def test_infer_string(self):
        self.assertEqual(infer_type('hello'), 'string')

class TestGenerateKustoCommands(unittest.TestCase):
    def test_generate_kusto_commands(self):
        data = {
            'column1': 'value1',
            'column2': '123',
            'column3': '{"key": "value"}',
            'column4': '2022-01-01T12:00:00Z',
        }
        table_name = 'test_table'
        expected_result = (
            ".create table ['test_table'] (['column1']:string, ['column2']:long, "
            "['column3']:dynamic, ['column4']:datetime)\n\n"
            ".create table ['test_table'] ingestion json mapping 'test_table_mapping' '["
            "{\"column\":\"column1\", \"Properties\":{\"Path\":\"$[\\'column1\\']\"}},"
            "{\"column\":\"column2\", \"Properties\":{\"Path\":\"$[\\'column2\\']\"}},"
            "{\"column\":\"column3\", \"Properties\":{\"Path\":\"$[\\'column3\\']\"}},"
            "{\"column\":\"column4\", \"Properties\":{\"Path\":\"$[\\'column4\\']\"}}"
            "]'"
        )

        result = generate_kusto_commands(data, table_name)
        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()
