"""Optional Node contract verification, no browser or network."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_surge_dom_safety_and_replay():
    r = subprocess.run(
        ["node", "tests/dashboard_surge.test.cjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
