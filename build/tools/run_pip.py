import runpy
import sys


bootstrap = sys.argv.pop(1)
sys.path.insert(0, bootstrap)
sys.argv[0] = "pip"
runpy.run_module("pip", run_name="__main__")
