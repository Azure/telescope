import os
import re
from pathlib import Path
import hcl2
import glob
import json
import subprocess
import yaml

class TemplateGenerator:
    def __init__(self, templates, values):
        self.templates = templates
        self.values = values
        self.script_dir = Path(__file__).parent  # Get the directory where the script is located

    def replace_placeholders(self, content, values):
      """Replace placeholders in the template content with provided values."""
      for placeholder, value in values.items():
          # Check if the value is an object (list or dict)
          if isinstance(value, (dict, list)):
              # Convert the object to a JSON string, formatted for readability
              value_str = json.dumps(value, indent=2)
          else:
              # Otherwise, treat it as a simple string
              value_str = str(value)

          # Replace the placeholder with the formatted value
          content = re.sub(r'{{' + re.escape(placeholder) + r'}}', value_str, content)
      return content

    def process_template(self, template_path, output_path):
        """Load a template, replace placeholders, and save it to the output path."""
        try:
            # Create an absolute path for the template file based on the script's directory
            template_path = self.script_dir / template_path

            with open(template_path, 'r') as file:
                template_content = file.read()

            # Replace placeholders in template content
            updated_content = self.replace_placeholders(template_content, self.values)

            # Replace the output path placeholders with actual values
            final_output_path = self.replace_placeholders(output_path, self.values)

            # Ensure output directory exists
            output_dir = Path(final_output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save the updated content to the output path
            with open(final_output_path, 'w') as output_file:
                output_file.write(updated_content)

            print(f"Template '{template_path}' successfully processed and saved as '{final_output_path}'.")

        except FileNotFoundError:
            print(f"Error: Template file '{template_path}' not found.")
        except Exception as e:
            print(f"Error processing template '{template_path}': {e}")

    def generate_templates(self):
        """Process all templates and generate output files."""
        for template_path, output_path in self.templates.items():
            if output_path is None:
                print(f"Skipping template '{template_path}' because the output path is None.")
                continue
            self.process_template(template_path, output_path)

def get_user_input(config_file_path="modules/python/scaffolding/input_template.yml"):
    """Load configuration from a file and return the values."""
    values = {}

    # Load the config file (the user should fill in or edit this file)
    try:
        with open(config_file_path, 'r') as config_file:
            config_data = yaml.safe_load(config_file)  # Parse the YAML file
    except FileNotFoundError:
        print(f"Error: The file {config_file_path} was not found.")
        return {}
    except yaml.YAMLError as e:
        print(f"Error: The file {config_file_path} is not a valid YAML. {e}")
        return {}

    # Load terraform tfvars data (replace with your actual function)
    tfvars_data_azure, tfvars_data_aws = load_terraform_tfvars_data()

    # Set values from the configuration file
    values['SCENARIO_TYPE'] = 'perf-eval' if config_data.get("scenario_type_choice") == '1' else 'issue-repro'
    values['SCENARIO_NAME'] = config_data.get("scenario_name", "")
    values['ENGINE_NAME'] = config_data.get("engine_name", "")
    values['TOPOLOGY_NAME'] = config_data.get("topology_name", "")
    values['DELETION_DELAY'] = config_data.get("deletion_delay", "2h")
    values['OWNER'] = config_data.get("owner", "aks")
    
    # Credential Type
    if config_data.get("credential_choice") == '1':
        values['CREDENTIAL_TYPE'] = 'managed_identity'
    elif config_data.get("credential_choice") == '2':
        values['CREDENTIAL_TYPE'] = 'service_connection'
    else:
        print("Invalid choice, using 'service_connection' as default.")
        values['CREDENTIAL_TYPE'] = 'service_connection'

    values['PIPELINE_NAME'] = config_data.get("pipeline_name", "new-pipeline")

    # Default directories (no prompt needed)
    values['TOPOLOGY_DIRECTORY'] = 'steps/topology'
    values['ENGINE_DIRECTORY'] = 'steps/engine'

    # Add network configuration (based on values from template or user inputs)
    values['AZURE_NETWORK_CONFIG_LIST'] = tfvars_data_azure['network_config_list']
    values['AWS_NETWORK_CONFIG_LIST'] = tfvars_data_aws['network_config_list']

    # Cluster Configuration
    cluster_input = config_data.get("cluster_input", "1")
    if cluster_input == '1':
        values['AZURE_CLUSTER_CONFIG_LIST'] = tfvars_data_azure['basic_cluster_list']
        values['AWS_CLUSTER_CONFIG_LIST'] = tfvars_data_aws['basic_cluster_list']
    elif cluster_input == '2':
        values['AZURE_CLUSTER_CONFIG_LIST'] = tfvars_data_azure['nap_cluster_list']
        values['AWS_CLUSTER_CONFIG_LIST'] = tfvars_data_aws['nap_cluster_list']
    elif cluster_input == '3':
        values['AZURE_CLUSTER_CONFIG_LIST'] = tfvars_data_azure['cas_cluster_list']
        values['AWS_CLUSTER_CONFIG_LIST'] = tfvars_data_aws['cas_cluster_list']
    else:
        print("Invalid choice, Cluster configuration will not be added.")
        values['AZURE_CLUSTER_CONFIG_LIST'] = []
        values['AWS_CLUSTER_CONFIG_LIST'] = []

    return values

def load_terraform_tfvars_data():
    # Load all tfvars files
    terraform_template_files = get_tfvars_files('modules/python/scaffolding/templates/terraform')
    tfvars_data_aws = {}
    tfvars_data_azure = {}

    for file_path in terraform_template_files:
      if 'aws' in file_path:
        tfvars_data_aws.update(load_tfvars(file_path))
      elif 'azure' in file_path:
        tfvars_data_azure.update(load_tfvars(file_path))

    for key, value in tfvars_data_azure.items():
      if isinstance(value, (dict, list)):
        tfvars_data_azure[key] = json_to_terraform(value)
      else:
        tfvars_data_azure[key] = value

    for key, value in tfvars_data_aws.items():
      if isinstance(value, (dict, list)):
        tfvars_data_aws[key] = json_to_terraform(value)
      else:
        tfvars_data_aws[key] = value
    
    return tfvars_data_azure, tfvars_data_aws

def get_tfvars_files(directory):
  return [file for file in glob.glob(f"{directory}/**/*.tfvars", recursive=True) if not file.endswith('-main-template.tfvars')]

def load_tfvars(file_path):
    """Load and parse the tfvars file."""
    with open(file_path, 'r') as file:
        return hcl2.load(file)

import json

def json_to_terraform(data):
    """Recursively convert the JSON to Terraform format (key = value)."""
    
    # If the data is a dictionary, process each key-value pair recursively
    if isinstance(data, dict):
        result = []
        for key, value in data.items():
            formatted_key = key  # No quotes around keys in Terraform
            formatted_value = json_to_terraform(value)  # Recursively process value
            # Add the key-value pair to the result as key = value
            result.append(f"{formatted_key} = {formatted_value}")
        return "{\n" + "\n".join(result) + "\n}"  # Return as a block-like structure
    
    # If the data is a list, process each item recursively
    elif isinstance(data, list):
        result = []
        for item in data:
            result.append(json_to_terraform(item))  # Process each item
        return "[\n" + ",\n".join(result) + "\n]"  # Return as a list block
    
    # Otherwise, return the value as a string, handling booleans, strings, and numbers
    elif isinstance(data, str):
        return f'"{data}"'  # Quote strings for Terraform compatibility
    elif isinstance(data, bool):
        return "true" if data else "false"
    else:
        return str(data)  # Convert numbers directly




def generate_templates_from_config():
    """Generate templates based on user input."""
    # Define the templates and their corresponding output paths
    templates = {
        'templates/yaml/pipeline_template.yaml': os.path.join('pipelines','{{SCENARIO_TYPE}}','{{PIPELINE_NAME}}.yml'),
        'templates/yaml/collect-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'collect-{{TOPOLOGY_NAME}}.yaml'),
        'templates/yaml/execute-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'execute-{{TOPOLOGY_NAME}}.yaml'),
        'templates/yaml/validate-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'validate-{{TOPOLOGY_NAME}}.yaml'),
        'templates/yaml/execute-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'execute.yaml'),
        'templates/yaml/validate-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'validate.yaml'),
        'templates/yaml/collect-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'collect.yaml'),
        'templates/terraform/azure-main-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'azure.tfvars'),
        'templates/terraform/aws-main-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'aws.tfvars'),
        'templates/terraform/tests/aws.json': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-test-inputs' ,'aws.json'),
        'templates/terraform/tests/azure.json': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-test-inputs' ,'azure.json')
    }
  
    # Get user input
    values = get_user_input()

    # Initialize TemplateGenerator with the templates and values
    generator = TemplateGenerator(templates, values)
    generator.generate_templates()
    command = ["terraform", "fmt"]
    directory = os.path.join('scenarios', values['SCENARIO_TYPE'], values['SCENARIO_NAME'], "terraform-inputs")
    subprocess.run(command, cwd=directory, capture_output=True, text=True)

if __name__ == "__main__":
    generate_templates_from_config()
