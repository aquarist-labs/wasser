import wasser
import sys

if sys.argv[0].endswith("__main__.py"):
    import os.path
    executable = os.path.basename(sys.executable)
    sys.argv[0] = executable + " -m wasser"
    del os

wasser.main()
