from textwrap import dedent

from benchmark import Resource
from pipeline import Script, Step

check_dependencies = Script(
    display_name="Check Dependencies",
    script=dedent(
        """
        python3 --version && pip3 --version
        jq --version
        """.strip(
            "\n"
        )
    ),
)

install_dependencies = Script(
    display_name="Install Dependencies",
    script=dedent(
        """
        set -e
        if [ -f "$(Pipeline.Workspace)/s/modules/python/requirements.txt" ]; then
            pip3 install -r $(Pipeline.Workspace)/s/modules/python/requirements.txt
        fi
        sudo apt-get -y install bc
        """.strip(
            "\n"
        )
    ),
)


def validate_dependencies() -> Script:
    return (
        Script(
            display_name="Validate Installed Dependencies",
            script=dedent(
                """
                set -e

                # Check if requirements.txt exists
                echo "Validating installed dependencies..."
                missing_dependencies=$(pip3 check 2>&1 | grep -i "not found" || true)
                if [ -n "$missing_dependencies" ]; then
                    echo "Error: Missing dependencies:"
                    echo "$missing_dependencies"
                    exit 1
                fi
                echo "All dependencies are installed."
                """
            ).strip(),
        ),
    )


def delete_dependencies() -> Script:
    return Script(
        display_name="Uninstall Python Dependencies",
        script=dedent(
            """
            set -e

            echo "Uninstalling Python dependencies listed in requirements.txt..."
            xargs -a "$(Pipeline.Workspace)/s/modules/python/requirements.txt" -n 1 pip3 uninstall -y
            """
        ).strip(),
    )


def delete_cache() -> Script:
    return Script(
        display_name="Delete Python Cache",
        script=dedent(
            """
            set -e

            echo "Deleting Python cache..."
            rm -rf "$(Pipeline.Workspace)/s/modules/python/__pycache__"
            echo "Python environment cleanup completed."
            """
        ).strip(),
    )


class Python3(Resource):
    def setup(self) -> list[Step]:
        return [
            check_dependencies,
            install_dependencies,
        ]

    def validate(self) -> list[Step]:
        return [validate_dependencies()]

    def tear_down(self) -> list[Step]:
        return [delete_dependencies(), delete_cache()]
