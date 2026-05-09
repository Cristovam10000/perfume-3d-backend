from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ClienteOut(BaseModel):
    id: str
    nome: str
    telefone: str
    bairro: str
    score: int
    status: str
    em_aberto: float = Field(serialization_alias="emAberto")
    total_compras: int = Field(serialization_alias="totalCompras")
    parcelas_atraso: int = Field(serialization_alias="parcelasAtraso")
    total_comprado: float = Field(serialization_alias="totalComprado")
    sync_status: str = Field(default="synced", serialization_alias="syncStatus")

    model_config = {"populate_by_name": True}


class ProdutoOut(BaseModel):
    id: str
    nome: str
    categoria: str
    preco_base: float = Field(serialization_alias="precoBase")
    custo: float
    estoque: int
    estoque_minimo: int = Field(serialization_alias="estoqueMinimo")
    volume_ml: int = Field(serialization_alias="volumeMl")
    frasco_color_value: int = Field(serialization_alias="frascoColorValue")
    tem_3d: bool = Field(serialization_alias="tem3D")
    modelo_3d_path: str | None = Field(default=None, serialization_alias="modelo3DPath")
    preview_img: str | None = Field(default=None, serialization_alias="previewImg")
    sync_status: str = Field(default="synced", serialization_alias="syncStatus")

    model_config = {"populate_by_name": True}


class ItemVendaOut(BaseModel):
    produto_id: str = Field(serialization_alias="produtoId")
    quantidade: int
    preco_unitario: float = Field(serialization_alias="precoUnitario")

    model_config = {"populate_by_name": True}


class VendaOut(BaseModel):
    id: str
    cliente_id: str = Field(serialization_alias="clienteId")
    data: datetime
    itens: list[ItemVendaOut]
    total: float
    entrada: float
    num_parcelas: int = Field(serialization_alias="numParcelas")
    observacoes: str | None = None
    sync_status: str = Field(default="synced", serialization_alias="syncStatus")

    model_config = {"populate_by_name": True}


class EventoParcelaOut(BaseModel):
    tipo: str
    data: datetime
    descricao: str
    valor: float | None = None


class ParcelaOut(BaseModel):
    id: str
    venda_id: str = Field(serialization_alias="vendaId")
    numero: int
    total: int
    valor: float
    vencimento: datetime
    status: str
    valor_pago: float = Field(default=0, serialization_alias="valorPago")
    eventos: list[EventoParcelaOut] = Field(default_factory=list)
    sync_status: str = Field(default="synced", serialization_alias="syncStatus")

    model_config = {"populate_by_name": True}


class PagamentoOut(BaseModel):
    id: str
    parcela_id: str = Field(serialization_alias="parcelaId")
    data: datetime
    valor: float
    forma: str
    observacoes: str | None = None
    sync_status: str = Field(default="synced", serialization_alias="syncStatus")

    model_config = {"populate_by_name": True}


class NotificacaoOut(BaseModel):
    id: str
    cliente_id: str = Field(serialization_alias="clienteId")
    parcela_id: str = Field(serialization_alias="parcelaId")
    tipo: str
    data: datetime
    texto: str
    valor: float
    lida: bool = False

    model_config = {"populate_by_name": True}


class SalesSnapshotOut(BaseModel):
    hoje: datetime
    clientes: list[ClienteOut]
    produtos: list[ProdutoOut]
    vendas: list[VendaOut]
    parcelas: list[ParcelaOut]
    pagamentos: list[PagamentoOut]
    notificacoes: list[NotificacaoOut]


class ProductCreateIn(BaseModel):
    nome: str
    categoria: str = "Perfume"
    preco_base: float = Field(alias="precoBase")
    custo: float = 0
    estoque: int = 0
    estoque_minimo: int = Field(default=1, alias="estoqueMinimo")
    volume_ml: int = Field(default=100, alias="volumeMl")
    frasco_color_value: int = Field(default=0xFFCB3E7B, alias="frascoColorValue")

    model_config = {"populate_by_name": True}


class ProductStockUpdateIn(BaseModel):
    mode: Literal["add", "set"]
    quantity: int


class SaleItemIn(BaseModel):
    produto_id: str = Field(alias="produtoId")
    quantidade: int
    preco_unitario: float = Field(alias="precoUnitario")

    model_config = {"populate_by_name": True}


class SaleCreateIn(BaseModel):
    cliente_id: str = Field(alias="clienteId")
    data: datetime
    itens: list[SaleItemIn]
    total: float
    entrada: float = 0
    num_parcelas: int = Field(default=1, alias="numParcelas")
    observacoes: str | None = None

    model_config = {"populate_by_name": True}


class CreateSaleOut(BaseModel):
    id: str


def as_datetime(value: date) -> datetime:
    return datetime(value.year, value.month, value.day)
