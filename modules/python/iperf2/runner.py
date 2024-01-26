import argparse
import os
import sys
import time

from ssh.runner import generate_ssh_command, execute_ssh_command

def generate_iperf2_command(protocol, ip_address, port, bandwidth, parallel, duration=60):
    command = "iperf --enhancedreports "
    command += "--format m "
    if protocol == "udp":
        command += "--udp "

    command += "--client " + ip_address + " "
    command += "--port " + port + " "
    command += "--bandwidth " + f"{bandwidth}M" + " "
    command += "--parallel " + str(parallel) + " "
    command += "--time " + str(duration)

    return command

def main():
    parser = argparse.ArgumentParser(description='Run SSH command.')
    parser.add_argument('--ssh-user', required=False, default='ubuntu', help='Username for SSH')
    parser.add_argument('--ssh-port', required=False, default='2222', help='Port for SSH')
    parser.add_argument('--client-ip', required=True, help='Public IP Address of client machine')
    parser.add_argument('--server-ip', required=True, help='IP Address of iperf server')
    parser.add_argument('--server-port', required=False, default='5001', help='Port for iperf server')
    parser.add_argument('--protocol', required=False, default='tcp', help='Protocol to run iperf, can be either udp or tcp')
    parser.add_argument("--bandwidths", nargs="+", type=int, help="Bandwidth list to run iperf")
    parser.add_argument("--parallels", nargs="+", type=int, help="Parallel list to run iperf")
    parser.add_argument('--startup', required=False, default=0, help='Startup delay in seconds')
    parser.add_argument('--interval', required=False, default=0, help='Interval in seconds')
    parser.add_argument('--duration', required=False, default=60, help='Duration to run iperf')
    parser.add_argument('--output', required=False, default='/tmp/', help='Output file path')

    args = parser.parse_args()

    n = len(args.bandwidths)
    if n != len(args.parallels):
        print('Error: length of bandwidths and parallels must be equal', file=sys.stderr)
        sys.exit(1)

    print(f'Waiting for {args.startup} seconds before iperf2 tests')
    time.sleep(args.startup)
    for i in range(n):
        parallel = args.parallels[i]
        bandwidth = args.bandwidths[i]
        print(f'Running iperf2 test with bandwidth {bandwidth}M and parallel {parallel}')
        iperf_command = generate_iperf2_command(args.protocol, args.server_ip, args.server_port, bandwidth, parallel, args.duration)
        ssh_command = generate_ssh_command(args.ssh_user, args.client_ip, args.ssh_port, iperf_command)
        output, error, returncode = execute_ssh_command(ssh_command)
        name = os.path.join(args.output, f'iperf2_{args.protocol}_{bandwidth}M_{parallel}.txt')
        file = open(name, 'w')
        file.write(output)
        if returncode != 0:
            print('Error: ', error, file=sys.stderr)

        print(f'Waiting for {args.interval} seconds before iperf2 tests')
        time.sleep(args.interval)

if __name__ == '__main__':
  main()