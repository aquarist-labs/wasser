import logging
import openstack
import os
import time

from typing import Dict
from wasser.state import NodeState, State


class Equipment():
    def __init__(self):
        pass

    def create(self):
        pass

    def delete(self):
        pass

    @staticmethod
    def from_node_spec(state: NodeState, spec):

        libvirt_spec = spec.get('libvirt', {})
        if libvirt_spec:
            return LibvirtEquipment(state, spec)
        openstack_spec = spec.get('openstack', {})
        if openstack_spec:
            return OpenStackEquipment(state, spec)

    @staticmethod
    def available_equipments():
        return ['libvirt', 'openstack']


class LibvirtEquipment(Equipment):
    def __init__(self, state: NodeState, node_spec: Dict):
        self.state = state
        self.spec = node_spec.get('libvirt', {})

class OpenStackEquipment(Equipment):
    """
    spec = state.get('spec', {}).get('opestack', {})
    equip = wasser.equip.OpenStack(spec)
    node = equip.create()
    equip
    """
    conn = None
    def __init__(self, state: NodeState, node_spec: Dict):
        self.state = state
        self.spec = node_spec.get('openstack', {})

    def get_connect(self):
        if self.conn:
            return self.conn

        cloud = self.spec.get('cloud')
        if self.state.state.debug:
            openstack.enable_logging(debug=True)
        else:
            openstack.enable_logging(debug=False)
            logging.getLogger("paramiko").setLevel(logging.WARNING)
        self.conn = openstack.connect(cloud)
        return self.conn


    def create(self):
        logging.debug(f'Create OpenStack equipment with node state {self.state}')
        self.create_server(self.state)

    def delete(self):
        self.delete_server(self.state)

    def create_server(self, node_state: NodeState):
        """OpenStack create_server wrapper"""

        conn = self.get_connect()
        c = self.conn.compute
        server_list = c.servers()
        logging.info("Found existing servers: %s" % ", ".join([i.name for i in server_list]))
        image_name = self.spec.get('image', None)
        if not image_name:
            raise Executable("image name is not specified")
        logging.info(f"Looking up image {image_name}...")
        image = self.conn.get_image(image_name)
        if not image:
            raise Exception(f"Cannot find image {image_name}")
        logging.info(f"Found image with id: {image.id}")
        flavor_name = self.spec.get('flavor', None)
        if not flavor_name:
            raise Executable("image name is not specified")
        flavor = conn.get_flavor(flavor_name)
        if not flavor:
            raise Exception(f"Cannot find flavor {flavor_name}")
        logging.info(f"Found flavor: {flavor.id}")
        keyname = self.spec.get('keyname', None)
        keypair = conn.compute.find_keypair(keyname)
        if not keypair:
            raise Exception(f"Cannot find keypair '{keyname}'")
        logging.info("Image:   %s" % image.name)
        logging.info("Flavor:  %s" % flavor.name)
        logging.info("Keypair: %s" % keypair.name)
        userdata = None
        userdata_path = self.spec.get('userdata', None)
        if userdata_path:

            if not userdata_path.startswith('/'):
                base = os.path.dirname(__file__)
                if base:
                    userdata_path = base + '/../' + userdata_path
            with open(userdata_path, 'r') as f:
                userdata=f.read()
        logging.debug("Creating target using flavor %s" % flavor)
        logging.debug("Image=%s" % image.name)
        logging.debug("Data:\n%s" % userdata)
        c = conn.compute

        # if the target is not kind a template, just use it as server name
        target_mask = self.spec.get('name')
        username = self.spec.get('username', 'root')
        keyfile = self.spec.get('keyfile', '~/.ssh/id_rsa')
        node_state.update(username=username)
        node_state.update(keyfile=keyfile)
        rename_server = (target_mask != self.make_server_name(target_mask, 0))
        if rename_server:
            target_name = 'wasser'
        else:
            target_name = target_mask
        node_state.update(name=target_name)

        params  = dict(
            name=target_name,
            image=image.id,
            flavor=flavor.id,
            key_name=keypair.name,
            userdata=userdata,
        )

        target_network = self.spec.get('network')
        target_floating = self.spec.get('floating')

        if target_network:
            params['network'] = target_network

        try:
            target = conn.create_server(**params)
        #Traceback (most recent call last):
        #  File "/home/jenkins/wasser/v/lib/python3.6/site-packages/openstack/cloud/_utils.py", line 425, in shade_exceptions
        #    yield
        #  File "/home/jenkins/wasser/v/lib/python3.6/site-packages/openstack/cloud/_compute.py", line 913, in create_server
        #    if server.status == 'ERROR':
        # AttributeError: 'NoneType' object has no attribute 'status'
        except AttributeError as e:
            if "no attribute 'status'" in str(e):
                logging.error(f'Failed to create server due to openstack bug')
                logging.warning(f'Going to cleanup server after a second')
                time.sleep(1)
                try:
                    t=conn.compute.get_server(target_name)
                    if t:
                        conn.compute.delete_server(t.id)
                except Exception as ee:
                    if 'Multiple matches found' in str(e):
                        logging.error(f'Cannot delete {target_name} because several server found')
            raise(e)

        target_id = target.id
        logging.info("Created target: %s" % target.id)
        node_state.update(id=target.id)
        logging.debug(target)

        fip_id = None
        if rename_server:
            # for some big nodes sometimes rename does not happen
            # and a pause is required
            grace_wait = 5
            logging.info("Graceful wait %s sec before rename..." % grace_wait)
            time.sleep(grace_wait)
            self.set_name(target.id, lockname=target_mask)

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
            node_state.update(fip_id=fip_id)

        node_state.update(ip=ipv4, name=target.name)


    def delete_server(self, node_state):
        logging.debug(f'Delete node {node_state}')
        conn = self.get_connect()
        target_id = node_state.data.get('id')
        fip_id = node_state.data.get('fip_id')
        logging.info(f"Delete server with id '{target_id}'")
        try:
            target=conn.compute.get_server(target_id)
            conn.compute.delete_server(target.id)
        except Exception as e:
            logging.warning(e)
        if fip_id:
            conn.delete_floating_ip(fip_id)

    @staticmethod
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

    def set_server_name(self, server_id, template):
        """
        Go through the range of possible names, skip the name if present
        or set it the server with  given id.
        """
        logging.info("Update name for server %s" % server_id)
        server_list = self.conn.compute.servers()
        existing_servers = [i.name for i in server_list]
        for n in range(99):
            target = self.make_server_name(template, n)
            if not target in existing_servers:
                logging.info("Setting server name to %s" % target)
                #self.conn.compute.update_server(server_id, name=target)
                #s = self.conn.update_server(server_id, name=target)
                tries=20
                while tries > 0:
                    self.conn.compute.update_server(server_id, name=target)
                    time.sleep(10) # wait count to 10
                    s = self.conn.get_server_by_id(server_id)
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

    def set_name(self, server_id, lockname='wasser_set_name.lock'):
        """
        Set name for server id using
        """
        template = self.spec.get('name')
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
                        res = self.set_server_name(server_id, template)
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
