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
import traceback
import time
import signal
import sys

import json

from wasser.shell import RemoteShell, LocalShell
from wasser.state import State, NodeState
from wasser.equip import Equipment

def main():
    parser = argparse.ArgumentParser(
            description='wasser - workflow automation software for shell executable routines')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-q', '--quiet', action='store_true', help='subpress logging')
    parser.add_argument('--pdb-attach', default=0, help='listen on port for pdb-attach, use with: python -m pdb_attach PID PORT')


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
    openstack_parser.add_argument('--target-floating',
                                        default=os.environ.get('TARGET_FLOATING', None),
                                        help='openstack floating')
    openstack_parser.add_argument('--target-network',
                                        default=os.environ.get('TARGET_NETWORK', None),
                                        help='openstack network')
    openstack_parser.add_argument('-t', '--target-name', help='overrides target name',
                                            default=os.environ.get('TARGET_NAME', ''))
    openstack_parser.add_argument('--target-keyname', help='overrides target name',
                                            default=os.environ.get('TARGET_KEYNAME', ''))
    openstack_parser.add_argument('--target-keyfile', help='overrides target name',
                                            default=os.environ.get('TARGET_KEYFILE', ''))
    openstack_parser.add_argument('--target-username', help='overrides target username',
                                            default=os.environ.get('TARGET_USERNAME', ''))

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
    parser_run.add_argument('-b', '--breakpoint',
                                            action='append',
                                            default=[],
                                            help='break at step')
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

    if args.pdb_attach:
        import pdb_attach
        pdb_attach.listen(args.pdb_attach)
        logging.info(f'Enabled pdb-attach module, command to attach the process: python -m pdb_attach {os.getpid()} {args.pdb_attach}')

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


wasser_remote_dir = '/opt/wasser'


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
    routine = Routine([host], env)
    routine.run([f'sudo mkdir -p {wasser_remote_dir} 2>&1',
                    f'sudo chown {host.user}: {wasser_remote_dir} 2>&1'])
    routine.run([f'mkdir -p {wasser_remote_dir}/bin 2>&1'])
    host.copy_files(copy_spec)

    routine.run(command_list)
    logging.info(f'The server is provisioned and can be accessed by address: {host.addr}')


class Workflow():
    """
    Workflow provide a list of routines to execute:

      workflow:
        routines:
            - "Some Routine"
            - "Another Routing"

    Where routines are defined as a dictionary of a list of steps:

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

    Each routine can be run on several nodes. For example:

    routines:
      "Four Nodes":
          nodes:
            - label: [mgr]
            - label: [mgr]
            - label: [cli]
            - label: [cli]
          steps:
            # this step will run on both node with 'mgr' label
            - name: print host name
              command: hostname -f
              onall: mgr
            # the next step will run only on one of the 'cli' node
            - name: print host name
              command: hostname -f
              onany: cli

    """

    def __init__(self, state, breaks=[]):
        self.state = state
        self.env = state.status.get('env')
        self.breaks = breaks

    def equip(self):
        spec = self.state.status.get('spec')
        workflow = spec.get('workflow', {})
        routines = spec.get('routines', {})
        workflow_routines = workflow.get('routines', [{'name': _}
						for _ in routines.keys()])

    def get_routine_hosts(self, routine_index):
        nodes_data = self.state.status.get('nodes')
        hosts = [get_host(_) for _ in nodes_data[routine_index]]
        return hosts

    def equip_keywords(self):
        return ['libvirt', 'openstack']

    def get_routine_node_specs(self, routine_spec):
        common_spec = self.state.status.get('spec')
        def override_node_spec(common_spec, node_spec):
            equip_keyword = next((_ for _ in Equipment.available_equipments()
                                    if _ in node_spec), None)
            if equip_keyword:
                a_spec = { equip_keyword: common_spec.get(equip_keyword, {}) }
                b_spec = { equip_keyword: node_spec.get(equip_keyword) }
                return state.override(a_spec, b_spec)
            else:
                return { _: common_spec.get(_)
                                for _ in Equipment.available_equipments()
                                    if _ in common_spec }
                
        if 'nodes' in routine_spec:
            node_specs = [override_node_spec(common_spec, _)
                            for _ in routine_spec.get('nodes', [])]
        else:
            # if no nodes declaired we have only one node
            node_specs = [override_node_spec(common_spec, {})]
        return node_specs

    def get_node_specs(self, routine=None):
        """
        Return node specs for routine, if routine is not provided
        then return specs for all nodes of all running routines.
        TODO.
        So if routine does not have 'nodes' then return single node,
        with default spec, openstack has a priority.
        """
        common_spec = self.state.status.get('spec')
        workflow = common_spec.get('workflow', {})
        routines = common_spec.get('routines', {})
        if routine:
            specs = self.get_routine_node_specs(routines.get(routine, {}))
            return specs
        else:
            specs = [self.get_routine_node_specs(routines.get(_, {}))
                        for _ in self.get_run_routines()]
            return specs


    def provision_servers(self):
        nodes_data = self.state.status['nodes']
        for routine_nodes_data in nodes_data:
            for _ in routine_nodes_data:
                provision_server(self.state, _)

    def access_banner(self):
        nodes_data = self.state.status.get('nodes', [])
        rr = self.get_run_routines()
        for i in range(len(rr)):
            first_node = nodes_data[i][0]
            addr = first_node.get('ip', None)
            user = first_node.get('username', None)
            skey = first_node.get('keyfile', None)
            if addr:
                ssh = ['ssh']
                if skey:
                    ssh += [f'-i {skey}']
                if user:
                    ssh += [f'{user}@{addr}']
                else:
                    ssh += [f'{addr}']
                ssh_access = ' '.join(ssh)

                return f'The first server for routine [{rr[i]}] can be accessed using: {ssh_access}'
            else:
                return ''

    def get_workflow(self):
        spec = self.state.status.get('spec')
        return spec.get('workflow', {})

    def get_routines(self):
        spec = self.state.status.get('spec')
        return spec.get('routines', {})


    def get_equipment(self, routine_name=None):
        nodes_data = self.state.status.get('nodes')
        run_routines = self.get_run_routines()
        # init node states if it is not yet
        if not nodes_data:
            nodes_data = [[] for _ in run_routines]
            self.state.status['nodes'] = nodes_data
        logging.debug(f'Nodes Data: {nodes_data}')
        run_equip = []
        for i in range(len(run_routines)):
            if routine_name and routine_name != run_routines[i]:
                continue
            logging.debug(f'Getting equipment for routine "{run_routines[i]}"')
            specs = self.get_node_specs(run_routines[i])
            if not nodes_data[i]:
                nodes_data[i] = [{} for _ in specs]
            equip = [Equipment.from_node_spec(
                            NodeState(self.state, nodes_data[i][x]),
                            specs[x])
                                for x in range(len(specs))]
            run_equip += equip
        return run_equip


    def create_nodes(self):
        for e in self.get_equipment():
            logging.debug(f'Creating equipment {e}')
            e.create()

    def delete_nodes(self):
        for e in self.get_equipment():
            logging.debug(f'Deleting equipment {e}')
            e.delete()

    def get_run_routines(self):
        """Return list of names of run routines"""
        spec = self.state.status.get('spec')
        workflow = spec.get('workflow', {})
        routines = spec.get('routines', {})
        workflow_routines = workflow.get('routines', [{'name': _}
						for _ in routines.keys()])
        names = [_ if isinstance(_, str) else _.get('name')
 						for _ in workflow_routines]
        return names

    def run(self):
        """
        Build routine workflow tree and run it through.
        """
        server_spec = self.state.status.get('spec')
        workflow = server_spec.get('workflow', {})
        routines = server_spec.get('routines', {})
        workflow_routines = workflow.get('routines', [{'name': _} for _ in routines.keys()])
        parallel_routines = workflow.get('threads', 1)

        self.provision_servers()

        for i in range(len(workflow_routines)):
            r = workflow_routines[i]
            if isinstance(r, str):
                name = r
            elif isinstance(r, dict) and 'name' in r:
                name = r.get('name')
            else:
                raise Exception(
                    f'Unexpected error while processing routing in workflow: {r}')
            logging.info(f"Using routine '{name}'...")
            if name in routines:
                steps = routines[name].get('steps', [])
                hosts = self.get_routine_hosts(i)
                routine = Routine(hosts, self.env, self.breaks)
                routine.run(steps)
            else:
                raise Exception(
                    f'Unknown routine "{name}"')


def render_command(command:str , env=os.environ) -> str:
    import jinja2
    return jinja2.Template(command).render(env)

class Routine():

    def __init__(self, nodes, env=[], breaks=[]):
        self.host = nodes[0]
        self.env = env
        self.breakpoints = breaks

    def run(self, steps):
        """
        Run routine step by step.

        Each step is represented by str or a dictionary.
        Steps are executed in the given order.

        In case of str it is used to look up of predefined
        module command and if not found it is treated as
        a shell script.
        For example following internal commands can be used:
        :reboot:        reboot current host.
        :reconnect:     reconnect host client.
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
        host = self.host
        client = host.shell.get_client()
        errors = []
        for c in steps:
            name = None
            always = False
            timeout = None
            if isinstance(c, str):
                if c in self.breakpoints:
                    logging.info(f"Breakpoint at step '{c}'")
                    break
                if c == 'reboot':
                    name = 'rebooting node'
                    command = 'sudo reboot &'
                elif c == 'wait_host':
                    client = host.shell.connect_client()
                    continue
                elif c == 'reconnect':
                    client = host.shell.connect_client()
                    continue
                elif c == 'checkout':
                    name = 'clone github repo'
                    timeout = 15*60
                    e = dict(self.env)
                    e.update(
                      github_url = 'https://github.com/aquarist-labs/aquarium',
                      github_dir = '.',
                    )
                    command = render_command(
                       f"{wasser_remote_dir}/bin/clone-git-repo.sh "
                       "{{ github_dir }} {{ github_url }} {{ github_branch }}",
                          env=e)
                else:
                    command = render_command(c, self.env)
            if isinstance(c, dict):
                if 'checkout' in c:
                    checkout = c.get('checkout')
                    timeout = 15*60
                    github_url = checkout.get('url', None)
                    github_dir = checkout.get('dir', None)
                    github_branch = checkout.get('branch', None)

                    e = dict(self.env)
                    if github_url:
                        e.update(github_url=github_url)
                    if github_dir:
                        e.update(github_dir=github_dir)
                    if github_branch:
                        e.update(github_branch=github_branch)
                    c.get('name', 'clone github repo')
                    command = render_command(
                       f"{wasser_remote_dir}/bin/clone-git-repo.sh "
                       "{{ github_dir }} {{ github_url }} {{ github_branch }}",
                          env=e)
                else:
                    command = render_command(c.get('command'), self.env)
                    name = c.get('name', None)
                always = c.get('always', False)
            try:
                if name in self.breakpoints:
                    logging.info(f"Breakpoint at step '{name}'")
                    break
                if errors and not always:
                    logging.debug(f'Skipping command: {name}\n{command}')
                else:
                    host.run(command, name=name, timeout=timeout)
            except Exception as e:
                logging.error(e)
                errors.append(e)
        if errors:
            raise errors[0]

def do_provision(args):
    state = State().with_args(args)
    provision_server(state, state.status['server'])
    exit(0)

def do_create(args):

    state = State().with_args(args)
    workflow = Workflow(state, breaks=args.breakpoint)
    try:
        workflow.create_nodes()
    except:
        logging.error("Failed to create nodes")
        traceback.print_exc()
        if not args.debug and not args.keep_nodes:
            logging.info("Cleanup...")
            workflow.delete_nodes()
        exit(1)
    return workflow


def do_delete(args):
    state = State().load(args)
    workflow = Workflow(state)
    workflow.delete_nodes()

def do_run(args):
    workflow = do_create(args)
    error_code = 0
    try:
        workflow.run()
    except:
        traceback.print_exc()
        error_code = 1
    if args.keep_nodes:
        banner = workflow.access_banner()
        if banner:
            logging.info(banner)
    else:
        do_delete(args)
    if error_code:
        exit(error_code)
