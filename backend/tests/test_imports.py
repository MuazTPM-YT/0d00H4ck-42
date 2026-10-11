import subprocess
import sys

import pytest

MODULES = [
    "analytics",
    "dispatch",
    "finance",
    "inventory",
    "orders",
    "production",
    "quality",
    "tracking",
    "workforce",
]


# scripts import services in their own order; each must load cold, with no import cycle
@pytest.mark.parametrize("module", MODULES)
def test_service_imports_on_its_own(module):
    code = f"import app.modules.{module}.service"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
