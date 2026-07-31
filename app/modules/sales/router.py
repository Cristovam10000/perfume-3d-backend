from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ...core.exceptions import NotFoundError
from ...database import get_session
from .repository import SalesRepository
from .schemas import (
    ClientWriteIn,
    ClienteOut,
    CreateSaleOut,
    DueDateUpdateIn,
    NotificationReadIn,
    NotificacaoOut,
    ParcelaOut,
    PaymentCreateIn,
    PaymentReceiptOut,
    ProductCreateIn,
    ProductStockUpdateIn,
    ProductUpdateIn,
    ProdutoOut,
    SaleCreateIn,
    SalesSnapshotOut,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.get(
    "/snapshot",
    response_model=SalesSnapshotOut,
    response_model_by_alias=True,
)
async def get_sales_snapshot(session=Depends(get_session)) -> SalesSnapshotOut:
    repo = SalesRepository(session)
    return await repo.snapshot()


@router.post(
    "/clients",
    response_model=ClienteOut,
    response_model_by_alias=True,
    status_code=201,
)
async def create_client(
    payload: ClientWriteIn,
    session=Depends(get_session),
) -> ClienteOut:
    repo = SalesRepository(session)
    return await repo.create_client(payload)


@router.patch(
    "/clients/{client_id}",
    response_model=ClienteOut,
    response_model_by_alias=True,
)
async def update_client(
    client_id: int,
    payload: ClientWriteIn,
    session=Depends(get_session),
) -> ClienteOut:
    repo = SalesRepository(session)
    client = await repo.update_client(client_id, payload)
    if client is None:
        raise NotFoundError(f"Cliente {client_id} nao encontrado")
    return client


@router.delete(
    "/clients/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_client(
    client_id: int,
    session=Depends(get_session),
) -> Response:
    repo = SalesRepository(session)
    deleted = await repo.delete_client(client_id)
    if not deleted:
        raise NotFoundError(f"Cliente {client_id} nao encontrado")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/products",
    response_model=ProdutoOut,
    response_model_by_alias=True,
    status_code=201,
)
async def create_product(
    payload: ProductCreateIn,
    session=Depends(get_session),
) -> ProdutoOut:
    repo = SalesRepository(session)
    return await repo.create_product(payload)


@router.patch(
    "/products/{product_id}",
    response_model=ProdutoOut,
    response_model_by_alias=True,
)
async def update_product(
    product_id: int,
    payload: ProductUpdateIn,
    session=Depends(get_session),
) -> ProdutoOut:
    repo = SalesRepository(session)
    product = await repo.update_product(product_id, payload)
    if product is None:
        raise NotFoundError(f"Produto {product_id} nao encontrado")
    return product


@router.patch(
    "/products/{product_id}/stock",
    response_model=ProdutoOut,
    response_model_by_alias=True,
)
async def update_stock(
    product_id: int,
    payload: ProductStockUpdateIn,
    session=Depends(get_session),
) -> ProdutoOut:
    repo = SalesRepository(session)
    product = await repo.update_stock(product_id, payload)
    if product is None:
        raise NotFoundError(f"Produto {product_id} nao encontrado")
    return product


@router.post(
    "/installments/{installment_id}/payments",
    response_model=PaymentReceiptOut,
    response_model_by_alias=True,
    status_code=201,
)
async def receive_payment(
    installment_id: int,
    payload: PaymentCreateIn,
    session=Depends(get_session),
) -> PaymentReceiptOut:
    repo = SalesRepository(session)
    return await repo.receive_payment(installment_id, payload)


@router.patch(
    "/installments/{installment_id}/due-date",
    response_model=ParcelaOut,
    response_model_by_alias=True,
)
async def update_installment_due_date(
    installment_id: int,
    payload: DueDateUpdateIn,
    session=Depends(get_session),
) -> ParcelaOut:
    repo = SalesRepository(session)
    return await repo.update_installment_due_date(installment_id, payload)


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificacaoOut,
    response_model_by_alias=True,
)
async def mark_notification_read(
    notification_id: int,
    payload: NotificationReadIn,
    session=Depends(get_session),
) -> NotificacaoOut:
    repo = SalesRepository(session)
    notification = await repo.mark_notification_read(notification_id, payload.lida)
    if notification is None:
        raise NotFoundError(f"Notificacao {notification_id} nao encontrada")
    return notification


@router.post(
    "/sales",
    response_model=CreateSaleOut,
    response_model_by_alias=True,
    status_code=201,
)
async def create_sale(
    payload: SaleCreateIn,
    session=Depends(get_session),
) -> CreateSaleOut:
    repo = SalesRepository(session)
    return await repo.create_sale(payload)
