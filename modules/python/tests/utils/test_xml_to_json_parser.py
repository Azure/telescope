import unittest
import json
from unittest import mock

from clusterloader2.utils.xml_to_json_parser import Xml2JsonParser


class TestXml2JsonParser(unittest.TestCase):
    def test_parse_single_testsuite_with_failures_and_success(self):
        xml = '''<?xml version="1.0"?>
<testsuites>
  <testsuite name="suite1" tests="2" failures="1" errors="0">
    <testcase name="case1" classname="class.A" time="0.1"/>
    <testcase name="case2" classname="class.B" time="0.2">
      <failure>something went wrong</failure>
    </testcase>
  </testsuite>
</testsuites>
'''
        with mock.patch('clusterloader2.utils.xml_to_json_parser.read_from_file', return_value=xml):
            parser = Xml2JsonParser(filepath="/fake/path.xml", indent=2)
            out = parser.parse()
            data = json.loads(out)

            self.assertIn('testsuites', data)
            self.assertEqual(len(data['testsuites']), 1)

            suite = data['testsuites'][0]
            self.assertEqual(suite['name'], 'suite1')
            self.assertEqual(suite['tests'], '2')
            self.assertEqual(suite['failures'], '1')
            self.assertEqual(suite['errors'], '0')

            self.assertIn('testcases', suite)
            self.assertEqual(len(suite['testcases']), 2)

            case1 = suite['testcases'][0]
            self.assertEqual(case1['name'], 'case1')
            self.assertIsNone(case1['failure'])

            case2 = suite['testcases'][1]
            self.assertEqual(case2['name'], 'case2')
            self.assertEqual(case2['failure'], 'something went wrong')

    def test_parse_multiple_testsuites_and_empty_failure_node(self):
        xml = '''<?xml version="1.0"?>
<testsuites>
  <testsuite name="s1" tests="1" failures="0" errors="0">
    <testcase name="ok" classname="c" time="0"/>
  </testsuite>
  <testsuite name="s2" tests="1" failures="1" errors="0">
    <testcase name="bad" classname="c2" time="0.5">
      <failure></failure>
    </testcase>
  </testsuite>
</testsuites>
'''
        with mock.patch('clusterloader2.utils.xml_to_json_parser.read_from_file', return_value=xml):
            parser = Xml2JsonParser(filepath="/fake/path2.xml")
            out = parser.parse()
            data = json.loads(out)

            self.assertEqual(len(data['testsuites']), 2)

            s2 = data['testsuites'][1]
            self.assertEqual(s2['name'], 's2')
            self.assertEqual(len(s2['testcases']), 1)
            case = s2['testcases'][0]
            # empty failure node => failure should be None
            self.assertIsNone(case['failure'])


if __name__ == '__main__':
    unittest.main()
