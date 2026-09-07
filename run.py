"""Compatible launcher name for existing portable installations."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_app import main

if __name__ == '__main__': main()
