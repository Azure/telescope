import argparse
from abc import ABC, abstractmethod
from enum import Enum

from utils.logger_config import get_logger, setup_logging
from utils import (
    write_to_file,
    convert_config_to_str,
    parse_test_results
)

# Configure logging
setup_logging()
logger = get_logger(__name__)


class Command(Enum):
    CONFIGURE = "configure"
    VALIDATE = "validate"
    EXECUTE = "execute"
    COLLECT = "collect"

def Ignored(func):
    """A decorator indicating a parameter to be skipped"""
    func.is_ignored = True
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
        def configure(self) -> dict:
            pass
        
        @abstractmethod
        def validate(self):
            pass
        
        @abstractmethod
        def execute(self):
            pass
        
        @abstractmethod
        def collect(self) -> str:
            pass
    
    @property
    @abstractmethod
    def args_parser(self) -> ArgsParser:
        pass

    @property
    @abstractmethod
    def runner(self) -> Runner:
        pass

    def _add_subparser(self, command: Command, description: str):
        subparsers = self.args_parser._subparsers
        
        add_args_method = {
            Command.CONFIGURE.value: self.args_parser.add_configure_args,
            Command.VALIDATE.value: self.args_parser.add_validate_args,
            Command.EXECUTE.value: self.args_parser.add_execute_args,
            Command.COLLECT.value: self.args_parser.add_collect_args,
        }.get(command)

        if not add_args_method:
            return

        is_method_ignored = getattr(add_args_method, "is_ignored")

        if not is_method_ignored:
            parser = subparsers.add_parser(command.value, help=description)
            add_args_method(parser)

    def parse_arguments(self) -> argparse.Namespace:
        # Sub-command for configuring clusterloader2
        self._add_subparser(
            command=Command.CONFIGURE.value,
            description="Override CL2 config file",
        )

        # Sub-command for validating clusterloader2's cluster setup
        self._add_subparser(
            command=Command.VALIDATE.value,
            description="Validate cluster setup",
        )

        # Sub-command for executing tests using clusterloader2
        self._add_subparser(
            command=Command.EXECUTE.value,
            description="Execute scale up operation",
        )

        # Sub-command for collecting clusterloader2's results
        self._add_subparser(
            command=Command.COLLECT.value,
            description="Collect scale up data",
        )

        return self.args_parser.parse()

    def perform(self):
        args = self.parse_arguments()
        args_dict = vars(args)
        command = args_dict.pop("command")

        if command == Command.CONFIGURE.value:
            config_dict = self.runner.configure(**args_dict)
            write_to_file(
                filename=args_dict.cl2_override_file,
                content=convert_config_to_str(config_dict)
            )
        elif command == Command.VALIDATE.value:
            self.runner.validate(**args_dict)
        elif command == Command.EXECUTE.value:
            self.runner.execute(**args_dict)
        elif command == Command.COLLECT.value:
            status, results = parse_test_results(args_dict.cl2_report_dir)
            result = self.runner.collect(
                test_status=status, 
                test_results=results, 
                **args_dict
            )
            write_to_file(
                filename=args.result_file,
                content=result,
            )
        else:
            print(f"I can't recognize `{command}`\n")
            self.args_parser.print_help()            
