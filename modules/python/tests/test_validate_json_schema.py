import unittest
import json
from unittest.mock import patch, mock_open
from  terraform.validate_json_schema import validate_json_schema

class TestValidateJson(unittest.TestCase):
    def test_valid_json(self):
        # Mock the schema and JSON data
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "number"}
            },
            "required": ["name", "age"]
        }
        json_data = {"name": "John", "age": 30}

        # Mock the open function to return the schema and JSON data
        with patch("builtins.open", mock_open(read_data=json.dumps(schema))), \
             patch("json.load", return_value=json_data):
            with patch("sys.argv", ["validate_json.py", "schema.json", "data.json"]):
                # Call the validate_json function
                with patch("jsonschema.Draft7Validator.iter_errors", return_value=[]):
                    validate_json_schema("data.json", "schema.json")

    def test_invalid_json(self):
        # Mock the schema and JSON data
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "number"}
            },
            "required": ["name", "age"]
        }
        json_data = {"name": "John"}  # Missing "age"

        # Mock the open function to return the schema and JSON data
        with patch("builtins.open", mock_open(read_data=json.dumps(schema))), \
             patch("json.load", return_value=json_data):
            with patch("sys.argv", ["validate_json.py", "schema.json", "data.json"]):
                # Call the validate_json function
                with patch("jsonschema.Draft7Validator.iter_errors", return_value=[Exception("Error 1"), Exception("Error 2")]):
                    validate_json_schema("data.json", "schema.json")

if __name__ == "__main__":
    unittest.main()
