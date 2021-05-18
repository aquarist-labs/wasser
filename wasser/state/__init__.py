import logging
import os
import json
import yaml
import copy

default_server_spec = {
    'openstack': {
        'name':     'wa%02d',
        'image':    None,
        'flavor':   None,
        'keyfile':  None,
        'keyname':  'wasser',
        'username': 'root',
        'userdata': 'openstack/user-data.yaml',
        'network':  None,
        'floating': None,
        'networks': ['Ext-Net'],
    }
}


def override(src, data):
    """
    Returns dict based on src dict overridden with the data.

    """
    res = copy.deepcopy(src)
    if isinstance(data, dict):
        for key, value in data.items():
            if key in res:
                if isinstance(res[key], dict):
                    res[key] = override(res[key], value)
                else:
                    res[key] = copy.deepcopy(value)
            elif isinstance(value, dict):
                res[key] = copy.deepcopy(value)
            else:
                res[key] = value
    return res


class State():
    status = {
      'server': {
        'name': 'wassertank',
        'id': None,
        'ip': None,
      },
      'env': {},
      'spec': default_server_spec,
    }

    def __init__(self, args):
        self.args = args
        if hasattr(args, 'path') and args.path:
            self.load_spec_file(args.path)

            self.status['env'].update(
                github_url=args.github_url,
                github_branch=args.github_branch,
            )
        else:
            self.load_state(args.state_path)

    def server_spec(self):
        return self.status['spec']


    def read_spec(self, path):
        data = None
        with open(path, 'r') as f:
            if path.endswith('.json'):
                data = json.load(f)
            else:
                data = yaml.safe_load(f)
        return data

    def load_spec_file(self, spec_path):
        home_config_path = os.path.expanduser('~/.wasser/config.yaml')
        local_config_path = '.wasser.yaml'

        spec = default_server_spec

        for path in [ home_config_path, local_config_path ]:
            if os.path.exists(path):
                spec = override(spec, self.read_spec(path))

        logging.info(f'Reading spec from file: {spec_path}')
        server_spec = override(spec, self.read_spec(spec_path))

        def override_key(obj, key, default=None):
            if default:
                obj[key] = default

        openstack_spec = server_spec.get('openstack', {})
        override_key(openstack_spec, 'cloud',     self.args.openstack_cloud)
        override_key(openstack_spec, 'flavor',    self.args.target_flavor)
        override_key(openstack_spec, 'floating',  self.args.target_floating)
        override_key(openstack_spec, 'image',     self.args.target_image)
        override_key(openstack_spec, 'keyfile',   self.args.target_keyfile)
        override_key(openstack_spec, 'keyname',   self.args.target_keyname)
        override_key(openstack_spec, 'name',      self.args.target_name)
        override_key(openstack_spec, 'network',   self.args.target_network)
        override_key(openstack_spec, 'username',  self.args.target_username)
        server_spec['openstack'] = openstack_spec
        self.status['spec'] = server_spec
        logging.debug(f'State: {self.status}')

    def load_state(self, path):
        with open(path, 'r') as f:
            self.status = json.load(f)
            logging.debug(self.status)

    def update(self, **kwargs):
        if kwargs:
            logging.debug(kwargs)
        for k,v in kwargs.items():
            logging.debug('override %s with %s' % (k,v))
            self.status['server'][k] = v
        logging.debug("Saving status to '%s'" % self.args.state_path)
        with open(self.args.state_path, 'w') as f:
            json.dump(self.status, f, indent=2)

    def access_banner(self):
        addr = self.status.get('server', {}).get('ip', None)
        user = self.status.get('server', {}).get('username', None)
        skey = self.status.get('server', {}).get('keyfile', None)
        if addr:
            ssh = ['ssh']
            if skey:
                ssh += [f'-i {skey}']
            if user:
                ssh += [f'{user}@{addr}']
            else:
                ssh += [f'{addr}']
            ssh_access = ' '.join(ssh)

            return f'The server can be accessed using: {ssh_access}'
        else:
            return ''
