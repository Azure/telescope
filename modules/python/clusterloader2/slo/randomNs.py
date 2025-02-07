import random

namespaces = ["slo-1", "slo-2"]
namespace = {{.Namespace}}
randomNamespace = ""

while randomNamespace == "":
    randomIndex = random.randint(0, len(namespaces) - 1)
    if namespaces[randomIndex] != namespace:
        randomNamespace = namespaces[randomIndex]
        break

print(f"Selected random namespace: {randomNamespace}")