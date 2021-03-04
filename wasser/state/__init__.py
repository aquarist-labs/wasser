import logging
import os
import json
import yaml

server_spec = {
    'name':     'target%02d',
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

class State():
    status = {
      'server': {
        'name': 'ci-target',
        'id': None,
        'ip': None,
      },
      'env': {},
      'spec': server_spec,
    }
    def __init__(self, args):
        self.args = args
        if args.path:
            self.load_spec_file(args.path)
        self.status['env'].update(
            github_url=args.github_url,
            github_branch=args.github_branch,
        )
    def server_spec(self):
        return self.status['spec']

    def load_spec_file(self, spec_path):
        with open(spec_path, 'r') as f:
            logging.info(f'Reading spec from file: {spec_path}')
            if spec_path.endswith('.yaml') or spec_path.endswith('.yml'):
                server_spec = yaml.safe_load(f)
            else:
                server_spec = json.load(f)
            def override_dict(obj, key, env=None, default=None):
                if env and env in os.environ:
                    obj[key] = os.environ.get(env, default)
                elif default:
                    obj[key] = default
            openstack_spec = server_spec.get('openstack')
            if not openstack_spec:
                openstack_spec = server_spec['openstack'] = {}
            override_dict(openstack_spec, 'keyfile',   default=self.args.target_keyfile)
            override_dict(openstack_spec, 'keyname',   default=self.args.target_keyname)
            override_dict(openstack_spec, 'image',     default=self.args.target_image)
            override_dict(openstack_spec, 'name',      default=self.args.target_name)
            override_dict(openstack_spec, 'flavor',    env='TARGET_FLAVOR')
            override_dict(openstack_spec, 'network',   env='TARGET_NETWORK')
            override_dict(openstack_spec, 'floating',  env='TARGET_FLOATING')
            self.status['spec'] = server_spec
        logging.debug(f'State: {self.status}')
    def update(self, **kwargs):
        if kwargs:
            logging.debug(kwargs)
        for k,v in kwargs.items():
            logging.debug('override %s with %s' % (k,v))
            self.status['server'][k] = v
        logging.debug("Saving status to '%s'" % self.args.state_path)
        with open(self.args.state_path, 'w') as f:
            json.dump(self.status, f, indent=2)

