import pytest
import sys
import os

if __name__ == "__main__":
    # Add nerves/workers/trading to sys.path to resolve internal modules correctly
    sys.path.insert(0, os.path.abspath("nerves/workers/trading"))
    
    print("Running pytest on test_pattern_challenger.py programmatically...")
    # Run pytest and capture results
    retcode = pytest.main([
        "-v",
        "nerves/workers/trading/tests/unit/test_pattern_challenger.py"
    ])
    print(f"Pytest exit code: {retcode}")
    sys.exit(retcode)
