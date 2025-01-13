import os
import re
from pathlib import Path
import hcl2
import glob
import json
import subprocess
import yaml

import json
import re
from pathlib import Path

def replace_placeholders(content, values):
    """Replace placeholders in the template content with provided values."""
    for placeholder, value in values.items():
        value_str = json.dumps(value, indent=2) if isinstance(value, (dict, list)) else str(value)
        content = re.sub(rf'{{{{{re.escape(placeholder)}}}}}', value_str, content)
    return content

def process_template(template_path, output_path, values, script_dir):
    """Process a template, replace placeholders, and save the output."""
    try:
        template_path = script_dir / template_path
        with open(template_path, 'r') as file:
            template_content = file.read()

        updated_content = replace_placeholders(template_content, values)
        final_output_path = replace_placeholders(output_path, values)

        output_dir = Path(final_output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(final_output_path, 'w') as output_file:
            output_file.write(updated_content)

        print(f"Template '{template_path}' processed and saved as '{final_output_path}'.")

    except FileNotFoundError:
        print(f"Error: Template file '{template_path}' not found.")
    except Exception as e:
        print(f"Error processing template '{template_path}': {e}")

def generate_templates(templates, values):
    """Generate templates by processing all templates."""
    script_dir = Path(__file__).parent  # Get the directory where the script is located
    for template_path, output_path in templates.items():
        if output_path is not None:
            process_template(template_path, output_path, values, script_dir)
        else:
            print(f"Skipping template '{template_path}' with no output path.")

def get_user_input(config_file_path="modules/python/scaffolding/input_template.yml"):
    """Load configuration from a file and return the values."""
    try:
        with open(config_file_path, 'r') as config_file:
            config_data = yaml.safe_load(config_file)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"Error loading config file {config_file_path}: {e}")
        return {}
    
    tfvars_data_azure, tfvars_data_aws = load_terraform_tfvars_data()

    values = {
        'SCENARIO_TYPE': 'perf-eval' if config_data.get("scenario_type_choice") == '1' else 'issue-repro',
        'SCENARIO_NAME': config_data.get("scenario_name", ""),
        'ENGINE_NAME': config_data.get("engine_name", ""),
        'TOPOLOGY_NAME': config_data.get("topology_name", ""),
        'DELETION_DELAY': config_data.get("deletion_delay", "2h"),
        'OWNER': config_data.get("owner", "aks"),
        'CREDENTIAL_TYPE': config_data.get("credential_choice", '2'),
        'PIPELINE_NAME': config_data.get("pipeline_name", "new-pipeline"),
        'TOPOLOGY_DIRECTORY': 'steps/topology',
        'ENGINE_DIRECTORY': 'steps/engine',
    }

    # Set credential type based on choice
    values['CREDENTIAL_TYPE'] = 'managed_identity' if values['CREDENTIAL_TYPE'] == '1' else 'service_connection'

    # Load tfvars data
    tfvars_data_azure, tfvars_data_aws = load_terraform_tfvars_data()

    # Add network and cluster configurations
    values['AZURE_NETWORK_CONFIG_LIST'] = tfvars_data_azure['network_config_list']
    values['AWS_NETWORK_CONFIG_LIST'] = tfvars_data_aws['network_config_list']

    cluster_input = config_data.get("cluster_input", "1")
    if cluster_input in {'1', '2', '3'}:
        cluster_key = {
            '1': 'basic_cluster_list',
            '2': 'nap_cluster_list',
            '3': 'cas_cluster_list'
        }.get(cluster_input)
        values['AZURE_CLUSTER_CONFIG_LIST'] = tfvars_data_azure[cluster_key]
        values['AWS_CLUSTER_CONFIG_LIST'] = tfvars_data_aws[cluster_key]
    else:
        print("Invalid choice for cluster configuration.")

    return values

def load_terraform_tfvars_data():
    """Load and parse all terraform .tfvars files."""
    tfvars_data_aws, tfvars_data_azure = {}, {}

    for file_path in get_tfvars_files('modules/python/scaffolding/templates/terraform'):
        tfvars_data = load_tfvars(file_path)
        if 'aws' in file_path:
            tfvars_data_aws.update(tfvars_data)
        elif 'azure' in file_path:
            tfvars_data_azure.update(tfvars_data)

    return format_tfvars_data(tfvars_data_azure), format_tfvars_data(tfvars_data_aws)

def get_tfvars_files(directory):
  return [file for file in glob.glob(f"{directory}/**/*.tfvars", recursive=True) if not file.endswith('-main-template.tfvars')]

def load_tfvars(file_path):
    """Load and parse the tfvars file."""
    with open(file_path, 'r') as file:
        return hcl2.load(file)

def format_tfvars_data(tfvars_data):
    """Recursively format the tfvars data into Terraform-friendly format."""
    for key, value in tfvars_data.items():
        tfvars_data[key] = json_to_terraform(value) if isinstance(value, (dict, list)) else value
    return tfvars_data

def json_to_terraform(data):
    """Convert JSON data to Terraform configuration syntax."""
    if isinstance(data, dict):
        return "{\n" + "\n".join([f"{key} = {json_to_terraform(value)}" for key, value in data.items()]) + "\n}"
    elif isinstance(data, list):
        return "[\n" + ",\n".join([json_to_terraform(item) for item in data]) + "\n]"
    elif isinstance(data, str):
        return f'"{data}"'
    elif isinstance(data, bool):
        return "true" if data else "false"
    else:
        return str(data)

def generate_templates_from_config():
    """Generate templates based on user input."""
    # Define the templates and their corresponding output paths
    templates = {
        'templates/yml/pipeline_template.yml': os.path.join('pipelines','{{SCENARIO_TYPE}}','{{PIPELINE_NAME}}.yml'),
        'templates/yml/collect-topology-template.yml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'collect-{{ENGINE_NAME}}.yml'),
        'templates/yml/execute-topology-template.yml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'execute-{{ENGINE_NAME}}.yml'),
        'templates/yml/validate-topology-template.yml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'validate-resources.yml'),
        'templates/yml/execute-engine-template.yml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'execute.yml'),
        'templates/yml/validate-engine-template.yml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'validate.yml'),
        'templates/yml/collect-engine-template.yml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'collect.yml'),
        'templates/terraform/azure-main-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'azure.tfvars'),
        'templates/terraform/aws-main-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'aws.tfvars'),
        'templates/terraform/tests/aws.json': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-test-inputs' ,'aws.json'),
        'templates/terraform/tests/azure.json': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-test-inputs' ,'azure.json')
    }
  
    values = get_user_input()
    generate_templates(templates, values)

    subprocess.run(["terraform", "fmt"], cwd=os.path.join('scenarios', values['SCENARIO_TYPE'], values['SCENARIO_NAME'], "terraform-inputs"), capture_output=True, text=True)

if __name__ == "__main__":
    generate_templates_from_config()
