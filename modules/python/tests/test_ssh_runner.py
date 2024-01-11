import unittest
import os
from unittest.mock import patch, Mock
from ssh.runner import generate_ssh_command, execute_ssh_command

class TestSSHCommand(unittest.TestCase):
    def setUp(self):
        os.environ['SSH_KEY_PATH'] = '/path/to/key'

    def tearDown(self):
        del os.environ['SSH_KEY_PATH']

    def test_generate_ssh_command(self):
        self.assertEqual(os.getenv('SSH_KEY_PATH'), '/path/to/key')
        user = "user"
        ip = "127.0.0.1"
        port = "22"
        command = "ls"

        expected_command = ('ssh -i /path/to/key -A -p 22 user@127.0.0.1 -2 '
                            '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                            '-o IdentitiesOnly=yes -o PreferredAuthentications=publickey '
                            '-o PasswordAuthentication=no -o ConnectTimeout=5 '
                            '-o GSSAPIAuthentication=no -o ServerAliveInterval=30 '
                            '-o ServerAliveCountMax=10 ls')

        actual_command = generate_ssh_command(user, ip, port, command)

        self.assertEqual(expected_command, actual_command)


    @patch('subprocess.Popen')
    def test_execute_ssh_command(self, mock_popen):
        mock_communicate = Mock()
        mock_communicate.communicate.return_value = (b"output", b"error")
        mock_communicate.returncode = 0
        mock_popen.return_value = mock_communicate

        expected_output = "output"
        expected_error = "error"
        ssh_command = ('ssh -i /path/to/key -A -p 22 user@127.0.0.1 -2 '
                       '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                       '-o IdentitiesOnly=yes -o PreferredAuthentications=publickey '
                       '-o PasswordAuthentication=no -o ConnectTimeout=5 '
                       '-o GSSAPIAuthentication=no -o ServerAliveInterval=30 '
                       '-o ServerAliveCountMax=10 ls')

        output, error, _ = execute_ssh_command(ssh_command)

        self.assertEqual(output, expected_output)
        self.assertEqual(error, expected_error)

if __name__ == '__main__':
    unittest.main()