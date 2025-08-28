import argparse
from abc import ABC, abstractmethod
from enum import Enum


def private(func):
    """Empty decorator to mark methods as private (for notation only)."""
    return func


class ClusterLoader2Base(ABC):
    class ArgsParser(ABC):
        @abstractmethod
        def add_configure_args(self):
            pass

        @abstractmethod
        def add_validate_args(self):
            pass

        @abstractmethod
        def add_execute_args(self):
            pass

        @abstractmethod
        def add_collect_args(self):
            pass

        @abstractmethod
        def parse(self) -> argparse.Namespace:
            pass

        @abstractmethod
        def print_help(self):
            pass

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

    @abstractmethod
    def parse_arguments(self) -> argparse.Namespace:
        # Sub-command for configuring clusterloader2
        self.args_parser.add_configure_args()

        # Sub-command for validating clusterloader2's cluster setup
        self.args_parser.add_validate_args()

        # Sub-command for executing tests using clusterloader2
        self.args_parser.add_execute_args()

        # Sub-command for collecting clusterloader2's results
        self.args_parser.add_collect_args()
        
        return self.args_parser.parse()

    @abstractmethod
    def perform(self, args: argparse.Namespace):
        args_dict = vars(args)
        command = args_dict.pop("command")

        if command == ClusterLoader2Base.Command.CONFIGURE:
            self.runner.configure()
        elif command == ClusterLoader2Base.Command.VALIDATE:
            self.runner.validate()
        elif command == ClusterLoader2Base.Command.EXECUTE:
            self.runner.execute()
        elif command == ClusterLoader2Base.Command.COLLECT:
            self.runner.collect()
        else:
            self.args_parser.print_help()            
