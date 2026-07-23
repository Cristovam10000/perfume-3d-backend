from __future__ import annotations

import pytest

from app.modules.sales.repository import SalesRepository
from app.modules.sales.schemas import ProductCreateIn


class _Result:
    def __init__(self, rows=None, scalar=None):
        self.rows = list(rows or [])
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        assert self.scalar is not None
        return self.scalar

    def scalar_one_or_none(self):
        return self.rows[0]["id"] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _ProductSession:
    """Sessão fake que registra os parâmetros do INSERT de produto."""

    def __init__(self, *, existing_id: int | None = None):
        self.existing_id = existing_id
        self.insert_params: dict | None = None
        self.update_params: dict | None = None
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        if sql.startswith("select id from produtos where sync_request_id"):
            rows = [] if self.existing_id is None else [{"id": self.existing_id}]
            return _Result(rows=rows)
        if sql.startswith("insert into produtos"):
            self.insert_params = dict(params)
            return _Result(scalar=101)
        if sql.startswith("update produtos set nome"):
            self.update_params = dict(params)
            return _Result(rows=[{"id": params["id"]}])
        if "from produtos p" in sql and "where p.id = :id" in sql:
            source = self.update_params or self.insert_params or {}
            return _Result(
                rows=[
                    {
                        "id": params["id"],
                        "nome": source.get("nome", "teste"),
                        "categoria": source.get("categoria", "Perfume"),
                        "preco_base": source.get("preco_base", 350.0),
                        "custo": source.get("custo", 300.0),
                        "estoque": source.get("estoque", 2),
                        "estoque_minimo": source.get("estoque_minimo", 1),
                        "volume_ml": source.get("volume_ml", 100),
                        "frasco_color_value": source.get(
                            "frasco_color_value", 4291509883
                        ),
                        "possui_modelo_3d": False,
                        "caminho_arquivo_modelo": None,
                        "caminho_imagem_preview": None,
                    }
                ]
            )
        raise AssertionError(f"SQL nao tratado no teste: {sql}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):  # pragma: no cover - nao esperado neste fluxo
        pass


@pytest.mark.asyncio
async def test_create_product_sem_request_id_faz_bind_de_none():
    session = _ProductSession()
    repo = SalesRepository(session)  # type: ignore[arg-type]

    payload = ProductCreateIn.model_validate(
        {
            "nome": "teste",
            "categoria": "Perfume",
            "precoBase": 350.0,
            "custo": 300.0,
            "estoque": 2,
            "estoqueMinimo": 1,
            "volumeMl": 100,
            "frascoColorValue": 4291509883,
        }
    )

    produto = await repo.create_product(payload)

    # Regressao: o INSERT precisa ligar o bind param `request_id`, mesmo quando
    # o app nao envia requestId (senao o asyncpg falha com
    # "A value is required for bind parameter 'request_id'").
    assert session.insert_params is not None
    assert "request_id" in session.insert_params
    assert session.insert_params["request_id"] is None
    assert session.commits == 1
    assert produto.nome == "teste"
    assert produto.preco_base == 350.0


@pytest.mark.asyncio
async def test_create_product_com_request_id_faz_bind_do_valor():
    session = _ProductSession()
    repo = SalesRepository(session)  # type: ignore[arg-type]

    payload = ProductCreateIn.model_validate(
        {
            "requestId": "req-produto-0001",
            "nome": "teste",
            "precoBase": 350.0,
            "custo": 300.0,
        }
    )

    await repo.create_product(payload)

    assert session.insert_params is not None
    assert session.insert_params["request_id"] == "req-produto-0001"


@pytest.mark.asyncio
async def test_update_product_atualiza_valor_sem_atributo_request_id():
    from app.modules.sales.schemas import ProductUpdateIn

    session = _ProductSession()
    repo = SalesRepository(session)  # type: ignore[arg-type]

    payload = ProductUpdateIn.model_validate(
        {
            "nome": "teste",
            "categoria": "Perfume",
            "precoBase": 250.0,
            "custo": 300.0,
            "estoqueMinimo": 1,
            "volumeMl": 100,
            "frascoColorValue": 4291509883,
        }
    )

    # Regressao: ProductUpdateIn nao tem `request_id`; o repo nao pode acessar
    # esse atributo (senao levanta AttributeError -> 500 no PATCH /products/{id}).
    produto = await repo.update_product(10, payload)

    assert produto is not None
    assert produto.preco_base == 250.0
    assert session.update_params is not None
    assert "request_id" not in session.update_params
    assert session.commits == 1
