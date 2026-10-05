import os
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ui_javascript():
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run(["node", os.path.join(here, "js_check.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
