import json

def generate_kusto_table_creation(schema_path, table_name):
    with open(schema_path, 'r') as schema_file:
        schema_data = json.load(schema_file)

    column_definitions = [
        f"['{col['ColumnName']}']: {col['DataType']}"
        for col in schema_data
    ]

    table_creation_command = f".create table ['{table_name}'] ({', '.join(column_definitions)})"

    return table_creation_command

def generate_kusto_table_mapping(schema_path, table_name):
    with open(schema_path, 'r') as schema_file:
        schema_data = json.load(schema_file)

    column_mappings = [
        f'{{"column": "{col["ColumnName"]}", "Properties": {{"Path": "$[\'{col["ColumnName"]}\']"}}}}'
        for col in schema_data
    ]

    mapping_command = f".create table ['{table_name}'] ingestion json mapping '{table_name}_mapping' {column_mappings}"

    return mapping_command

def write_to_file(file_path, content):
    with open(file_path, 'a') as file:
        file.write(content)

def main():
    schema_path = sys.argv[1]
    table_name = sys.argv[2]

    kusto_table_creation_command = generate_kusto_table_creation(schema_path, table_name)
    kusto_table_mapping_command = generate_kusto_table_mapping(schema_path, table_name)
    output_file_path = 'table_creation_script.txt' 
    
    write_to_file(output_file_path, "// Create table command\n")
    write_to_file(output_file_path, kusto_table_creation_command)

    write_to_file(output_file_path, "\n\n// Create mapping command\n")
    write_to_file(output_file_path, kusto_table_mapping_command)

if __name__ == "__main__":
    main()
