from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.modules.sales.repository import SalesRepository


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class _ClientDeleteSession:
    def __init__(self, *, active: bool | None, has_sales: bool = False):
        self.active = active
        self.has_sales = has_sales
        self.updated = False
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        if sql.startswith("select ativo from clientes"):
            return _Result(self.active)
        if sql.startswith("select exists("):
            return _Result(self.has_sales)
        if sql.startswith("update clientes set ativo = false"):
            self.updated = True
            self.active = False
            return _Result()
        raise AssertionError(f"SQL nao tratado no teste: {sql}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_delete_client_sem_vendas_faz_exclusao_logica():
    session = _ClientDeleteSession(active=True)
    repo = SalesRepository(session)  # type: ignore[arg-type]

    deleted = await repo.delete_client(10)

    assert deleted is True
    assert session.updated is True
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_delete_client_com_vendas_preserva_historico():
    session = _ClientDeleteSession(active=True, has_sales=True)
    repo = SalesRepository(session)  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="possui vendas"):
        await repo.delete_client(10)

    assert session.updated is False
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_delete_client_inexistente_retorna_false():
    session = _ClientDeleteSession(active=None)
    repo = SalesRepository(session)  # type: ignore[arg-type]

    assert await repo.delete_client(999) is False
    assert session.updated is False
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_delete_client_ja_inativo_e_idempotente():
    session = _ClientDeleteSession(active=False)
    repo = SalesRepository(session)  # type: ignore[arg-type]

    assert await repo.delete_client(10) is True
    assert session.updated is False
    assert session.commits == 0
