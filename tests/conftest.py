"""Configuração global do pytest.

- garante que o pacote `app` é importável independente do cwd;
- fornece uma fixture `session_factory` com SQLite async em arquivo temporário
  (`aiosqlite`) para exercitar a camada de repositório/serviço sem Postgres.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_BACK_ROOT = Path(__file__).resolve().parent.parent
if str(_BACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACK_ROOT))


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker]:
    """Engine SQLite em arquivo (compatível com múltiplas conexões async)."""
    from app.database import Base
    from app.modules.captures import models  # noqa: F401 — registra capture_jobs/images
    from app.modules.captures import modelos_universais  # noqa: F401 — registra modelos_3d_universais

    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        await engine.dispose()
