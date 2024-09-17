import json
import subprocess
import os
import docker

from xml.dom import minidom
from docker_client import DockerClient

IMAGE="telescope.azurecr.io/perf-eval/clusterloader2:20240917.1"

def run_command(command):
    """Utility function to run a shell command and capture the output."""
    print(f"Running command: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    print(result.stdout)
    return result.stdout.strip()

def run_cl2_command(kubeconfig, cl2_config_dir, cl2_report_dir, provider, overrides=False):
    docker_client = DockerClient()
    command=f"""--provider={provider} --v=2 --enable-exec-service=false
--kubeconfig /root/.kube/config 
--testconfig /root/perf-tests/clusterloader2/config/config.yaml 
--report-dir /root/perf-tests/clusterloader2/results"""
    if overrides:
        command += f" --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml"

    volumes = { 
        kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
        cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
        cl2_report_dir: {'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
    }

    if provider == "aws":
        aws_path = os.path.expanduser("~/.aws/credentials")
        volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

    try:
        container = docker_client.run_container(IMAGE, command, volumes, detach=False)
        return container.logs().decode('utf-8')
    except docker.errors.ContainerError as e:
        return f"Container exited with a non-zero status code: {e.exit_status}\n{e.stderr.decode('utf-8')}"

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
