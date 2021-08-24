import logging
import os
import json
import yaml
import copy

from pathlib import Path
from typing import Dict

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

status_default_data =  {
      'server': {
        'name': 'wassertank',
        'id': None,
        'ip': None,
      },
      # routine nodes dictionary
      'nodes': [],
      'env': {},
      'spec': default_server_spec,
    }


class State():
    status = None
    debug = False
    def __init__(self, status=None):
        if status:
            self.status = copy.deepcopy(status)
            logging.debug(self.status)
        else:
            self.status = copy.deepcopy(status_default_data)

    @staticmethod
    def from_args(args):
        return State().with_args(args)

    def with_args(self, args):
        self.args = args
        self.debug = args.debug
        if hasattr(args, 'path') and args.path:
            self.load_spec(args.path)
            self.override_openstack_spec(self.args)

            self.status['env'].update(
                github_url=args.github_url,
                github_branch=args.github_branch,
            )
        else:
            self.load_state(args.state_path)
        logging.debug(f'State: {self.status}')
        return self

    def load(self, args):
        self.args = args
        self.debug = args.debug
        self.load_state(args.state_path)
        logging.debug(f'State: {self.status}')
        return self


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

    @staticmethod
    def _override_openstack_spec(spec, args):
        def override_key(obj, key, default=None):
            if default:
                obj[key] = default

        _spec = spec.get('openstack', {})

        openstack_params = {
            'cloud':     args.openstack_cloud,
            'flavor':    args.target_flavor,
            'floating':  args.target_floating,
            'image':     args.target_image,
            'keyfile':   args.target_keyfile,
            'keyname':   args.target_keyname,
            'name':      args.target_name,
            'network':   args.target_network,
            'username':  args.target_username,
        }
        for k, v in openstack_params.items():
            override_key(_spec, k, v)
        spec['openstack'] = _spec
        return _spec

    def override_openstack_spec(self, args):
        self._override_openstack_spec(self.status.get('spec'), args)

    def read_spec_files(self, paths):
        for path in paths:
            if os.path.exists(path):
                logging.debug(f'Reading spec from file: {path}')
                yield self.read_spec(path)

            
    def load_spec(self, spec_path):
        spec_paths = [
            os.path.expanduser('~/.wasser/config.yaml'),
            '.wasser.yaml',
            spec_path
        ]
        
        specs = self.read_spec_files(spec_paths)
        logging.debug(f'Overriding status...')
        self.override_status_specs(specs)


    def override_status_specs(self, specs):
        spec = default_server_spec
        for s in specs:
            spec = override(spec, s)
        self.status['spec'] = spec
        return self


    def load_state(self, path):
        with open(path, 'r') as f:
            self.status = json.load(f)
            logging.debug(self.status)

    def save(self):
        logging.debug("Saving status to '%s'" % self.args.state_path)
        with open(self.args.state_path, 'w') as f:
            json.dump(self.status, f, indent=2)


class NodeState():
    # node data reference object
    data: Dict = None
    # wasser root state
    state: State = None
    def __init__(self, state: State, data: Dict):
        self.data = data
        self.state = state

    def update(self,
                    **kwargs):
        if kwargs:
            logging.debug(kwargs)
        for k,v in kwargs.items():
            logging.debug('override %s with %s' % (k,v))
            self.data[k] = v
        self.state.save()
