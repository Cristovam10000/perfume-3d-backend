from __future__ import annotations

from datetime import date, datetime

import pytest

from app.core.exceptions import ValidationError
from app.modules.sales.repository import SalesRepository
from app.modules.sales.schemas import PaymentCreateIn


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

    def __iter__(self):
        return iter(self.rows)


class _PaymentSession:
    def __init__(self):
        self.installment = {
            "id": 7,
            "venda_id": 3,
            "numero_parcela": 1,
            "numero_parcelas": 2,
            "valor_original": 100.0,
            "valor_pago": 0.0,
            "valor_restante": 100.0,
            "status": "pendente",
            "data_vencimento": date(2026, 8, 10),
            "cliente_id": 5,
            "nome_completo": "Maria",
        }
        self.payments: dict[int, dict] = {}
        self.request_ids: dict[str, int] = {}
        self.events: list[dict] = []
        self.notifications = 0
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        if sql.startswith("select id from pagamentos where request_id"):
            payment_id = self.request_ids.get(params["request_id"])
            return _Result(rows=[] if payment_id is None else [{"id": payment_id}])
        if "from parcelas p" in sql and "for update" in sql:
            return _Result(rows=[dict(self.installment)])
        if sql.startswith("insert into pagamentos"):
            payment_id = len(self.payments) + 1
            self.payments[payment_id] = {
                "id": payment_id,
                "parcela_id": params["parcela_id"],
                "data_pagamento": params["data"],
                "valor_pago": params["valor"],
                "forma_pagamento": params["forma"],
                "observacoes": params["observacoes"],
            }
            self.request_ids[params["request_id"]] = payment_id
            return _Result(scalar=payment_id)
        if sql.startswith("update parcelas"):
            self.installment.update(
                {
                    "valor_pago": params["valor_pago"],
                    "valor_restante": params["valor_restante"],
                    "status": params["status"],
                }
            )
            return _Result()
        if sql.startswith("insert into eventos_parcela"):
            self.events.append(
                {
                    "parcela_id": params["parcela_id"],
                    "tipo_evento": "pagamento",
                    "data_evento": datetime.combine(params["data"], datetime.min.time()),
                    "valor_afetado": params["valor"],
                    "observacoes": params["observacoes"],
                }
            )
            return _Result()
        if sql.startswith("insert into notificacoes"):
            self.notifications += 1
            return _Result()
        if sql.startswith("insert into resumo_financeiro_cliente"):
            return _Result()
        if "from pagamentos" in sql and "where id = :id" in sql:
            payment = self.payments.get(params["id"])
            return _Result(rows=[] if payment is None else [payment])
        if "from parcelas p" in sql and "where p.id = :id" in sql:
            return _Result(rows=[dict(self.installment)])
        if "from eventos_parcela" in sql:
            return _Result(
                rows=[
                    event
                    for event in self.events
                    if event["parcela_id"] == params["id"]
                ]
            )
        raise AssertionError(f"SQL nao tratado no teste: {sql}")

    async def commit(self):
        self.commits += 1


def _payload(value: float, request_id: str) -> PaymentCreateIn:
    return PaymentCreateIn.model_validate(
        {
            "requestId": request_id,
            "valor": value,
            "data": "2026-07-23",
            "forma": "Pix",
        }
    )


@pytest.mark.asyncio
async def test_partial_then_total_payment_updates_remaining_and_status():
    session = _PaymentSession()
    repository = SalesRepository(session)  # type: ignore[arg-type]

    partial = await repository.receive_payment(7, _payload(40, "partial-12345678"))
    assert partial.installment.status == "parcial"
    assert partial.installment.valor_pago == 40
    assert partial.installment.valor - partial.installment.valor_pago == 60

    total = await repository.receive_payment(7, _payload(60, "total-123456789"))
    assert total.installment.status == "paga"
    assert total.installment.valor_pago == 100
    assert total.installment.valor - total.installment.valor_pago == 0
    assert session.notifications == 2
    assert session.commits == 2


@pytest.mark.asyncio
async def test_payment_rejects_value_above_balance_without_commit():
    session = _PaymentSession()
    repository = SalesRepository(session)  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="excede o saldo"):
        await repository.receive_payment(7, _payload(100.01, "excess-12345678"))

    assert session.payments == {}
    assert session.commits == 0


@pytest.mark.asyncio
async def test_payment_request_id_is_idempotent():
    session = _PaymentSession()
    repository = SalesRepository(session)  # type: ignore[arg-type]
    payload = _payload(25, "same-request-123")

    first = await repository.receive_payment(7, payload)
    second = await repository.receive_payment(7, payload)

    assert second.payment.id == first.payment.id
    assert len(session.payments) == 1
    assert session.installment["valor_pago"] == 25
    assert session.notifications == 1
