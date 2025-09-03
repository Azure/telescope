"""Compatibility shims exposing legacy module-level helper functions.

This module provides small wrapper functions that forward to the
new class-based utilities so existing callers and tests that patch
these module-level names continue to work.
"""
from .cl2_command import Cl2Command
from .xml_to_json_parser import Xml2JsonParser
from .cl2_report_parser import Cl2ReportProcessor


def run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, **kwargs):
    """Legacy wrapper that constructs a Cl2Command.Params and executes it.

    Extra keyword arguments are forwarded into the Params constructor so
    tests and callers can pass through optional flags.
    """
    params = Cl2Command.Params(
        kubeconfig=kubeconfig,
        cl2_image=cl2_image,
        cl2_config_dir=cl2_config_dir,
        cl2_report_dir=cl2_report_dir,
        provider=provider,
        **kwargs,
    )
    return Cl2Command(params).execute()


def parse_xml_to_json(filepath, indent=0):
    """Legacy wrapper for Xml2JsonParser.parse()."""
    return Xml2JsonParser(filepath, indent=indent).parse()


def process_cl2_reports(cl2_report_dir: str, template: dict):
    """Legacy wrapper for Cl2ReportProcessor.process()."""
    return Cl2ReportProcessor(cl2_report_dir=cl2_report_dir,
                              template=template).process()
