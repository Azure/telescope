from xml.dom import minidom
from enum import Enum
import json

from  .common import read_from_file

class TagNames(Enum):
    TESTSUITE = "testsuite"
    TESTCASE = "testcase"
    FAILURE = "failure"

class AttributeNames(Enum):
    NAME = "name"
    TESTS = "tests"
    FAILURES = "failures"
    ERRORS = "errors"
    CLASSNAME = "classname"
    TIME = "time"

class Xml2JsonParser:
    def __init__(self, 
                 filepath: str, 
                 indent: int = 0):
        self._filepath = filepath
        self._indent = indent
        self._xml_content = None

    @property
    def xml_document(self) -> minidom.Document:
        if getattr(self, "_xml_doc", None) is None:
            xml_content = read_from_file(self._filepath)
            self._xml_doc = minidom.parseString(xml_content)
        return self._xml_doc
    
    @property
    def testsuites(self) -> minidom.NodeList[minidom.Element]:
        return self.xml_document.getElementsByTagName(TagNames.TESTSUITE.value)
    
    def _process_case(self, testcase: minidom.Element) -> dict:
        case_name = testcase.getAttribute(AttributeNames.NAME.value)
        case_classname = testcase.getAttribute(AttributeNames.CLASSNAME.value)
        case_time = testcase.getAttribute(AttributeNames.TIME.value)

        case_result = {
            AttributeNames.NAME.value: case_name,
            AttributeNames.CLASSNAME.value: case_classname,
            AttributeNames.TIME.value: case_time,
            TagNames.FAILURE.value: None
        }

        # Check for failure
        failure = testcase.getElementsByTagName(TagNames.FAILURE.value)
        if failure and failure[0].firstChild:
            case_result[TagNames.FAILURE.value] = failure[0].firstChild.nodeValue

        return case_result
    
    def _process_suite(self, testsuite: minidom.Element) -> list[dict]:
        testcases = testsuite.getElementsByTagName(TagNames.TESTCASE.value)
        return [self._process_case(tc) for tc in testcases]

    def parse(self) -> str:
        result = {
            "testsuites": [ 
                {
                    AttributeNames.NAME.value: suite.getAttribute(AttributeNames.NAME.value),
                    AttributeNames.TESTS.value: suite.getAttribute(AttributeNames.TESTS.value),
                    AttributeNames.FAILURES.value: suite.getAttribute(AttributeNames.FAILURES.value),
                    AttributeNames.ERRORS.value: suite.getAttribute(AttributeNames.ERRORS.value),
                    "testcases": self._process_suite(suite)
                } for suite in self.testsuites
            ]
        }

        return json.dumps(result, indent=self._indent)
