from dataclasses import dataclass, field
from textwrap import dedent

from components import Resource
from pipeline import Script, Step


def set_run_id(run_id: str) -> Script:
    if not run_id:
        run_id = "$(Build.BuildId)-$(System.JobId)"

    return Script(
        display_name="Set run id",
        script=dedent(
            f"""
            echo "Run ID: {run_id}"
            echo "##vso[task.setvariable variable=RUN_ID]{run_id}"
            """
        ).strip(),
    )


def set_run_url_and_code_url() -> Script:

    return Script(
        display_name="Set Run URL & Code URL",
        script=dedent(
            """
            run_url="$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)&view=logs&j=$(System.JobId)"
            echo "Run URL: $run_url"
            echo "##vso[task.setvariable variable=RUN_URL]$run_url"

            code_url="$(Build.Repository.Uri)/commit/$(Build.SourceVersion)"
            echo "Code URL: $code_url"
            echo "##vso[task.setvariable variable=CODE_URL]$code_url"
            """
        ).strip(),
    )


def set_test_results_directory() -> Script:

    return Script(
        display_name="Set Test Results Directory",
        script=dedent(
            """
            test_results_directory=$(Pipeline.Workspace)/s/$(RUN_ID)
            mkdir -p $test_results_directory
            echo "Test Results directory: $test_results_directory"

            test_results_file=$test_results_directory/results.json

            echo "Test Results file: $test_results_file"
            echo "##vso[task.setvariable variable=TEST_RESULTS_FILE]$test_results_file"
            """
        ).strip(),
    )


def set_script_module_directory(test_modules_dir: str) -> Script:
    if not test_modules_dir:
        test_modules_dir = "modules/bash"

    script_modules_directory = f"$(Pipeline.Workspace)/s/{test_modules_dir}"

    return Script(
        display_name="Set Script Module Directory",
        script=dedent(
            f"""
            echo "Script modules directory: {script_modules_directory}"
            """
        ).strip(),
    )


def validate_owner_info() -> Script:

    return Script(
        display_name="Validate OWNER info",
        script=dedent(
            """
            # Check if OWNER has been set to any string value other than an empty string
            if [ -z "$OWNER" ]; then
                echo "##vso[task.logissue type=error;] OWNER is not set. Please set OWNER to a valid value ('aks', 'compute', 'networking', 'storage') in the pipeline."
                exit 1
            fi
            """
        ).strip(),
        condition="eq(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


@dataclass
class Setup(Resource):
    run_id: str
    engine: str
    test_module_dir: str = ""
    engine_input: dict = field(default_factory=dict)

    def setup(self) -> list[Step]:
        return [
            set_run_id(self.run_id),
            set_run_url_and_code_url,
            set_test_results_directory,
            set_script_module_directory(self.test_module_dir),
        ]

    def validate(self) -> list[Step]:
        return [validate_owner_info()]

    def execute_tests(self) -> list[Step]:
        return []

    def tear_down(self) -> list[Step]:
        return []
