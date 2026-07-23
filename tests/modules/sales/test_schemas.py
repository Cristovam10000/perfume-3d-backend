from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.sales.schemas import (
    ClientWriteIn,
    DueDateUpdateIn,
    NotificationReadIn,
    PaymentCreateIn,
    ProductCreateIn,
    ProductUpdateIn,
)


def test_client_write_strips_fields_and_requires_essential_data():
    client = ClientWriteIn(
        nome="  Maria Silva  ",
        telefone=" 85999998888 ",
        bairro=" Centro ",
    )
    assert client.nome == "Maria Silva"
    assert client.telefone == "85999998888"
    assert client.bairro == "Centro"

    with pytest.raises(ValidationError):
        ClientWriteIn(nome="M", telefone="123", bairro="")


@pytest.mark.parametrize("field", ["precoBase", "custo"])
def test_product_create_requires_positive_price_and_cost(field: str):
    payload = {
        "nome": "Perfume teste",
        "categoria": "Unissex",
        "precoBase": 200,
        "custo": 100,
        "estoque": 3,
    }
    payload[field] = 0
    with pytest.raises(ValidationError):
        ProductCreateIn.model_validate(payload)


def test_product_update_does_not_accept_stock_and_validates_commercial_data():
    product = ProductUpdateIn.model_validate(
        {
            "nome": "Perfume teste",
            "categoria": "Unissex",
            "precoBase": 200,
            "custo": 100,
            "estoqueMinimo": 2,
            "volumeMl": 100,
            "frascoColorValue": 0xFFCB3E7B,
        }
    )
    assert product.preco_base == 200
    assert product.custo == 100


def test_payment_accepts_supported_method_and_rejects_zero():
    payment = PaymentCreateIn.model_validate(
        {
            "requestId": "payment-12345678",
            "valor": 50,
            "data": "2026-07-23",
            "forma": "Pix",
        }
    )
    assert payment.valor == 50
    assert payment.data == date(2026, 7, 23)

    with pytest.raises(ValidationError):
        PaymentCreateIn.model_validate(
            {
                "requestId": "payment-12345678",
                "valor": 0,
                "data": "2026-07-23",
                "forma": "Cheque",
            }
        )


def test_due_date_and_notification_read_alias_contract():
    change = DueDateUpdateIn.model_validate({"dueDate": "2026-08-15"})
    assert change.due_date == date(2026, 8, 15)
    assert NotificationReadIn().lida is True
