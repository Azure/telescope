import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ClusterLoader2Base(ABC):
    # TODO: Optimize and add all shared values when all tests are implemented
    # e.g: https://docs.python.org/3/library/dataclasses.html#inheritance

    @abstractmethod
    def configure_clusterloader2(self):
        pass

    @abstractmethod
    def validate_clusterloader2(self):
        pass

    @abstractmethod
    def execute_clusterloader2(self):
        pass

    @abstractmethod
    def collect_clusterloader2(self):
        pass

    @staticmethod
    @abstractmethod
    def add_validate_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_execute_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_collect_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_configure_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @classmethod
    def create_parser(cls, description) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description=description)
        subparsers = parser.add_subparsers(dest="command")

        # Sub-command for configure_clusterloader2
        parser_configure = subparsers.add_parser(
            "configure", help="Configure ClusterLoader2"
        )
        cls.add_configure_subparser_arguments(parser_configure)

        # Sub-command for validate_clusterloader2
        parser_validate = subparsers.add_parser(
            "validate", help="Validate cluster setup"
        )
        cls.add_validate_subparser_arguments(parser_validate)

        # Sub-command for execute_clusterloader2
        parser_execute = subparsers.add_parser(
            "execute", help="Execute ClusterLoader2 tests"
        )
        cls.add_execute_subparser_arguments(parser_execute)

        # Sub-command for collect_clusterloader2
        parser_collect = subparsers.add_parser("collect", help="Collect test results")
        cls.add_collect_subparser_arguments(parser_collect)

        return parser

    def write_cl2_override_file(self, logger, cl2_override_file, config):
        with open(cl2_override_file, "w", encoding="utf-8") as file:
            file.writelines(f"{k}: {v}\n" for k, v in config.items())

        with open(cl2_override_file, "r", encoding="utf-8") as file:
            logger.info(f"Content of file {cl2_override_file}:\n{file.read()}")
