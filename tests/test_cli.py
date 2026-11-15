from __future__ import annotations

import json
from pathlib import Path

import pytest

from fraudrules.__main__ import main


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = main(list(args))
    return code, capsys.readouterr().out


def test_list_validate_show(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "list")
    assert code == 0 and "ST-001" in out and "AT-005" in out
    assert run(capsys, "validate")[1].startswith("ok: ")
    code, out = run(capsys, "show", "ST-001")
    assert "1010.313" in out


def test_sql_with_overrides_and_dialect(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "--rule", "ST-001", "--set", "ST-001.window=1d", "sql", "--dialect", "snowflake")
    assert code == 0 and "86400" in out and "MU-001" not in out
    with pytest.raises(SystemExit):
        main(["--set", "nonsense", "sql"])
    with pytest.raises(SystemExit):
        main(["--rule", "ZZ-999", "sql"])
    assert main(["--set", "ST-001.nope=1", "sql"]) == 1


def test_sigma_to_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sigma", "--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.yml"))) == 5


def test_synth_then_run_both_backends(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "synth", "--out", str(tmp_path), "--population", "40", "--days", "35")
    assert code == 0 and json.loads(out)["transactions"] > 0
    planted = json.loads((tmp_path / "planted.json").read_text())
    _, duck_out = run(capsys, "run", "--data", str(tmp_path))
    _, py_out = run(capsys, "run", "--data", str(tmp_path), "--backend", "python")
    assert duck_out == py_out
    hits = {tuple(line.split(",")[::2]) for line in duck_out.strip().splitlines()[1:]}
    for p in planted:
        caught = any((p["rule_id"], row) in hits for row in p["rows"])
        assert caught == (p["kind"] == "positive"), p["rule_id"]
