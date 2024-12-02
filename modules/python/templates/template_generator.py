import os
import re

# Define the templates and their corresponding output paths
templates = {
    'config/pipeline_template.yaml': os.getenv('PIPELINE_NAME'),
    'config/collect-topology-template.yaml': os.path.join(os.getenv('TOPOLOGY_DIRECTORY', 'steps/topology'), os.getenv('TOPOLOGY_NAME'), f'collect-{os.getenv("TOPOLOGY_NAME")}.yaml'),
    'config/execute-topology-template.yaml': os.path.join(os.getenv('TOPOLOGY_DIRECTORY', 'steps/topology'), os.getenv('TOPOLOGY_NAME'), f'execute-{os.getenv("TOPOLOGY_NAME")}.yaml'),
    'config/validate-topology-template.yaml': os.path.join(os.getenv('TOPOLOGY_DIRECTORY', 'steps/topology'), os.getenv('TOPOLOGY_NAME'), f'validate-{os.getenv("TOPOLOGY_NAME")}.yaml'),
    'config/execute-engine-template.yaml': os.path.join(os.getenv('ENGINE_DIRECTORY', 'steps/engine'), os.getenv('ENGINE_NAME'),'execute.yaml'),
    'config/validate-engine-template.yaml': os.path.join(os.getenv('ENGINE_DIRECTORY', 'steps/engine'), os.getenv('ENGINE_NAME'), 'validate.yaml'),
    'config/collect-engine-template.yaml': os.path.join(os.getenv('ENGINE_DIRECTORY', 'steps/engine'), os.getenv('ENGINE_NAME'), 'collect.yaml'),
}

# Define the values to replace using environment variables
values = {
    'SCENARIO_TYPE': os.getenv('SCENARIO_TYPE'),
    'SCENARIO_NAME': os.getenv('SCENARIO_NAME'),
    'ENGINE_NAME': os.getenv('ENGINE_NAME'),
    'TOPOLOGY_NAME': os.getenv('TOPOLOGY_NAME'),
    'CREDENTIAL_TYPE': os.getenv('CREDENTIAL_TYPE'),
}

# Function to replace placeholders in a template
def replace_placeholders(template, values):
    for placeholder, value in values.items():
        template = re.sub(r'{{' + re.escape(placeholder) + r'}}', value, template)
    return template

# Process each template
for template_path, output_path in templates.items():
    if output_path is None:
        print(f"Skipping template '{template_path}' because the output path is None.")
        continue

    # Load the template
    with open(template_path, 'r') as file:
        template = file.read()

    # Replace the placeholders with actual values
    updated_template = replace_placeholders(template, values)

    # Update the output path with the actual values
    output_path = replace_placeholders(output_path, values)

    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Save the updated template to the specified file
    with open(output_path, 'w') as file:
        file.write(updated_template)

    print(f"Template '{template_path}' updated and saved as '{output_path}'.")
