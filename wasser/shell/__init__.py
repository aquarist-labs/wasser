import logging
import os
import paramiko
import socket
import time
import threading


class Shell():
    cmdlog_prefix = '+++ '
    stdout_prefix = '>>> '
    stderr_prefix = 'EEE '

    @staticmethod
    def log_info(std, prefix):
        while True:
            line = std.readline()
            if not line:
                break
            if isinstance(line, bytes):
                logging.info(prefix + line.decode().rstrip())
            else:
                logging.info(prefix + line.rstrip())

    def log_cmd(self, command: str, name: str = None):
        if name:
            logging.info(f"=== {name}")
        for i in command.split('\n'):
            logging.info(f'{self.cmdlog_prefix} {i}')

    def start_logging_stderr(self, stream):
        t = threading.Thread(target=self.log_info, args=(stream, self.stderr_prefix))
        t.start()
        return t

    def start_logging_stdout(self, stream):
        t = threading.Thread(target=self.log_info, args=(stream, self.stdout_prefix))
        t.start()
        return t

    def run(self, command: str, name: str = None, timeout: int = None) -> None:
        pass


import subprocess

class LocalShell(Shell):
    def __init__(self, user: str):
        self.hostname = 'local'
        self.username = user or os.environ.get('USER')


    def copy_files(self, copy_spec):
        logging.warning('copy files is not supported yet for local host')


    def run(self, command: str, name: str = None, timeout: int = None) -> None:
        self.log_cmd(command, name)

        p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE)

        stdout_thread = self.start_logging_stdout(p.stdout)
        stderr_thread = self.start_logging_stderr(p.stderr)

        exit_code = p.wait(timeout=timeout)

        stdout_thread.join()
        stderr_thread.join()

        if exit_code:
            raise Exception(f"Received exit code {exit_code} while running command: {command}")
        logging.info(f"||| exit code: {exit_code}")


class RemoteShell(Shell):
    def __init__(self, name='localhost', user='root', identity=None):
        self.client = None
        self.username = user
        self.hostname = name
        self.identity = os.path.expanduser(identity or '~/.ssh/id_rsa')

    def connect_client(self, wait=10, timeout=300):
        """
            returns ssh client object
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        start_time = time.time()
        logging.info(f"Connecting to host [{self.hostname}]")
        while True:
            try:
                client.connect(self.hostname, username=self.username, key_filename=self.identity)
                logging.info("Connected to the host " + self.hostname)
                break
            except (paramiko.ssh_exception.NoValidConnectionsError,
                    paramiko.ssh_exception.SSHException,
                    socket.error) as e:
                logging.debug("Exception occured: " + str(e))
                if timeout < (time.time() - start_time):
                    logging.error("Timeout occured")
                    raise e
                else:
                    logging.info(f"Waiting {wait} seconds...")
                    time.sleep(wait)
        self.client = client
        return client

    def get_client(self):
        if self.client:
            return self.client
        else:
            return self.connect_client()

    def copy_files(self, copy_spec):
        logging.debug(f"Copy spec: {copy_spec}")
        client = self.get_client()
        if copy_spec:
            with client.open_sftp() as sftp:
                for i in copy_spec:
                    for path in i['from']:
                        if not path.startswith('/'):
                            if not os.path.isfile(path):
                                base = os.path.dirname(__file__)
                                if base:
                                    path = base + '/' + path
                        path = os.path.abspath(path)
                        logging.info('Upload file %s' % path)
                        name = os.path.basename(path)
                        dest = i['into'].rstrip('/') + '/' + name
                        sftp.put(path, dest)
                        for x in ['mode', 'chmod']:
                            if x in i:
                                sftp.chmod(dest, int(i[x], 8))


    def run(self, command: str, name: str = None, timeout: int = None) -> None:
        self.log_cmd(command, name)

        client = self.get_client()
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

        stdout_thread = self.start_logging_stdout(stdout)
        stderr_thread = self.start_logging_stderr(stderr)

        stdout_thread.join()
        stderr_thread.join()

        exit_code = stdout.channel.recv_exit_status()
        if exit_code:
            raise Exception(f"Received exit code {exit_code} while running command: {command}")
        logging.info(f"||| exit code: {exit_code}")
