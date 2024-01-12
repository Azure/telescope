import json
from datetime import datetime
import sys
def infer_type(value):
    # Check if it's a boolean
    if value.lower() in ['true', 'false']:
        return "bool"
    # Check if it's an number
    try:
        int(value)
        return "long"
    except ValueError:
        pass
    # Check if it's dynamic
    try:
        # Attempt to load the string as JSON
        parsed_json = json.loads(value)
        # Check if the parsed JSON is a dictionary or a list
        if isinstance(parsed_json, (dict, list)):
            return "dynamic"        
        return type(parsed_json) == dict and dict or list
    except json.JSONDecodeError:
        pass
    # Check if it's a datetime
    try:
        datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
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

    return table_command, mapping_command

def write_to_file(file_path, *commands):
    with open(file_path, 'w') as file:
        for command in commands:
            file.write(f"////////////////////////////////////////////////////////////\n{command}\n\n")
    
if __name__ == "__main__":
    table_name = sys.argv[1]
    schema_path = sys.argv[2]
    with open(schema_path, 'r') as schema_file:             
        json_data = schema_file.readline()       
    json_object = json.loads(json_data)
    table_command, mapping_command = generate_kusto_commands(json_object, table_name)
    print(table_command,mapping_command)
       
