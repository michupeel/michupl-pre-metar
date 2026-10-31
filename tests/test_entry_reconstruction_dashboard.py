"""Optional Node DOM contract verification, explicitly separate from visual QA."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node unavailable; synthetic DOM check optional"
)
def test_additive_dashboard_replay_and_null_contract():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/dashboard_entry_reconstruction.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
