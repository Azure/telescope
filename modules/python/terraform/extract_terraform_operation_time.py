import re
import json
import sys

def extract_resources_from_log(log_file, action_type):
    # Regex pattern to extract module, action type, and time taken
    pattern = re.compile(r"(module\.[\w\-\.]+\[.*?\]): (?:Destruction|Creation) complete after (\d+m\d+s|\d+s)")

    resource_data = []

    # Read and process the Terraform log file
    with open(log_file, "r") as f:
        for line in f:
            if "Creation" in line or "Destruction" in line:
                match = pattern.search(line.strip())
                if match:
                    module_resource = match.group(1)  # Extract the entire module resource
                    time_str = match.group(2)  # Extract the time taken (e.g., 4m14s or 10s)

                    # Convert the time string to seconds
                    if 'm' in time_str:
                        minutes, seconds = time_str.split('m')
                        total_seconds = int(minutes) * 60 + int(seconds[:-1])  # Remove "s" and convert to seconds
                    else:
                        total_seconds = int(time_str[:-1])  # Remove "s" and convert to seconds

                    # Remove the "module." prefix from the module_resource
                    module_resource = module_resource.replace("module.", "")

                    # Split the module_resource between main module and submodule
                    first_dot_index = module_resource.find('.')
                    if first_dot_index != -1:
                        main_module = module_resource[:first_dot_index]  # Get the main module (first part)
                        submodule_name = module_resource[first_dot_index + 1:]  # Get everything after the first dot

                        # Extract the resource name, which is the last segment after the last dot
                        last_dot_index = submodule_name.rfind('.')
                        if last_dot_index != -1:
                            resource_name = submodule_name[last_dot_index + 1:]  # Get the last part after the last dot
                            submodule_name = submodule_name[:last_dot_index]  # Update submodule_name to exclude the resource
                        else:
                            resource_name = submodule_name  # If no dot found, the whole is the resource name
                            submodule_name = ""

                    else:
                        main_module = module_resource
                        submodule_name = ""
                        resource_name = ""

                    # Store resource details along with action (apply/destroy)
                    resource_data.append({
                        "module_name": main_module,  # First part before dot
                        "submodule_name": submodule_name,  # Rest of the string (excluding resource)
                        "resource_name": resource_name,  # Last part after the last dot
                        "action": action_type,
                        "time_taken_seconds": total_seconds
                    })

    # Return the collected data as a JSON string
    return json.dumps(resource_data, indent=4)

if __name__ == "__main__":
    # Get log file and action type (apply/destroy) from arguments
    log_file = sys.argv[1]
    action_type = sys.argv[2]

    # Call the function and print the result
    result_json = extract_resources_from_log(log_file, action_type)
    print(result_json)