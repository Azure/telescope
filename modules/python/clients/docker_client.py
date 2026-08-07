import docker


class DockerClient:
    def __init__(self):
        self.client = docker.from_env()

    def run_container(self, image, command, volumes, detach, name=None):
        options = {"volumes": volumes, "detach": detach}
        if name:
            options["name"] = name
        return self.client.containers.run(image, command, **options)
