"""Testes de unidade: o motor puro, sem API e sem banco.

Rodam com `pytest tests/unit` sem nada de pé. O src/ entra no caminho de
import porque o motor é importado direto (é código Python puro).
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
TESTS_UNIT = Path(__file__).resolve().parent

for path in (str(SRC), str(TESTS_UNIT)):
    if path not in sys.path:
        sys.path.insert(0, path)
