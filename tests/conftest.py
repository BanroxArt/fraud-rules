from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fraudrules import model as m
from fraudrules.loader import load_pack

RULES = load_pack()
BY_ID = {r.id: r for r in RULES}


@pytest.fixture(scope="session")
def rules() -> list[m.Rule]:
    return RULES
