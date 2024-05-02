import sys
import json
from jsonschema import  Draft7Validator

def validate_json_schema(json_file, schema_file):
    # Load JSON file
    with open(json_file, 'r') as f:
        json_data = json.load(f)

    # Load JSON schema
    with open(schema_file, 'r') as f:
        schema = json.load(f)

    # Validate JSON against schema
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(json_data))

    if not errors:
        print("JSON is valid against the schema.")
    else:
        print("JSON is not valid against the schema. Errors:")
        for error in errors:
            print(error.message)

if __name__ == "__main__":
    # Check if correct number of command-line arguments are provided
    if len(sys.argv) != 3:
        print("Usage: python validate_json.py <schema_file> <json_file>")
        sys.exit(1)

    # Get schema file path and JSON file path from command-line arguments
    schema_file_path = sys.argv[1]
    json_file_path = sys.argv[2]

    # Validate JSON against schema
    validate_json_schema(json_file_path, schema_file_path)
