from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def create_all() -> None:
    from .modules.captures import models  # noqa: F401 — registra capture_jobs/capture_images
    from .modules.captures import modelos_universais  # noqa: F401 — registra modelos_3d_universais

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
