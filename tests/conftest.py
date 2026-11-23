import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["STAGE_DELAY_MS"] = "0"
os.environ["LLM_PROVIDER"] = "none"
os.environ["SEED_HISTORY"] = "0"
for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own empty DB containing only the vendor master."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app import seed
    seed.init_app(seed_runs=False)
    yield
