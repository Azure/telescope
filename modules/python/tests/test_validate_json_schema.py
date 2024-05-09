import unittest
from unittest.mock import patch, mock_open
from io import StringIO
import json
from terraform.validate_json_schema import validate_json_schema

class TestValidateJsonSchema(unittest.TestCase):

    schema = {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "run_id": {"type": "string"},
                "region": {"type": "string"},
                "accelerated_networking": {"type": "boolean"}
            },
            "required": ["owner", "run_id", "region"]
        }
    def test_validate_json_schema_valid(self):
        # Mock a valid JSON data
        json_data = {
            "owner": "John Doe",
            "run_id": "123456",
            "region": "us-west",
            "accelerated_networking": True
        }

        # Mock file operations
        with patch("builtins.open", mock_open(read_data='{}')) as mock_file:
            mock_file.side_effect = [StringIO(json.dumps(self.schema)), StringIO(json.dumps(json_data))]
            result = validate_json_schema('schema.json', 'data.json')

        # Assert that the validation succeeded
        self.assertTrue(result['isValid'])
        self.assertIsNone(result['errors'])

    def test_validate_json_schema_invalid(self):
        # Mock an invalid JSON data (missing "region")
        json_data_invalid  = {
            "owner": "John Doe",
            "run_id": "123456"
        }

        # Mock file operations
        with patch("builtins.open", mock_open(read_data='{}')) as mock_file:
            mock_file.side_effect = [StringIO(json.dumps(self.schema)), StringIO(json.dumps(json_data_invalid ))]
            result = validate_json_schema('schema.json', 'data.json')


        # Assert that the validation failed
        self.assertFalse(result['isValid'])
        self.assertIsNotNone(result['errors'])
        self.assertIn("'region' is a required property", result['errors'])

if __name__ == '__main__':
    unittest.main()
