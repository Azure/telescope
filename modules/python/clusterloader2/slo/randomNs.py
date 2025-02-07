import random

namespaces = ["slo-1", "slo-2"]
namespace = "{{.Namespace}}"
randomNamespace = ""

while randomNamespace == "":
    randomIndex = random.randint(0, len(namespaces) - 1)
    if namespaces[randomIndex] != namespace:
        randomNamespace = namespaces[randomIndex]
        break

def get_random_namespace():
    return randomNamespace

# Write the random namespace to a file
with open("random_namespace.txt", "w") as file:
    file.write(get_random_namespace())