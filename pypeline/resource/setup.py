from dataclasses import dataclass
from textwrap import dedent

from benchmark import Resource
from pipeline import Script, Step

set_run_id = lambda run_id: Script(
    display_name="Set run id",
    script=dedent(
        """
        if [ -n "$RUN_ID" ]; then
        run_id=$RUN_ID
        else
        run_id=$(Build.BuildId)-$(System.JobId)
        fi
        echo "Run ID: $run_id"
        echo "##vso[task.setvariable variable=RUN_ID]$run_id"
        """.strip(
            "\n"
        )
    ),
    env={"RUN_ID": run_id},
)

set_run_url_and_code_url = Script(
    display_name="Set Run URL & Code URL",
    script=dedent(
        """
        run_url="$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)&view=logs&j=$(System.JobId)"
        echo "Run URL: $run_url"
        echo "##vso[task.setvariable variable=RUN_URL]$run_url"

        code_url="$(Build.Repository.Uri)/commit/$(Build.SourceVersion)"
        echo "Code URL: $code_url"
        echo "##vso[task.setvariable variable=CODE_URL]$code_url"
        """.strip(
            "\n"
        )
    ),
)

set_test_results_directory = Script(
    display_name="Set Test Results Directory",
    script=dedent(
        """
        test_results_directory=$(Pipeline.Workspace)/s/$(RUN_ID)
        mkdir -p $test_results_directory
        echo "Test Results directory: $test_results_directory"
        echo "##vso[task.setvariable variable=TEST_RESULTS_DIR]$test_results_directory"

        test_results_file=$test_results_directory/results.json

        echo "Test Results file: $test_results_file"
        echo "##vso[task.setvariable variable=TEST_RESULTS_FILE]$test_results_file"
        """.strip(
            "\n"
        )
    ),
)

set_script_module_directory = lambda test_modules_dir: Script(
    display_name="Set Script Module Directory",
    script=dedent(
        """
        if [ -n "${TEST_MODULES_DIR}" ]; then
            test_modules_directory=$(Pipeline.Workspace)/s/${TEST_MODULES_DIR}
        else
            test_modules_directory=$(Pipeline.Workspace)/s/modules/bash
        fi
        echo "Script modules directory: $test_modules_directory"
        echo "##vso[task.setvariable variable=TEST_MODULES_DIR]$test_modules_directory"
        """.strip(
            "\n"
        )
    ),
    env={"TEST_MODULES_DIR": test_modules_dir},
)


@dataclass
class Setup(Resource):
    run_id: str
    test_module_dir: str = ""

    def setup(self) -> list[Step]:
        return [
            set_run_id(self.run_id),
            set_run_url_and_code_url,
            set_test_results_directory,
            set_script_module_directory(self.test_module_dir),
        ]

    def validate(self) -> list[Step]:
        return []

    def tear_down(self) -> list[Step]:
        return []
