import pytest

from wasser import state


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


