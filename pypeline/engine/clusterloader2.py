from benchmark import Engine
from pipeline import Step


class ClusterLoader2(Engine):
    def setup(self) -> list[Step]:
        return []

    def validate(self) -> list[Step]:
        return []

    def run(self) -> list[Step]:
        return []

    def tear_down(self) -> list[Step]:
        return []