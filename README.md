# wasser

Use case with openstack:

1. Make sure you have openstack clouds config defined

2. `pip install git+https://github.com/aquarist-labs/wasser`

3. `wa run path-to-workflow-config.yaml`


## Wasser Config Files

### Example


```
routines:
  Routine1:
    steps:
      - hostname -f

openstack:
  flavor: s1-8
  image: Ubuntu 20.10
  keyfile: ~/.ssh/id_rsa
  keyname: default
  username: ubuntu
```

Config file load order:

- ~/.wasser/config.yaml
- .wasser.yaml
- run argument

