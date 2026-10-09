from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def _database():
    """集成测试会走持久化节点（质控结果/预问诊记录），这里统一建库。"""
    from backend.infra.db import db

    db.connect()
    yield db
    db.close()
