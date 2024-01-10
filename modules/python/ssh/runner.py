import subprocess
import argparse
import sys
import os

def generate_ssh_command(user, ip, port, command):
    SSH_KEY_PATH = os.getenv('SSH_KEY_PATH')
    ssh_command = (
        f'ssh -i {SSH_KEY_PATH} '
        f'-A '
        f'-p {port} '
        f'{user}@{ip} -2 '
        '-o UserKnownHostsFile=/dev/null '
        '-o StrictHostKeyChecking=no '
        '-o IdentitiesOnly=yes '
        '-o PreferredAuthentications=publickey '
        '-o PasswordAuthentication=no '
        '-o ConnectTimeout=5 '
        '-o GSSAPIAuthentication=no '
        '-o ServerAliveInterval=30 '
        '-o ServerAliveCountMax=10 '
        f'{command}'
    )
    return ssh_command

def execute_ssh_command(ssh_command):
    process = subprocess.Popen(ssh_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    output, error = process.communicate()
    return output.decode(), error.decode(), process.returncode

def main():
    parser = argparse.ArgumentParser(description='Run SSH command.')
    parser.add_argument('--user', required=False, default='ubuntu', help='Username for SSH')
    parser.add_argument('--ip', required=True, help='IP Address')
    parser.add_argument('--port', required=False, default='2222', help='Port for SSH')
    parser.add_argument('--command', required=False, default='hostname', help='Command to execute via SSH')

    args = parser.parse_args()

    ssh_command = generate_ssh_command(args.user, args.ip, args.port, args.command)
    output, error, returncode = execute_ssh_command(ssh_command)

    print(output)
    if returncode != 0:
        print('Error: ', error, file=sys.stderr)

if __name__ == "__main__":
    main()