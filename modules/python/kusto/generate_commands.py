import json
import sys
import base64

from dateutil.parser import isoparse

def infer_type(value):
    # Check if it's a boolean
    if isinstance(value, str) and value.lower() in ['true', 'false']:
        return "bool"

    # Check if it's an integer
    try:
        int(value)
        return "real"
    except (ValueError, TypeError):
        pass

    # Check if it's a float
    try:
        float(value)
        return "real"
    except (ValueError, TypeError):
        pass

    # Check if it's dynamic
    if isinstance(value, (dict, list)):
        return "dynamic"

    # Attempt to load the string as JSON
    try:
        parsed_json = json.loads(str(value))
        if isinstance(parsed_json, (dict, list)):
            return "dynamic"
    except (json.JSONDecodeError, TypeError):
        pass

    # Check if it's a datetime
    try:
        isoparse(value)
        return "datetime"
    except ValueError:
        pass

    # If none of the above, take it as string
    return "string"

def generate_kusto_commands(data, table_name):
    # Create table command
    table_command = f".create table ['{table_name}'] ("

    for key, value in data.items():
        infered_type = infer_type(value)
        table_command += f"['{key}']:{infered_type}, "

    table_command = table_command.rstrip(", ") + ")"

    # Create table ingestion json mapping command
    mapping_command = f".create table ['{table_name}'] ingestion json mapping '{table_name}_mapping' '["
    for key in data.keys():
        mapping_command += f"{{\"column\":\"{key}\", \"Properties\":{{\"Path\":\"$[\\'{key}\\']\"}}}},"
    mapping_command = mapping_command.rstrip(", ") + "]'"

    kusto_commands = f"{table_command}\n\n{mapping_command}"
    return kusto_commands

def main():
    table_name = sys.argv[1]
    schema_path = sys.argv[2]
    with open(schema_path, 'r', encoding='utf-8') as schema_file:
        json_data = schema_file.readline()
    json_object = json.loads(json_data)
    kusto_commands = base64.b64encode(generate_kusto_commands(json_object, table_name).encode("utf-8"))
    print(kusto_commands.decode("utf-8"))

if __name__ == "__main__":
    main()