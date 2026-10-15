"""pytest 全局夹具：测试用独立临时台账数据库。

通过 monkeypatch 覆盖 config.LEDGER_DB，让所有 ledger 函数
自然落到临时库上——比 mock 模块属性更接近真实调用路径。
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.detection import ledger  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每个测试用独立的临时数据库文件，并让全局 config 指向它。"""
    db = tmp_path / "test_ledger.db"
    ledger.init_db(db)
    monkeypatch.setattr(config, "LEDGER_DB", db)
    yield db
