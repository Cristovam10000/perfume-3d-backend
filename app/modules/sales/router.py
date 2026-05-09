from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.exceptions import NotFoundError
from ...database import get_session
from .repository import SalesRepository
from .schemas import (
    CreateSaleOut,
    ProductCreateIn,
    ProductStockUpdateIn,
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
