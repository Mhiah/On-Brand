import sys
from pathlib import Path

# Make the plugin importable as a package named ``on_brand`` for the core tests.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
