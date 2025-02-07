import os

# Read the random namespace from the file
with open("random_namespace.txt", "r") as file:
    random_namespace = file.read().strip()

# Read the template file
with open("cnp_template.yaml", "r") as file:
    template = file.read()

# Replace the placeholder with the random namespace
template = template.replace("{{$randomNamespace}}", random_namespace)

# Write the processed template back to the same file
with open("cnp_template.yaml", "w") as file:
    file.write(template)

print("Processed template written to cnp_template.yaml")