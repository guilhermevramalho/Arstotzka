import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
TESTS_UNIT = Path(__file__).resolve().parent
for path in (str(SRC), str(TESTS_UNIT)):
    if path not in sys.path:
        sys.path.insert(0, path)
