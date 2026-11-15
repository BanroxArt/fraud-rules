from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compiled_artifacts_are_current() -> None:
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_compiled.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
