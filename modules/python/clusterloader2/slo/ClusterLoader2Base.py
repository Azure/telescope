import argparse
from abc import ABC, abstractmethod
from enum import Enum


def private(func):
    """Empty decorator to mark methods as private (for notation only)."""
    return func


class ClusterLoader2Base(ABC):
    class ArgsParser(ABC):
        _parser: argparse.ArgumentParser
        _subparsers: argparse.ArgumentParser

        def __init__(self, description: str):
            self._parser = argparse.ArgumentParser(description=description)
            self._subparsers = self._parser.add_subparsers(dest="command")

        @abstractmethod
        def add_configure_args(self, parser):
            pass

        @abstractmethod
        def add_validate_args(self, parser):
            pass

        @abstractmethod
        def add_execute_args(self, parser):
            pass

        @abstractmethod
        def add_collect_args(self, parser):
            pass
      
        def parse(self) -> argparse.Namespace:
            return self._parser.parse_args()

        def print_help(self):
            self._parser.print_help()

    class Runner(ABC):
        @abstractmethod
        def configure(self):
            pass
        
        @abstractmethod
        def validate(self):
            pass
        
        @abstractmethod
        def execute(self):
            pass
        
        @abstractmethod
        def collect(self):
            pass
    
    class Command(Enum):
        CONFIGURE = "configure"
        VALIDATE = "validate"
        EXECUTE = "execute"
        COLLECT = "collect"

    @property
    @abstractmethod
    def args_parser(self) -> ArgsParser:
        pass

    @property
    @abstractmethod
    def runner(self) -> Runner:
        pass

    def parse_arguments(self) -> argparse.Namespace:
        # Sub-command for configuring clusterloader2
        parser_configure = self.args_parser._subparsers.add_parser("configure", help="Override CL2 config file")
        self.args_parser.add_configure_args(parser_configure)

        # Sub-command for validating clusterloader2's cluster setup
        parser_validate = self.args_parser._subparsers.add_parser("validate", help="Validate cluster setup")
        self.args_parser.add_validate_args(parser_validate)

        # Sub-command for executing tests using clusterloader2
        parser_execute = self.args_parser._subparsers.add_parser("execute", help="Execute scale up operation")
        self.args_parser.add_execute_args(parser_execute)

        # Sub-command for collecting clusterloader2's results
        parser_collect = self.args_parser._subparsers.add_parser("collect", help="Collect scale up data")
        self.args_parser.add_collect_args(parser_collect)
        
        return self.args_parser.parse()

    def perform(self):
        args = self.parse_arguments()
        args_dict = vars(args)
        command = args_dict.pop("command")

        if command == ClusterLoader2Base.Command.CONFIGURE.value:
            self.runner.configure(**args_dict)
        elif command == ClusterLoader2Base.Command.VALIDATE.value:
            self.runner.validate(**args_dict)
        elif command == ClusterLoader2Base.Command.EXECUTE.value:
            self.runner.execute(**args_dict)
        elif command == ClusterLoader2Base.Command.COLLECT.value:
            self.runner.collect(**args_dict)
        else:
            print(f"I can't recognize `{command}`\n")
            self.args_parser.print_help()            
