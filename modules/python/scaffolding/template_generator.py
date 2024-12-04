import os
import re
from pathlib import Path

class TemplateGenerator:
    def __init__(self, templates, values):
        self.templates = templates
        self.values = values
        self.script_dir = Path(__file__).parent  # Get the directory where the script is located

    def replace_placeholders(self, content, values):
        """Replace placeholders in the template content with provided values."""
        for placeholder, value in values.items():
            content = re.sub(r'{{' + re.escape(placeholder) + r'}}', value, content)
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


def get_user_input():
    """Prompt the user for input values."""
    values = {}
    print("Please enter the following values:")
    print("Note: The values will be used to generate the templates.")
    print("Select Scenario Type:")
    print("1. Performance Evaluation")
    print("2. Issue Reproduction")
    scenario_type_choice = input("Enter the number for Scenario Type (1 or 2): ")
    if scenario_type_choice == '1':
        values['SCENARIO_TYPE'] = 'perf-eval'
    elif scenario_type_choice == '2':
        values['SCENARIO_TYPE'] = 'issue-repro'
    values['SCENARIO_NAME'] = input("Enter Scenario Name: ")
    values['ENGINE_NAME'] = input("Enter Engine Name: ")
    values['TOPOLOGY_NAME'] = input("Enter Topology Name: ")
    values['DELETION_DELAY'] = input("Enter Deletion time (e.g., 2h): ") or "2h"
    values['OWNER'] = input("Enter Owner: ") or "aks"

    # Ask for CREDENTIAL_TYPE with options
    print("Select Credential Type:")
    print("1. Managed Identity")
    print("2. Service Connection")
    credential_choice = input("Enter the number for Credential Type (1 or 2): ")

    if credential_choice == '1':
        values['CREDENTIAL_TYPE'] = 'managed_identity'
    elif credential_choice == '2':
        values['CREDENTIAL_TYPE'] = 'service_connection'
    else:
        print("Invalid choice, using 'service_connection' as default.")
        values['CREDENTIAL_TYPE'] = 'service_connection'

    values['PIPELINE_NAME'] = input("Enter Pipeline Name: ")
    print("\nSelect the resources you want to create in this test scenario:")

    # List available resources with numbers
    available_resources = [
        "Kubernetes Cluster (Basic)",
        "Kubernetes Cluster (With Karpenter)",
        "Kubernetes Cluster (With Cluster Autoscaler)"
    ]
    
    for index, resource in enumerate(available_resources, 1):
        print(f"{index}. {resource}")

    # Let the user select resources by entering numbers
    selected_resources_input = input("Please select the resources you want to create in this test scenario (comma-separated): ")
    selected_resource_indexes = [int(i.strip()) for i in selected_resources_input.split(",")]

    # Map selected numbers to resource names
    selected_resources = [available_resources[i - 1] for i in selected_resource_indexes if 1 <= i <= len(available_resources)]
    values['SELECTED_RESOURCES'] = selected_resources

    # Default directories (no prompt needed)
    values['TOPOLOGY_DIRECTORY'] = 'steps/topology'
    values['ENGINE_DIRECTORY'] = 'steps/engine'


    return values

def generate_templates_from_config():
    """Generate templates based on user input."""
    # Define the templates and their corresponding output paths
    templates = {
        'config/pipeline_template.yaml': os.path.join('pipelines','{{SCENARIO_TYPE}}','{{PIPELINE_NAME}}.yml'),
        'config/collect-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'collect-{{TOPOLOGY_NAME}}.yaml'),
        'config/execute-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'execute-{{TOPOLOGY_NAME}}.yaml'),
        'config/validate-topology-template.yaml': os.path.join('{{TOPOLOGY_DIRECTORY}}', '{{TOPOLOGY_NAME}}', 'validate-{{TOPOLOGY_NAME}}.yaml'),
        'config/execute-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'execute.yaml'),
        'config/validate-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'validate.yaml'),
        'config/collect-engine-template.yaml': os.path.join('{{ENGINE_DIRECTORY}}', '{{ENGINE_NAME}}', 'collect.yaml'),
        'config/azure-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'azure.tfvars'),
        'config/aws-template.tfvars': os.path.join('scenarios', '{{SCENARIO_TYPE}}','{{SCENARIO_NAME}}', 'terraform-inputs' ,'aws.tfvars'),
    }

    # Get user input
    values = get_user_input()

    # Initialize TemplateGenerator with the templates and values
    generator = TemplateGenerator(templates, values)
    generator.generate_templates()

if __name__ == "__main__":
    generate_templates_from_config()
