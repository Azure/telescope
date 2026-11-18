import unittest
from unittest.mock import patch, MagicMock, call
from pipelines.pipelines import (
    get_headers,
    get_pipeline_definition,
    get_scheduled_pipelines,
    disable_pipeline,
    should_disable_pipeline,
    main,
)


class TestPipelines(unittest.TestCase):
    def setUp(self):
        self.org = "org"
        self.project = "project"
        self.pat = "pat"
        self.headers = {"Authorization": "Basic pat"}

    def test_get_headers(self):
        headers = get_headers("pat")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], "Bearer pat")

    @patch("pipelines.pipelines.requests.get")
    def test_get_pipeline_definition(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1, "name": "test_pipeline"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_pipeline_definition("org", "project", 1, {"Authorization": "test"})
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "test_pipeline")
        mock_get.assert_called_once()

    @patch("pipelines.pipelines.requests.get")
    def test_get_scheduled_pipelines(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"id": 1, "sourceBranch": "refs/heads/main"}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_scheduled_pipelines("org", "project", {"Authorization": "test"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)
        mock_get.assert_called_once()

    @patch("pipelines.pipelines.requests.put")
    @patch("pipelines.pipelines.logger")
    def test_disable_pipeline(self, mock_logger, mock_put):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_put.return_value = mock_response

        # Test disabling a pipeline
        pipeline_def = {
            "id": 1,
            "name": "test_pipeline",
            "queueStatus": "enabled",
            "path": "/mock/path",
        }
        disable_pipeline(
            "org",
            "project",
            pipeline_def,
            {"Authorization": "test"},
            reason="Test reason",
        )

        # Verify the pipeline was marked as disabled
        self.assertEqual(pipeline_def["queueStatus"], "disabled")

        # Verify logging occurred
        mock_logger.info.assert_called_with(
            "Disabling pipeline: test_pipeline under /mock/path, reason: Test reason"
        )

        # Verify the API was called
        mock_put.assert_called_once_with(
            "https://dev.azure.com/org/project/_apis/build/definitions/1?api-version=7.1-preview.7",
            headers={"Authorization": "test"},
            json=pipeline_def,
            timeout=10,
        )

    @patch("pipelines.pipelines.get_scheduled_pipelines")
    @patch("pipelines.pipelines.get_pipeline_definition")
    @patch("pipelines.pipelines.disable_pipeline")
    @patch("pipelines.pipelines.should_disable_pipeline")
    @patch("pipelines.pipelines.logger")
    @patch("pipelines.pipelines.get_headers")
    def test_main_logic(
        self,
        mock_get_headers,
        mock_logger,
        mock_should_disable,
        mock_disable,
        mock_get_def,
        mock_get_sched,
    ):
        pipeline = {
            "sourceBranch": "refs/heads/feature-xyz",
            "definition": {"id": 10, "name": "P1", "path": "\\MyPipelines"},
            "_links": {"web": {"href": "http://example.com"}},
        }
        excluded_pipeline = {
            "sourceBranch": "refs/heads/feature-abc",
            "definition": {"id": 20, "name": "P2", "path": "\\MyPipelines"},
            "_links": {"web": {"href": "http://example.com"}},
        }

        pipeline_def = {
            "id": 10,
            "name": "P1",
            "path": "\\MyPipelines",
            "queueStatus": "enabled",
        }

        excluded_pipeline_def = {
            "id": 20,
            "name": "P2",
            "path": "\\MyPipelines",
            "queueStatus": "enabled",
        }

        mock_get_sched.return_value = [pipeline, excluded_pipeline]
        mock_get_def.side_effect = [pipeline_def, excluded_pipeline_def]

        # Set up the should_disable_pipeline mock to return appropriate values
        mock_should_disable.side_effect = [
            (
                True,
                "Pipeline is scheduled on non-main branch: refs/heads/feature-xyz",
            ),  # For first pipeline
            (False, "Pipeline is explicitly excluded"),  # For second pipeline
        ]

        mock_get_headers.return_value = {"Authorization": "Basic pat"}

        args = [
            "--org",
            self.org,
            "--project",
            self.project,
            "--pat",
            self.pat,
            "--exclude-pipelines",
            "20",
        ]
        with patch("sys.argv", ["main.py"] + args):
            with patch("pipelines.pipelines.logger", mock_logger):
                main()

        # Check the should_disable_pipeline was called correctly
        mock_should_disable.assert_has_calls(
            [
                call(
                    pipeline_def=pipeline_def,
                    source_branch="refs/heads/feature-xyz",
                    excluded_ids=[20],
                ),
                call(
                    pipeline_def=excluded_pipeline_def,
                    source_branch="refs/heads/feature-abc",
                    excluded_ids=[20],
                ),
            ]
        )

        # Verify the disable_pipeline was called with the right parameters
        expected_pipeline_def = pipeline_def.copy()
        expected_pipeline_def["comment"] = (
            "Disabled by script: Pipeline is scheduled on non-main branch: refs/heads/feature-xyz"
        )
        mock_disable.assert_called_once()
        call_args = mock_disable.call_args
        self.assertEqual(call_args[0][0], self.org)
        self.assertEqual(call_args[0][1], self.project)
        self.assertEqual(call_args[0][2]["id"], 10)
        self.assertEqual(
            call_args[0][2]["comment"],
            "Disabled by script: Pipeline is scheduled on non-main branch: refs/heads/feature-xyz",
        )

        # Verify other function calls
        mock_get_sched.assert_called_once_with(self.org, self.project, self.headers)

        # Verify the logging calls
        mock_logger.info.assert_any_call("Excluded pipeline IDs: [20]")

        # Test when the scheduled pipeline throws an exception
        mock_get_sched.side_effect = Exception("Api error")
        mock_logger.reset_mock()
        with patch("sys.argv", ["main.py"] + args):
            with self.assertRaises(SystemExit):
                main()
            mock_logger.error.assert_called_once_with("Failed: Api error")

        # Test when the disable pipeline throws an exception
        mock_logger.reset_mock()

        # Set up to trigger the disable failure
        mock_get_sched.side_effect = None
        mock_get_sched.return_value = [pipeline]

        pipeline_def = {
            "id": 10,
            "name": "P1",
            "path": "\\MyPipelines",
            "queueStatus": "enabled",
        }
        mock_get_def.side_effect = [pipeline_def]

        # Reset and set up the should_disable_pipeline mock
        mock_should_disable.reset_mock()
        mock_should_disable.side_effect = [(True, "Test reason")]

        mock_disable.reset_mock()
        mock_disable.side_effect = Exception("Api error")

        with patch("sys.argv", ["main.py"] + args):
            with self.assertRaises(SystemExit):
                main()
            mock_logger.error.assert_any_call(
                "Failed to disable pipeline 10: Api error"
            )

    @patch("pipelines.pipelines.logger")
    def test_should_disable_pipeline_excluded(self, mock_logger):
        """Test that excluded pipelines are properly detected."""
        pipeline_def = {"id": 123, "name": "Test Pipeline", "path": "\\MyPipelines"}

        excluded_ids = [123, 456]

        should_disable, reason = should_disable_pipeline(
            pipeline_def, "refs/heads/feature", excluded_ids
        )
        self.assertFalse(should_disable)
        self.assertEqual(reason, "Pipeline is explicitly excluded")
        mock_logger.warning.assert_called_once()

    def test_should_disable_pipeline_skip_resource_management(self):
        """Test that pipelines with SKIP_RESOURCE_MANAGEMENT=true are detected."""
        pipeline_def = {
            "id": 123,
            "name": "Test Pipeline",
            "path": "\\MyPipelines",
            "variables": {
                "SKIP_RESOURCE_MANAGEMENT": {"value": "true", "allowOverride": True}
            },
        }

        should_disable, reason = should_disable_pipeline(pipeline_def)
        self.assertTrue(should_disable)
        self.assertEqual(reason, "SKIP_RESOURCE_MANAGEMENT is set to true")

    def test_should_disable_pipeline_non_main_branch(self):
        """Test that pipelines on non-main branches are detected."""
        pipeline_def = {"id": 123, "name": "Test Pipeline", "path": "\\MyPipelines"}

        should_disable, reason = should_disable_pipeline(
            pipeline_def, "refs/heads/feature"
        )
        self.assertTrue(should_disable)
        self.assertEqual(
            reason, "Pipeline is scheduled on non-main branch: refs/heads/feature"
        )

    def test_should_not_disable_pipeline_main_branch_no_skip(self):
        """Test that pipelines on main branch without SKIP_RESOURCE_MANAGEMENT are not disabled."""
        pipeline_def = {
            "id": 123,
            "name": "Test Pipeline",
            "path": "\\MyPipelines",
            "variables": {
                "SKIP_RESOURCE_MANAGEMENT": {"value": "false", "allowOverride": True}
            },
        }

        should_disable, reason = should_disable_pipeline(
            pipeline_def, "refs/heads/main"
        )
        self.assertFalse(should_disable)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
