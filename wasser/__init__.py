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

def _create_openstack_server(args, conn, state, image, flavor, key_name, user_data=None):
    logging.debug("Creating target using flavor %s" % flavor)
    logging.debug("Image=%s" % image.name)
    logging.debug("Data:\n%s" % user_data)
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
        key_name=key_name,
        userdata=user_data,
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
    try:
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
        provision_server(state)
    except:
        logging.error("Failed to create node")
        traceback.print_exc()
        if not args.debug and not args.keep_nodes:
            logging.info("Cleanup...")
            if target_floating:
                if fip_id:
                    conn.delete_floating_ip(fip_id)
            c.delete_server(target.id)
        exit(1)

class Host():
    def __init__(self, name='localhost', user='root', identity=None):
        self.client = None
        self.username = user
        self.hostname = name
        self.identity = os.path.expanduser(identity)

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
        if copy_spec:
            with self.client.open_sftp() as sftp:
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

def provision_hst(host, status, env):
    client = host.get_client()
    server_spec = status['spec']

    target_fqdn = status['server']['name'] + ".suse.de"
    target_addr = status['server']['ip']

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
    host_run(host, [f'sudo mkdir -p {wasser_remote_dir} 2>&1',
                    f'sudo chown {host.username}: {wasser_remote_dir} 2>&1'])
    host_run(host, [f'mkdir -p {wasser_remote_dir}/bin 2>&1'])
    host.copy_files(copy_spec)

    host_run(host, command_list, env)
    routines = server_spec.get('routines', {})
    for name in routines.keys():
        logging.info(f"Using routine '{name}'...")
        host_run(host, routines[name].get('steps', []), env)


def render_command(command, env=os.environ):
    import jinja2
    return jinja2.Template(command).render(env)


def host_run(host, command_list, env=[]):
    client = host.get_client()
    for c in command_list:
      name = None
      if isinstance(c, str):
          if c == 'reboot':
              name = 'rebooting node'
              command = 'sudo reboot &'
          elif c == 'wait_host':
              client = host.connect_client()
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
      if name:
          print(f"=== {name}")
      for i in command.split('\n'):
          print("+ " + i)
      stdin, stdout, stderr = client.exec_command(command)
      while True:
        l = stdout.readline()
        if not l:
          break
        print(">>> " + l.rstrip())
      exit_code = stdout.channel.recv_exit_status()
      if exit_code:
          raise Exception(f"Received exit code {exit_code} while running command: {command}")
      print(f"||| exit code: {exit_code}")


def provision_server(state):
    ip = state.status['server']['ip']
    secret_file = state.status['server']['keyfile']
    user_name = state.status['server']['username']
    host = Host(ip, user_name, secret_file)
    host.connect_client()
    provision_hst(host, status=state.status, env=state.status.get('env'))

def do_provision(args):
    with open(args.state_path, 'r') as f:
        status = json.load(f)
        logging.debug(status)
    target_id = status['server']['id']
    target_ip = status['server']['ip']
    user_name = status['server']['username']
    secret_file = status['server']['keyfile']
    logging.info("Provisioning target %s" % status['server']['name'])
    host = Host(ip, user_name, secret_file)
    host.connect_client()
    provision_hst(host, status=status, env=status.get('env'))
    exit(0)

def do_create(args):

    def handle_signal(signum, frame):
        print("Handling signal", signum)
        # Instead of calling do_delete() we raise SystemExit exception so
        # corresponding catch can do cleanup for us if required
        raise(SystemExit)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    conn = get_connect(args)
    c = conn.compute
    server_list = c.servers()
    state = State(args)
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
    _create_openstack_server(args, conn, state, image, flavor, keypair.name, userdata)
    pass

def delete_openstack_server(conn, target_id):
    logging.info(f"Delete server with id '{target_id}'")
    try:
        target=conn.compute.get_server(target_id)
        conn.compute.delete_server(target.id)
    except Exception as e:
        logging.warning(e)

def do_delete(args):
    with open(args.state_path, 'r') as f:
        status = json.load(f)
        logging.debug(status)
    conn = get_connect(args)
    target_id = status['server']['id']
    fip_id = status['server'].get('fip_id')
    delete_openstack_server(conn, target_id)
    if fip_id:
        conn.delete_floating_ip(fip_id)

def do_run(args):
    do_create(args)
    if not args.keep_nodes:
        do_delete(args)
