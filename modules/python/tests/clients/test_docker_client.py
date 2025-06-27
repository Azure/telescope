#!/usr/bin/env python3
"""
Unit tests for DockerClient class
"""

import unittest
from unittest import mock
from clients.docker_client import DockerClient

class TestDockerClient(unittest.TestCase):
    """
    Unit tests for the DockerClient class, verifying its integration with the docker SDK.
    Test Cases:
    - Ensures DockerClient initializes by calling docker.from_env.
    - Verifies that run_container calls containers.run with the correct arguments.
    - Checks that run_container returns the result from containers.run.
    Mocks are used to isolate DockerClient from the actual Docker environment.
    """
    def setUp(self):
        """
        Set up the test environment by patching the Docker client's from_env method.
        This method uses unittest.mock to patch 'clients.docker_client.docker.from_env',
        ensuring that any calls to this method during tests are intercepted by a mock.
        The patch is automatically stopped after the test using addCleanup.
        Initializes a DockerClient instance for use in tests.
        """
        patcher = mock.patch("clients.docker_client.docker.from_env")
        self.addCleanup(patcher.stop)
        self.mock_from_env = patcher.start()
        self.docker_client = DockerClient()

    def test_init_calls_docker_from_env(self):
        """
        Test that DockerClient.__init__ calls docker.from_env and sets the client attribute.
        """
        # Verify that docker.from_env was called once during initialization
        self.mock_from_env.assert_called_once()
        # Verify that the DockerClient's client attribute is set to the mock
        self.assertIs(self.docker_client.client, self.mock_from_env.return_value)

    def test_run_container_calls_containers_run_with_correct_args(self):
        """
        Test that the `run_container` method calls `containers.run` on the Docker client
        with the correct arguments: image, command, volumes, and detach.

        This test mocks the Docker client, sets up sample arguments, executes the method,
        and verifies that `containers.run` is called once with the expected parameters.
        """
        # Setup
        mock_client = self.mock_from_env.return_value
        image = "busybox"
        command = "echo hello"
        volumes = {"host_path": {"bind": "/container_path", "mode": "rw"}}
        detach = True

        # Execute
        self.docker_client.run_container(image, command, volumes, detach)

        # Verify
        mock_client.containers.run.assert_called_once_with(
            image, command, volumes=volumes, detach=detach
        )

    def test_run_container_returns_result(self):
        """
        Test that the `run_container` method returns the container object as expected.

        This test mocks the Docker client and its `containers.run` method to ensure that
        when `run_container` is called with specific arguments, it returns the mocked container
        instance. Verifies correct interaction with the Docker client.
        """
        # Setup
        mock_container = mock.Mock()
        mock_client = self.mock_from_env.return_value
        mock_client.containers.run.return_value = mock_container

        # Execute
        result = self.docker_client.run_container("alpine", "ls", {}, False)

        # Verify
        self.assertIs(result, mock_container)
