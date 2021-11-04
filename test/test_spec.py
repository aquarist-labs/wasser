import pytest

from wasser import state
from wasser import Workflow

@pytest.mark.parametrize(
    [
        'src' , 'obj', 'res'
    ],
    [
        [
            dict(),
            dict(default=0),
            dict(default=0),
        ],
        [
            dict(),
            dict(openstack=dict(name='target', username='root')),
            dict(openstack=dict(name='target', username='root')),
        ],
        [
            dict(openstack=dict(name='target')),
            dict(openstack=dict(username='root')),
            dict(openstack=dict(name='target', username='root')),
        ],
        [
            dict(openstack=dict(username='root', networks=['default'])),
            dict(openstack=dict(networks=[])),
            dict(openstack=dict(username='root', networks=[])),
        ],
        [
            dict(openstack=dict(username='root', networks=None)),
            dict(openstack=dict(networks=['default'])),
            dict(openstack=dict(username='root', networks=['default'])),
        ],

    ]
)
def test_override(src, obj, res):
    assert res == state.override(src, obj)

@pytest.mark.parametrize(
    [ 'conf', 'all_routines', 'run_routines' ],
    [
        [
            dict(openstack=dict(name='target', username='root')),
            list(),
            list(),
        ],
        [
            dict(
                openstack=dict(
                    username='opensuse',
                    image='opensuse-x86',
                ),
                routines=dict(
                    a=dict(
                    )
                )
            ),
            dict(),
            list('a'),
        ],
        [
            dict(
                routines=dict(
                    a=dict(),
                    b=dict(),
                ),
                workflow=dict(
                    routines=list('a')
                )
            ),
            dict(a=dict()),
            list('a'),
        ],
    ]
)
def test_get_routines(conf, all_routines, run_routines):
    s = state.State()
    s.override_status_specs([conf])
    print(s.status)
    w = Workflow(s)
    print(w)
    print('The Workflow:', w.get_workflow())
    print('All Routines:', w.get_routines())
    print('Run Routines:', w.get_run_routines())
    print('All Nodes Specs:', w.get_node_specs())
    assert run_routines == w.get_run_routines()

@pytest.mark.parametrize(
    [ 'conf', 'nodes' ],
    [
        [
            dict(
                openstack=dict(name='target', username='root'),
                routines=dict(
                    a=dict()
                ),
            ),
            [['OpenStackEquipment']],
        ],
        [
            dict(
                libvirt=dict(username='root'),
                routines=dict(
                    a=dict()
                ),
            ),
            [['LibvirtEquipment']],
        ],
        [
            dict(
                libvirt=dict(username='root'),
                routines=dict(
                    a=dict(
                        nodes=[
                            dict(label='alpha', libvirt=dict()),
                            dict(label='beta', openstack=dict()),
                        ]
                    ),
                    b=dict()
                ),
            ),
            [['LibvirtEquipment', 'OpenStackEquipment'],['LibvirtEquipment']],
        ],
    ]
)
def test_nodes_spec(conf, nodes):
    s = state.State()
    print('Status nodes:', s.status.get('nodes'))
    s.override_status_specs([conf])
    s.debug = True
    print('Status spec:', s.status.get('spec'))
    w = Workflow(s)
    print('All Nodes Specs:', w.get_node_specs())
    routines = w.get_run_routines()
    print('Run routines:', routines)
    for i in range(len(routines)):
        r = routines[i]
        specs = w.get_node_specs(r)
        print(f'Node specs: {specs}')
        equip = w.get_equipment(r)
        print(f'Routine {r} Equipment:', [type(_).__name__ for _ in equip])
        assert nodes[i] == [type(_).__name__ for _ in equip]
