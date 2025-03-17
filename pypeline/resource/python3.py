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


class Python3(Resource):
    def setup(self) -> list[Step]:
        return [
            check_dependencies,
            install_dependencies,
        ]

    def validate(self) -> list[Step]:
        return []

    def tear_down(self) -> list[Step]:
        return []
