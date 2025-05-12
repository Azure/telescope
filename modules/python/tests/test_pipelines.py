import unittest
from unittest.mock import patch, MagicMock, call
from pipelines.pipelines import get_headers, get_pipeline_definition, get_scheduled_pipelines, disable_pipeline, main

class TestPipelines(unittest.TestCase):

    def test_get_headers(self):
        headers = get_headers("pat")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], "Basic pat")

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
        mock_response.json.return_value = {"value": [{"id": 1, "sourceBranch": "refs/heads/main"}]}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_scheduled_pipelines("org", "project", {"Authorization": "test"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)
        mock_get.assert_called_once()

    @patch("pipelines.pipelines.requests.put")
    def test_disable_pipeline(self, mock_put):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_put.return_value = mock_response

        pipeline_def = {"id": 1, "name": "test_pipeline", "queueStatus": "enabled", "path": "/mock/path"}
        disable_pipeline("org", "project", pipeline_def, {"Authorization": "test"})
        self.assertEqual(pipeline_def["queueStatus"], "disabled")
        mock_put.assert_called_once()

    @patch("pipelines.pipelines.get_scheduled_pipelines")
    @patch("pipelines.pipelines.get_pipeline_definition")
    @patch("pipelines.pipelines.disable_pipeline")
    @patch("pipelines.pipelines.logger")
    @patch("pipelines.pipelines.get_headers")
    def test_main_logic(self, mock_get_headers, mock_logger, mock_disable, mock_get_def, mock_get_sched):
        pipeline = {
            "sourceBranch": "refs/heads/feature-xyz",
            "definition": {"id": 10, "name": "P1", "path": "\\MyPipelines"},
            "_links": {"web": {"href": "http://example.com"}}
        }
        excluded_pipeline = {
            "sourceBranch": "refs/heads/feature-abc",
            "definition": {"id": 20, "name": "P2", "path": "\\MyPipelines"},
            "_links": {"web": {"href": "http://example.com"}}
        }
        pipeline_def = {
            "id": 10,
            "name": "P1",
            "path": "\\MyPipelines",
            "queueStatus": "enabled"
        }

        mock_get_sched.return_value = [pipeline, excluded_pipeline]
        mock_get_def.side_effect = [
                {"id": 10, "name": "P1", "path": "\\MyPipelines", "queueStatus": "enabled"},
                {"id": 20, "name": "P2", "path": "\\MyPipelines", "queueStatus": "enabled"},
            ]

        mock_get_headers.return_value = {"Authorization": "Basic pat"}
        self.org = "org"
        self.project = "project"
        self.pat = "pat"
        self.headers = {"Authorization": "Basic pat"}

        args = ["--org", self.org, "--project", self.project, "--pat", self.pat, "--exclude-pipelines", "20"]
        with patch("sys.argv", ["main.py"] + args):
            with patch("pipelines.pipelines.logger", mock_logger):
                main()

        mock_disable.assert_called_once_with(self.org, self.project, pipeline_def, self.headers)
        mock_get_sched.assert_called_once_with(self.org, self.project, self.headers)

        mock_logger.warning.assert_has_calls([
            call("Pipeline:'\\MyPipelines P1' \n Scheduled Branch: refs/heads/feature-xyz \n Pipeline ID: 10 \n Build Url: http://example.com"),
            call("Pipeline '\\MyPipelines P2' is excluded from disabling."),
        ], any_order=False)
        
        mock_logger.info.assert_has_calls([
            call("Excluded pipeline IDs: [20]")
        ], any_order=False)

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
        mock_get_sched.return_value = [pipeline, excluded_pipeline]

        mock_get_def.side_effect = [
            {"id": 10, "name": "P1", "path": "\\MyPipelines", "queueStatus": "enabled"},
            {"id": 20, "name": "P2", "path": "\\MyPipelines", "queueStatus": "enabled"},
        ]

        mock_disable.side_effect = Exception("Api error")

        with patch("sys.argv", ["main.py"] + args):
            with self.assertRaises(SystemExit):
                main()
            mock_logger.error.assert_any_call("Failed to disable pipeline 10: Api error")


if __name__ == "__main__":
    unittest.main()