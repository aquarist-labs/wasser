"""Workflow Automation Software for Shell Executable Routines

Wasser is a tiny tool for continuous delivery and continuous integration
which is supposed to be simple and easy to use for virtualized system
deployment and test automation.

Wasser is the German word for 'water', which is suddenly and splendidly
stands for Workflow Automation Software for Shell Executable Routines.
There are few common abbreviations for it: W., Wa., and Ws.; and one of
it can be reasonably used as a command name (or alias) for a shorthand,
except of 'w' of course, since it is already taken by system utility.
"""

import argparse
import logging
import os
import sys

import signal

import paramiko
import socket
import threading

import json

def main():
    parser = argparse.ArgumentParser(
            description='wasser - workflow automation software for shell executable routines')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-q', '--quiet', action='store_true', help='subpress logging')


    github_parser = argparse.ArgumentParser(add_help=False)
    github_parser.add_argument('--github-url',
                                            default='',
                                            help='github repo')
    github_parser.add_argument('--github-branch',
                                            default='main',
                                            help='github branch')

    openstack_parser = argparse.ArgumentParser(add_help=False)
    openstack_parser.add_argument('--openstack-cloud',
                                            default=os.environ.get('OS_CLOUD', None),
                                            help='openstack cloud')
    openstack_parser.add_argument('--target-image',
                                            default=os.environ.get('TARGET_IMAGE', None),
                                            help='openstack image')
    openstack_parser.add_argument('--target-flavor',
                                            default=os.environ.get('TARGET_FLAVOR', None),
                                            help='openstack flavor')
    openstack_parser.add_argument('-t', '--target-name', help='overrides target name',
                                            default=os.environ.get('TARGET_NAME', ''))
    openstack_parser.add_argument('--target-keyname', help='overrides target name',
                                            default=os.environ.get('TARGET_KEYNAME', ''))
    openstack_parser.add_argument('--target-keyfile', help='overrides target name',
                                            default=os.environ.get('TARGET_KEYFILE', ''))

    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('-s', '--state-path',
                                            default='.wasser_state',
                                            help='path to status file (default: %(default)s)')
    common_parser.add_argument('-d', '--debug',
                                            action='store_true',
                                            help='enter debug mode')

    subparsers = parser.add_subparsers(help="sub-command help", dest='command')
    parser_run = subparsers.add_parser('run',
                                            parents=[common_parser, github_parser, openstack_parser],
                                            help='run help')
    parser_run.add_argument('path',
                                            help='path to script file')
    parser_run.add_argument('-i', '--interactive', action='store_true',
                                            help='run steps interactively')
    parser_run.add_argument('-c', '--continue', action='store_true',
                                            help='continue run')
    parser_run.add_argument('-e', '--extra-vars',
                                            help='extra variables')
    parser_run.add_argument('-k', '--keep-nodes',
                                            action='store_true',
                                            help='cleanup')

    parser_clean = subparsers.add_parser('create',
                                            parents=[common_parser, openstack_parser],
                                            help='create environment: nodes, networks, etc.')
    parser_clean = subparsers.add_parser('delete',
                                            parents=[common_parser, openstack_parser],
                                            help='delete environment: nodes, networks, etc.')

    args = parser.parse_args()

    if args.quiet:
        # in quiet mode we want to suppress all messages 
        pass
    elif args.verbose:
        # when verbose we'd like to see timings
        logging.basicConfig(level=logging.DEBUG,
                datefmt='%Y-%m-%d %H:%M:%S',
                format='%(asctime)s %(levelname)s:%(message)s')
        logging.info("Verbose mode is enabled")
    else:
        # usually we do not want special prefix for the info logging
        # however warning and error message would be great to decorate
        _info = logging.Formatter('%(message)s')
        _default = logging.Formatter('%(levelname)s:%(message)s')
        class InfoFormatter(logging.Formatter):
            def format(self, record):
                if record.levelno == logging.INFO:
                    return _info.format(record)
                else:
                    return _default.format(record)
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(InfoFormatter())
        logging.root.addHandler(h)
        logging.root.setLevel(logging.INFO)


    if not args.command:
        parser.print_help()
        exit(1)

    def handle_signal(signum, frame):
        logging.info(f"Handling signal {signum}")
        # Instead of calling do_delete() and exit() here as follows:
        #   do_delete(args)
        #   exit(1)
        # we just raise SystemExit exception so corresponding catch can do
        # cleanup for us if required.
        raise(SystemExit)
    if args.command in ['run', 'create']:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    if args.command == 'run':
        do_run(args)
    if args.command == 'create':
        do_create(args)
    if args.command == 'delete':
        do_delete(args)
    if args.command == 'provision':
        pass
    exit(0)



import openstack
import traceback

import time

from wasser.state import State

wasser_remote_dir = '/opt/wasser'

def get_connect(args):
    if args.debug:
        openstack.enable_logging(debug=True)
    else:
        openstack.enable_logging(debug=False)
        logging.getLogger("paramiko").setLevel(logging.WARNING)
    conn = openstack.connect(args.openstack_cloud)
    return conn

def make_server_name(template, index):
    """
    Returns name based on the template and numeric index.

    The template can contain one placeholder for the index.
    If template does not contain any placeholder,
    then treat template as a bare name, and return it.

    :param template:    an str with name template, for example: node%00d
    :param index:       an int value with numeric index.
    """
    try:
      target = template % index
    except:
      target = template
    return target

def set_openstack_server_name(conn, state, server_id):
    logging.info("Update name for server %s" % server_id)
    server_spec = state.status['spec']
    server_list = conn.compute.servers()
    openstack_spec = server_spec.get('openstack', {})
    spec_name = openstack_spec.get('name')
    existing_servers = [i.name for i in server_list]
    for n in range(99):
        target = make_server_name(spec_name, n)
        if not target in existing_servers:
            logging.info("Setting server name to %s" % target)
            #conn.compute.update_server(server_id, name=target)
            #s = conn.update_server(server_id, name=target)
            tries=20
            while tries > 0:
                conn.compute.update_server(server_id, name=target)
                time.sleep(10) # wait count to 10
                s=conn.get_server_by_id(server_id)
                if s.name and s.name == target:
                    break
                else:
                    logging.info("Server name is '%s', should be '%s'" %(s.name, target))
                tries -= 1
                logging.info("Left %s tries to rename the server" % tries)
            else:
                raise SystemExit("Cannot set name to '%s' for server '%s'" % (target, server_id))
            return target
    logging.error("Can't allocate name")
    logging.info("TODO: Add wait loop for name allocation")

def set_name(conn, state, server_id, lockname='wasser_set_name.lock'):
    import fcntl
    lockfile = '/tmp/' + lockname
    lock_timeout = 5 * 60
    lock_wait = 2
    logging.debug("Trying to lock file for process " + str(os.getpid()))
    while True:
            try:
                    lock = open(lockfile, 'w')
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    logging.debug(f"File locked for process {os.getpid()}")
                    res = set_openstack_server_name(conn, state, server_id)
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    logging.debug(f'Unlocking for {os.getpid()}')
                    break
            except IOError as err:
                    # print "Can't lock: ", err
                    if lock_timeout > 0:
                            lock_timeout -= lock_wait
                            logging.debug("Process", os.getpid(), "waits", lock_wait, "seconds...")
                            time.sleep(lock_wait)
                    else:
                            raise SystemExit('Unable to obtain file lock: %s' % lockfile)

def create_openstack_server(args, conn, state):
    c = conn.compute
    server_list = c.servers()
    logging.info("Found existing servers: %s" % ", ".join([i.name for i in server_list]))
    server_spec = state.status['spec']
    openstack_spec = server_spec.get('openstack', {})
    image_name = openstack_spec.get('image', None)
    if not image_name:
        raise Executable("image name is not specified")
    logging.info(f"Looking up image {image_name}...")
    image = conn.get_image(image_name)
    if not image:
        raise Exception(f"Cannot find image {image_name}")
    logging.info(f"Found image with id: {image.id}")
    flavor_name = openstack_spec.get('flavor', None)
    if not flavor_name:
        raise Executable("image name is not specified")
    flavor = conn.get_flavor(flavor_name)
    if not flavor:
        raise Exception(f"Cannot find flavor {flavor_name}")
    logging.info(f"Found flavor: {flavor.id}")
    keyname = openstack_spec.get('keyname', None)
    keypair = conn.compute.find_keypair(keyname)
    logging.info("Image:   %s" % image.name)
    logging.info("Flavor:  %s" % flavor.name)
    logging.info("Keypair: %s" % keypair.name)
    userdata = None
    userdata_path = openstack_spec.get('userdata', None)
    if userdata_path:

        if not userdata_path.startswith('/'):
            base = os.path.dirname(__file__)
            if base:
                userdata_path = base + '/' + userdata_path
        with open(userdata_path, 'r') as f:
            userdata=f.read()
    logging.debug("Creating target using flavor %s" % flavor)
    logging.debug("Image=%s" % image.name)
    logging.debug("Data:\n%s" % userdata)
    server_spec = state.status['spec']
    openstack_spec = server_spec.get('openstack', {})
    c = conn.compute

    # if the target is not kind a template, just use it as server name
    target_mask = openstack_spec.get('name')
    username = openstack_spec.get('username', 'root')
    keyfile = openstack_spec.get('keyfile', '.ssh/id_rsa')
    state.update(username=username)
    state.update(keyfile=keyfile)
    rename_server = (target_mask != make_server_name(target_mask, 0))
    if rename_server:
        target_name = state.status['server']['name']
    else:
        target_name = target_mask
    state.update(name=target_name)

    params  = dict(
        name=target_name,
        image=image.id,
        flavor=flavor.id,
        key_name=keypair.name,
        userdata=userdata,
    )

    target_network = openstack_spec.get('network')
    target_floating = openstack_spec.get('floating')

    if target_network:
        params['network'] = target_network

    target = conn.create_server(**params)
    target_id = target.id
    logging.info("Created target: %s" % target.id)
    state.update(id=target.id)
    logging.debug(target)

    fip_id = None
    if rename_server:
        # for some big nodes sometimes rename does not happen
        # and a pause is required
        grace_wait = 5
        logging.info("Graceful wait %s sec before rename..." % grace_wait)
        time.sleep(grace_wait)
        set_name(conn, state, target.id, lockname=target_mask)

    timeout = 8 * 60
    wait = 10
    start_time = time.time()
    while target.status != 'ACTIVE':
      logging.debug("Target status is: %s" % target.status)
      if target.status == 'ERROR':
        # only get_server_by_id can return 'fault' for a server
        x=conn.get_server_by_id(target_id)
        if 'fault' in x and 'message' in x['fault']:
            raise Exception("Server creation unexpectedly failed with message: %s" % x['fault']['message'])
        else:
            raise Exception("Unknown failure while creating server: %s" % x)
      if timeout > (time.time() - start_time):
        logging.info(f'Server {target.name} is not active. Waiting {wait} seconds...')
        time.sleep(wait)
      else:
        logging.error("Timeout occured, was not possible to make server active")
        break
      target=conn.compute.get_server(target_id)

    for i,v in target.addresses.items():
        logging.info(i)
        logging.debug(v)

    ipv4=[x['addr'] for i, nets in target.addresses.items()
        for x in nets if x['version'] == 4][0]
    logging.info(ipv4)
    if target_floating:
        faddr = conn.create_floating_ip(
                network=target_floating,
                server=target,
                fixed_address=ipv4,
                wait=True,
                )
        ipv4 = faddr['floating_ip_address']
        fip_id = faddr['id']
        state.update(fip_id=fip_id)

    state.update(ip=ipv4, name=target.name)


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

    def run(self, command: str, name: str = None) -> None:
        pass


import subprocess

class LocalShell(Shell):
    def __init__(self, user: str):
        self.hostname = 'local'
        self.username = user or os.environ.get('USER')


    def copy_files(self, copy_spec):
        logging.warning('copy files is not supported yet for local host')


    def run(self, command: str, name: str = None) -> None:
        self.log_cmd(command, name)

        p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE)

        stdout_thread = self.start_logging_stdout(p.stdout)
        stderr_thread = self.start_logging_stderr(p.stderr)

        stdout_thread.join()
        stderr_thread.join()

        exit_code = p.wait()
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


    def run(self, command: str, name: str = None) -> None:
        self.log_cmd(command, name)

        client = self.get_client()
        stdin, stdout, stderr = client.exec_command(command)

        stdout_thread = self.start_logging_stdout(stdout)
        stderr_thread = self.start_logging_stderr(stderr)

        stdout_thread.join()
        stderr_thread.join()

        exit_code = stdout.channel.recv_exit_status()
        if exit_code:
            raise Exception(f"Received exit code {exit_code} while running command: {command}")
        logging.info(f"||| exit code: {exit_code}")


class Host():
    def __init__(self, name, addr=None, user=None, keyfile=None):
        self.name = name
        self.addr = addr
        self.user = user
        self.keyfile = keyfile
        if addr:
            self.shell = RemoteShell(addr, user, keyfile)
        else:
            self.shell = LocalShell(user)

    def run(self, command, **kwargs):
        self.shell.run(command, **kwargs)

    def copy_files(self, spec):
        self.shell.copy_files(spec)


def get_host(server):
    server_name = server['name']
    server_addr = server['ip']
    secret_file = server['keyfile']
    user_name = server['username']
    return Host(server_name, server_addr, user_name, secret_file)


def provision_server(state, server):
    env = state.status.get('env')
    server_spec = state.status['spec']

    host = get_host(server)

    logging.info("Provisioning target %s" % host.name)

    target_fqdn = host.name + ".suse.de"
    target_addr = host.addr

    command_list = []
    if server_spec.get('vars') and server_spec['vars'].get('dependencies'):
        command_list += [
            'sudo zypper --no-gpg-checks ref 2>&1',
            'sudo zypper install -y %s 2>&1' % ' '.join(server_spec['vars']['dependencies']),
        ]
    command_list += [
      'echo "' + target_addr + '\t' + target_fqdn + '" | sudo tee -a /etc/hosts',
      'sudo hostname ' + target_fqdn,
      'cat /etc/os-release',
      ]
    copy_spec = [{
        'from': [
            os.path.dirname(__file__) + '/snippets/clone-git-repo.sh',
            os.path.dirname(__file__) + '/snippets/run.cmd',
        ],
        'into': f'{wasser_remote_dir}/bin',
        'mode': '0755',
    }]
    if 'copy' in server_spec:
        # copy should be a list
        copy_spec += server_spec['copy']

    logging.info("Copying files to host...")
    run_routine(host, [f'sudo mkdir -p {wasser_remote_dir} 2>&1',
                    f'sudo chown {host.user}: {wasser_remote_dir} 2>&1'])
    run_routine(host, [f'mkdir -p {wasser_remote_dir}/bin 2>&1'])
    host.copy_files(copy_spec)

    run_routine(host, command_list, env)
    logging.info(f'The server is provisioned and can be accessed by address: {host.addr}')

def run_workflow(status, env):
    """
    Build routine workflow tree and run it through.
    Shell routines defined as a dictionary of a list of steps:

      routines:
        "Some Routine":
            steps:
               - name: first step
               - name: second step
        "Another Routine":
            steps:
               - echo Single step routine
        "Third Routine":
            steps:
               - name: Multi-line command
               - |
                   echo "message to stdout"
                   echo "message to stderr" > /dev/stderr
                   exit 0

    Workflow provide a list of routines to execute:

      workflow:
        routines:
            - "Some Routine"
            - "Another Routing"

    All provided routines will be run in parallel in the given order.
    However particular routines can be run restricted to run
    after others finish.

      workflow:
        routines:
            - name: Some Routine
            - name: Another Routine
              after: Some Routine

    If workflow is empty, all available routines are supposed to be run.

    By default there will be only 1 routine executed at a time, but this
    can be changed by setting the maximum number of parallel routines
    to be executed in threads.

      workflow:
        threads: 2

    """
    server_spec = status['spec']
    workflow = server_spec.get('workflow', {})
    routines = server_spec.get('routines', {})
    workflow_routines = workflow.get('routines', [{'name': _} for _ in routines.keys()])
    parallel_routines = workflow.get('threads', 1)

    for r in workflow_routines:
        if isinstance(r, str):
            name = r
        elif isinstance(r, dict) and 'name' in r:
            name = r.get('name')
        else:
            raise Exception(
                f'Unexpected error while processing routing in workflow: {r}')
        logging.info(f"Using routine '{name}'...")
        if name in routines:
            server = status['server']
            host = get_host(server)
            run_routine(host, routines[name].get('steps', []), env)
        else:
            raise Exception(
                f'Unknown routine "{name}"')


def render_command(command, env=os.environ):
    import jinja2
    return jinja2.Template(command).render(env)


def run_routine(host, steps, env=[]):
    """
    Run routine step by step.

    Each step is represented by str or a dictionary.
    Steps are executed in the given order.

    In case of str it is used to look up of predefined
    module command and if not found it is treated as
    a shell script.
    For example following internal commands can be used:
    :reboot:        reboot current host
    :wait_host:     wait until host is online and can run shell commands.
    :checkout:      clone source code repo into the current directory.

    In case of dict, it has following format:
    :name:      str, name of the step, used for the reference.
    :always:    bool, always run if True, defaults to False.

    If the dict has 'command' keyword it is treated as a shell
    script, additional keywords supported:

    :env:       dict, extra environment variables.

    If the dict has 'checkout' it has subkeys:

    :url:       github repo to clone
    :dir:       destination directory
    :branch:    branch name or reference, for example, main or refs/pull/X/merge
    """
    client = host.shell.get_client()
    errors = []
    for c in steps:
        name = None
        always = False
        if isinstance(c, str):
            if c == 'reboot':
                name = 'rebooting node'
                command = 'sudo reboot &'
            elif c == 'wait_host':
                client = host.shell.connect_client()
                continue
            elif c == 'checkout':
                name = 'clone github repo'
                e = dict(env)
                e.update(
                  github_url = 'https://github.com/aquarist-labs/aquarium',
                  github_dir = '.',
                )
                command = render_command(
                   f"{wasser_remote_dir}/bin/clone-git-repo.sh "
                   "{{ github_dir }} {{ github_url }} {{ github_branch }} 2>&1",
                      env=e)
            else:
                command = render_command(c, env)
        if isinstance(c, dict):
            if 'checkout' in c:
                checkout = c.get('checkout')
                github_url = checkout.get('url', None)
                github_dir = checkout.get('dir', None)
                github_branch = checkout.get('branch', None)

                e = dict(env)
                if github_url:
                    e.update(github_url=github_url)
                if github_dir:
                    e.update(github_dir=github_dir)
                if github_branch:
                    e.update(github_branch=github_branch)
                c.get('name', 'clone github repo')
                command = render_command(
                   f"{wasser_remote_dir}/bin/clone-git-repo.sh "
                   "{{ github_dir }} {{ github_url }} {{ github_branch }} 2>&1",
                      env=e)
            else:
                command = render_command(c.get('command'), env)
                name = c.get('name', None)
            always = c.get('always', False)
        try:
            if errors and not always:
                logging.debug(f'Skipping command: {name}\n{command}')
            else:
                host.run(command, name=name)
        except Exception as e:
            logging.error(e)
            errors.append(e)
    if errors:
        raise errors[0]

def do_provision(args):
    state = State(args)
    provision_server(state, state.status['server'])
    exit(0)

def do_create(args):

    state = State(args)

    conn = get_connect(args)
    try:
        create_openstack_server(args, conn, state)
    except:
        logging.error("Failed to create node")
        traceback.print_exc()
        if not args.debug and not args.keep_nodes:
            logging.info("Cleanup...")
            delete_openstack_server(conn, state)
        exit(1)
    return state

def delete_openstack_server(conn, state):
    target_id = state.status['server']['id']
    fip_id = state.status['server'].get('fip_id')
    logging.info(f"Delete server with id '{target_id}'")
    try:
        target=conn.compute.get_server(target_id)
        conn.compute.delete_server(target.id)
    except Exception as e:
        logging.warning(e)
    if fip_id:
        conn.delete_floating_ip(fip_id)

def do_delete(args):
    state = State(args)
    conn = get_connect(args)
    delete_openstack_server(conn, state)

def do_run(args):
    state = do_create(args)
    try:
        provision_server(state, state.status['server'])
        run_workflow(status=state.status, env=state.status.get('env'))
    except:
        traceback.print_exc()
        if not args.debug and not args.keep_nodes:
            do_delete(args)
        exit(1)
    if not args.keep_nodes:
        do_delete(args)
