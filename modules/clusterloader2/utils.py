import json
import subprocess

from xml.dom import minidom

IMAGE="telescope.azurecr.io/perf-eval/clusterloader2:20240917"

def run_command(command):
    """Utility function to run a shell command and capture the output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

def base_cl2_command(kubeconfig, cl2_config_dir, cl2_report_dir, provider, overrides=None):
    command=f"""docker run -it \\
-v {kubeconfig}:/root/.kube/config \\
-v {cl2_config_dir}:/root/perf-tests/clusterloader2/config \\
-v {cl2_report_dir}:/root/perf-tests/clusterloader2/results \\
{IMAGE} \\
--provider={provider} --v=2 --enable-exec-service=false \\
--kubeconfig /root/.kube/config \\
--testconfig /root/perf-tests/clusterloader2/config/config.yaml \\
--report-dir /root/perf-tests/clusterloader2/results"""
    if overrides:
        command += f"--overrides {overrides}"

    return command

def parse_xml_to_json(file_path, indent = 0):
    # Open and read the XML file
    with open(file_path, 'r') as file:
        xml_content = file.read()
    
    # Parse the XML content
    dom = minidom.parseString(xml_content)
    
    # Initialize the result dictionary
    result = {
        "testsuites": []
    }
    
    # Extract test suites
    testsuites = dom.getElementsByTagName("testsuite")
    for testsuite in testsuites:
        suite_name = testsuite.getAttribute("name")
        suite_tests = int(testsuite.getAttribute("tests"))
        suite_failures = int(testsuite.getAttribute("failures"))
        suite_errors = int(testsuite.getAttribute("errors"))
        
        suite_result = {
            "name": suite_name,
            "tests": suite_tests,
            "failures": suite_failures,
            "errors": suite_errors,
            "testcases": []
        }
        
        # Extract test cases
        testcases = testsuite.getElementsByTagName("testcase")
        for testcase in testcases:
            case_name = testcase.getAttribute("name")
            case_classname = testcase.getAttribute("classname")
            case_time = testcase.getAttribute("time")
            
            case_result = {
                "name": case_name,
                "classname": case_classname,
                "time": case_time,
                "failure": None
            }
            
            # Check for failure
            failure = testcase.getElementsByTagName("failure")
            if failure:
                failure_message = failure[0].firstChild.nodeValue
                case_result["failure"] = failure_message
            
            suite_result["testcases"].append(case_result)
        
        result["testsuites"].append(suite_result)
    
    # Convert the result dictionary to JSON
    json_result = json.dumps(result, indent = indent)
    return json_result
