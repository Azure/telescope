import docker
import docker.errors

class DockerClient:
    def __init__(self):
        self.client = docker.from_env()

    def run_container(self, image, command, volumes, detach):
        return self.client.containers.run(image, command, volumes=volumes, detach=detach)
    