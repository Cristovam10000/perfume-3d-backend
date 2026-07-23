from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ...core.exceptions import ValidationError
from .schemas import (
    ClientWriteIn,
    ClienteOut,
    CreateSaleOut,
    DueDateUpdateIn,
    EventoParcelaOut,
    ItemVendaOut,
    NotificacaoOut,
    PagamentoOut,
    ParcelaOut,
    PaymentCreateIn,
    PaymentReceiptOut,
    ProductCreateIn,
    ProductStockUpdateIn,
    ProductUpdateIn,
    ProdutoOut,
    SaleCreateIn,
    SalesSnapshotOut,
    VendaOut,
    as_datetime,
)


async def ensure_sales_schema(engine: AsyncEngine) -> None:
    """Aplica pequenas colunas de estoque usadas pelo front atual.

    O projeto ainda nao usa Alembic; este bootstrap deixa ambientes locais
    antigos compatíveis sem apagar ou recriar tabelas comerciais existentes.
    """
    statements = [
        "ALTER TABLE IF EXISTS produtos ADD COLUMN IF NOT EXISTS custo numeric(10,2) DEFAULT 0 NOT NULL",
        "ALTER TABLE IF EXISTS produtos ADD COLUMN IF NOT EXISTS estoque_minimo integer DEFAULT 1 NOT NULL",
        "ALTER TABLE IF EXISTS produtos ADD COLUMN IF NOT EXISTS volume_ml integer DEFAULT 100 NOT NULL",
        "ALTER TABLE IF EXISTS produtos ADD COLUMN IF NOT EXISTS frasco_color_value bigint DEFAULT 4285558395 NOT NULL",
        "ALTER TABLE IF EXISTS pagamentos ADD COLUMN IF NOT EXISTS request_id varchar(80)",
        "ALTER TABLE IF EXISTS clientes ADD COLUMN IF NOT EXISTS sync_request_id varchar(80)",
        "ALTER TABLE IF EXISTS produtos ADD COLUMN IF NOT EXISTS sync_request_id varchar(80)",
        "ALTER TABLE IF EXISTS vendas ADD COLUMN IF NOT EXISTS sync_request_id varchar(80)",
        "ALTER TABLE IF EXISTS eventos_parcela ADD COLUMN IF NOT EXISTS request_id varchar(80)",
        "UPDATE produtos SET estoque_minimo = 1 WHERE estoque_minimo IS NULL OR estoque_minimo < 1",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pagamentos_request_id ON pagamentos(request_id) WHERE request_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_sync_request_id ON clientes(sync_request_id) WHERE sync_request_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_produtos_sync_request_id ON produtos(sync_request_id) WHERE sync_request_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vendas_sync_request_id ON vendas(sync_request_id) WHERE sync_request_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_eventos_parcela_request_id ON eventos_parcela(request_id) WHERE request_id IS NOT NULL",
        """
        DELETE FROM notificacoes older
        USING notificacoes newer
        WHERE older.id < newer.id
          AND older.parcela_id = newer.parcela_id
          AND older.tipo_notificacao = newer.tipo_notificacao
          AND older.tipo_notificacao IN (
              'vence_amanha', 'vence_hoje', 'atraso'
          )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notificacoes_cobranca_parcela_tipo
        ON notificacoes(parcela_id, tipo_notificacao)
        WHERE tipo_notificacao IN ('vence_amanha', 'vence_hoje', 'atraso')
        """,
    ]
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


class SalesRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def snapshot(self) -> SalesSnapshotOut:
        await self._ensure_billing_notifications()
        await self.session.commit()
        clientes = await self._clientes()
        produtos = await self._produtos()
        vendas = await self._vendas()
        parcelas = await self._parcelas()
        pagamentos = await self._pagamentos()
        notificacoes = await self._notificacoes()
        return SalesSnapshotOut(
            hoje=as_datetime(date.today()),
            clientes=clientes,
            produtos=produtos,
            vendas=vendas,
            parcelas=parcelas,
            pagamentos=pagamentos,
            notificacoes=notificacoes,
        )

    async def create_client(self, payload: ClientWriteIn) -> ClienteOut:
        if payload.request_id:
            existing_id = (
                await self.session.execute(
                    text(
                        """
                        select id from clientes
                        where sync_request_id = :request_id and ativo = true
                        """
                    ),
                    {"request_id": payload.request_id},
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                existing = await self._client_by_id(int(existing_id))
                if existing is not None:
                    return existing

        result = await self.session.execute(
            text(
                """
                insert into clientes (
                    nome_completo, telefone, bairro, ativo, sync_request_id
                )
                values (:nome, :telefone, :bairro, true, :request_id)
                returning id
                """
            ),
            {
                "nome": payload.nome,
                "telefone": payload.telefone,
                "bairro": payload.bairro,
                "request_id": payload.request_id,
            },
        )
        client_id = int(result.scalar_one())
        await self._recalculate_summary(client_id)
        await self.session.commit()
        client = await self._client_by_id(client_id)
        if client is None:  # pragma: no cover - retorno defensivo
            raise RuntimeError("Cliente criado nao encontrado")
        return client

    async def update_client(
        self,
        client_id: int,
        payload: ClientWriteIn,
    ) -> ClienteOut | None:
        result = await self.session.execute(
            text(
                """
                update clientes
                set nome_completo = :nome,
                    telefone = :telefone,
                    bairro = :bairro,
                    atualizado_em = current_timestamp
                where id = :id and ativo = true
                returning id
                """
            ),
            {
                "id": client_id,
                "nome": payload.nome,
                "telefone": payload.telefone,
                "bairro": payload.bairro,
            },
        )
        if result.scalar_one_or_none() is None:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self._client_by_id(client_id)

    async def create_product(self, payload: ProductCreateIn) -> ProdutoOut:
        if payload.request_id:
            existing_id = (
                await self.session.execute(
                    text(
                        """
                        select id from produtos
                        where sync_request_id = :request_id and ativo = true
                        """
                    ),
                    {"request_id": payload.request_id},
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                existing = await self._product_by_id(int(existing_id))
                if existing is not None:
                    return existing

        result = await self.session.execute(
            text(
                """
                insert into produtos (
                    nome, categoria, preco_base, custo, estoque,
                    estoque_minimo, volume_ml, frasco_color_value,
                    possui_modelo_3d, ativo, sync_request_id
                )
                values (
                    :nome, :categoria, :preco_base, :custo, :estoque,
                    :estoque_minimo, :volume_ml, :frasco_color_value,
                    false, true, :request_id
                )
                returning id
                """
            ),
            {
                "nome": payload.nome,
                "categoria": payload.categoria,
                "preco_base": payload.preco_base,
                "custo": payload.custo,
                "estoque": max(payload.estoque, 0),
                "estoque_minimo": max(payload.estoque_minimo, 1),
                "volume_ml": max(payload.volume_ml, 1),
                "frasco_color_value": payload.frasco_color_value,
                "request_id": payload.request_id,
            },
        )
        product_id = result.scalar_one()
        await self.session.commit()
        product = await self._product_by_id(product_id)
        if product is None:  # pragma: no cover - retorno defensivo
            raise RuntimeError("Produto criado nao encontrado")
        return product

    async def update_product(
        self,
        product_id: int,
        payload: ProductUpdateIn,
    ) -> ProdutoOut | None:
        result = await self.session.execute(
            text(
                """
                update produtos
                set nome = :nome,
                    categoria = :categoria,
                    preco_base = :preco_base,
                    custo = :custo,
                    estoque_minimo = :estoque_minimo,
                    volume_ml = :volume_ml,
                    frasco_color_value = :frasco_color_value,
                    atualizado_em = current_timestamp
                where id = :id and ativo = true
                returning id
                """
            ),
            {
                "id": product_id,
                "nome": payload.nome,
                "categoria": payload.categoria,
                "preco_base": payload.preco_base,
                "custo": payload.custo,
                "estoque_minimo": payload.estoque_minimo,
                "volume_ml": payload.volume_ml,
                "frasco_color_value": payload.frasco_color_value,
            },
        )
        if result.scalar_one_or_none() is None:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self._product_by_id(product_id)

    async def update_stock(
        self, product_id: int, payload: ProductStockUpdateIn
    ) -> ProdutoOut | None:
        if payload.mode == "add":
            statement = """
                update produtos
                set estoque = greatest(0, estoque + :quantity),
                    atualizado_em = current_timestamp
                where id = :id and ativo = true
            """
        else:
            statement = """
                update produtos
                set estoque = greatest(0, :quantity),
                    atualizado_em = current_timestamp
                where id = :id and ativo = true
            """
        await self.session.execute(
            text(statement),
            {"id": product_id, "quantity": max(payload.quantity, 0)},
        )
        await self.session.commit()
        return await self._product_by_id(product_id)

    async def receive_payment(
        self,
        installment_id: int,
        payload: PaymentCreateIn,
    ) -> PaymentReceiptOut:
        existing = await self._payment_receipt_by_request_id(payload.request_id)
        if existing is not None:
            return existing

        row = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.venda_id, p.valor_original, p.valor_pago,
                        p.valor_restante, p.status, v.cliente_id,
                        c.nome_completo
                    from parcelas p
                    join vendas v on v.id = p.venda_id
                    join clientes c on c.id = v.cliente_id
                    where p.id = :id
                    for update
                    """
                ),
                {"id": installment_id},
            )
        ).mappings().first()
        if row is None:
            raise ValidationError(f"Parcela {installment_id} nao encontrada")

        remaining = float(row["valor_restante"])
        if row["status"] == "paga" or remaining <= 0:
            raise ValidationError("Esta parcela ja esta paga")
        if payload.valor > remaining + 0.005:
            raise ValidationError(
                f"Valor recebido excede o saldo da parcela: {remaining:.2f}"
            )

        paid = round(float(row["valor_pago"]) + payload.valor, 2)
        new_remaining = round(max(float(row["valor_original"]) - paid, 0), 2)
        status = "paga" if new_remaining <= 0 else "parcial"

        payment_id = int(
            (
                await self.session.execute(
                    text(
                        """
                        insert into pagamentos (
                            parcela_id, valor_pago, data_pagamento,
                            forma_pagamento, observacoes, request_id
                        )
                        values (
                            :parcela_id, :valor, :data, :forma,
                            :observacoes, :request_id
                        )
                        returning id
                        """
                    ),
                    {
                        "parcela_id": installment_id,
                        "valor": payload.valor,
                        "data": payload.data,
                        "forma": payload.forma,
                        "observacoes": payload.observacoes,
                        "request_id": payload.request_id,
                    },
                )
            ).scalar_one()
        )
        await self.session.execute(
            text(
                """
                update parcelas
                set valor_pago = :valor_pago,
                    valor_restante = :valor_restante,
                    status = :status,
                    data_ultimo_pagamento = :data,
                    atualizado_em = current_timestamp
                where id = :id
                """
            ),
            {
                "id": installment_id,
                "valor_pago": paid,
                "valor_restante": new_remaining,
                "status": status,
                "data": payload.data,
            },
        )
        await self.session.execute(
            text(
                """
                insert into eventos_parcela (
                    parcela_id, tipo_evento, data_evento,
                    valor_afetado, observacoes
                )
                values (
                    :parcela_id, 'pagamento', :data,
                    :valor, :observacoes
                )
                """
            ),
            {
                "parcela_id": installment_id,
                "data": payload.data,
                "valor": payload.valor,
                "observacoes": payload.observacoes or f"Pagamento via {payload.forma}",
            },
        )
        await self.session.execute(
            text(
                """
                insert into notificacoes (
                    cliente_id, parcela_id, tipo_notificacao,
                    tipo_destinatario, agendada_para, status,
                    mensagem, valor, lida
                )
                values (
                    :cliente_id, :parcela_id, 'pagamento',
                    'vendedor', current_timestamp, 'pendente',
                    :mensagem, :valor, false
                )
                """
            ),
            {
                "cliente_id": int(row["cliente_id"]),
                "parcela_id": installment_id,
                "mensagem": (
                    f"Pagamento de R$ {payload.valor:.2f} recebido de "
                    f"{row['nome_completo']}."
                ),
                "valor": payload.valor,
            },
        )
        await self._recalculate_summary(int(row["cliente_id"]))
        await self.session.commit()
        receipt = await self._payment_receipt_by_payment_id(payment_id)
        if receipt is None:  # pragma: no cover - retorno defensivo
            raise RuntimeError("Pagamento criado nao encontrado")
        return receipt

    async def update_installment_due_date(
        self,
        installment_id: int,
        payload: DueDateUpdateIn,
    ) -> ParcelaOut:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.valor_pago, p.valor_restante, p.status,
                        p.data_vencimento, v.cliente_id
                    from parcelas p
                    join vendas v on v.id = p.venda_id
                    where p.id = :id
                    for update
                    """
                ),
                {"id": installment_id},
            )
        ).mappings().first()
        if row is None:
            raise ValidationError(f"Parcela {installment_id} nao encontrada")
        if row["status"] == "paga" or float(row["valor_restante"]) <= 0:
            raise ValidationError("Nao e possivel renegociar uma parcela paga")
        if payload.due_date < date.today():
            raise ValidationError("O novo vencimento nao pode estar no passado")

        status = "parcial" if float(row["valor_pago"]) > 0 else "pendente"
        await self.session.execute(
            text(
                """
                update parcelas
                set data_vencimento = :due_date,
                    status = :status,
                    atualizado_em = current_timestamp
                where id = :id
                """
            ),
            {
                "id": installment_id,
                "due_date": payload.due_date,
                "status": status,
            },
        )
        await self.session.execute(
            text(
                """
                insert into eventos_parcela (
                    parcela_id, tipo_evento, data_evento,
                    valor_afetado, observacoes, request_id
                )
                values (
                    :parcela_id, 'remarca', current_timestamp,
                    null, :observacoes, :request_id
                )
                on conflict (request_id) where request_id is not null do nothing
                """
            ),
            {
                "parcela_id": installment_id,
                "observacoes": payload.observacoes
                or (
                    f"Vencimento alterado de {row['data_vencimento']} "
                    f"para {payload.due_date}"
                ),
                "request_id": payload.request_id,
            },
        )
        await self._ensure_billing_notifications(installment_id=installment_id)
        await self._recalculate_summary(int(row["cliente_id"]))
        await self.session.commit()
        installment = await self._installment_by_id(installment_id)
        if installment is None:  # pragma: no cover - retorno defensivo
            raise RuntimeError("Parcela atualizada nao encontrada")
        return installment

    async def mark_notification_read(
        self,
        notification_id: int,
        read: bool,
    ) -> NotificacaoOut | None:
        row = (
            await self.session.execute(
                text(
                    """
                    update notificacoes
                    set lida = :lida
                    where id = :id
                    returning id, cliente_id, parcela_id, tipo_notificacao,
                              agendada_para, mensagem, valor, lida
                    """
                ),
                {"id": notification_id, "lida": read},
            )
        ).mappings().first()
        if row is None:
            await self.session.rollback()
            return None
        await self.session.commit()
        return _notification_from_row(row)

    async def create_sale(self, payload: SaleCreateIn) -> CreateSaleOut:
        if payload.request_id:
            existing_id = (
                await self.session.execute(
                    text(
                        """
                        select id from vendas
                        where sync_request_id = :request_id
                        """
                    ),
                    {"request_id": payload.request_id},
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                return CreateSaleOut(id=str(existing_id))

        if not payload.itens:
            raise ValidationError("A venda precisa ter pelo menos um produto")

        cliente_id = _parse_db_id(payload.cliente_id, "cliente")
        await self._validate_client(cliente_id)
        await self._validate_sale_items(payload.itens)

        sale_date = payload.data.date()
        remaining = max(payload.total - payload.entrada, 0)
        installments_count = max(payload.num_parcelas, 1) if remaining > 0 else 0

        result = await self.session.execute(
            text(
                """
                insert into vendas (
                    cliente_id, data_venda, valor_total, valor_entrada,
                    valor_restante, numero_parcelas, observacoes,
                    sync_request_id
                )
                values (
                    :cliente_id, :data_venda, :valor_total, :valor_entrada,
                    :valor_restante, :numero_parcelas, :observacoes,
                    :request_id
                )
                returning id
                """
            ),
            {
                "cliente_id": cliente_id,
                "data_venda": sale_date,
                "valor_total": payload.total,
                "valor_entrada": payload.entrada,
                "valor_restante": remaining,
                "numero_parcelas": installments_count,
                "observacoes": payload.observacoes,
                "request_id": payload.request_id,
            },
        )
        sale_id = int(result.scalar_one())

        for item in payload.itens:
            product_id = _parse_db_id(item.produto_id, "produto")
            total = item.quantidade * item.preco_unitario
            await self.session.execute(
                text(
                    """
                    insert into itens_venda (
                        venda_id, produto_id, quantidade,
                        preco_unitario, preco_total
                    )
                    values (
                        :venda_id, :produto_id, :quantidade,
                        :preco_unitario, :preco_total
                    )
                    """
                ),
                {
                    "venda_id": sale_id,
                    "produto_id": product_id,
                    "quantidade": item.quantidade,
                    "preco_unitario": item.preco_unitario,
                    "preco_total": total,
                },
            )
            update_result = await self.session.execute(
                text(
                    """
                    update produtos
                    set estoque = estoque - :quantidade,
                        atualizado_em = current_timestamp
                    where id = :produto_id
                      and ativo = true
                      and estoque >= :quantidade
                    """
                ),
                {"produto_id": product_id, "quantidade": item.quantidade},
            )
            if update_result.rowcount != 1:
                raise ValidationError(
                    f"Estoque insuficiente para o produto {product_id}"
                )

        if installments_count > 0:
            base_value = round(remaining / installments_count, 2)
            values = [base_value for _ in range(installments_count)]
            values[-1] = round(remaining - sum(values[:-1]), 2)
            for index, value in enumerate(values, start=1):
                await self.session.execute(
                    text(
                        """
                        insert into parcelas (
                            venda_id, numero_parcela, valor_original,
                            valor_pago, valor_restante, data_vencimento, status
                        )
                        values (
                            :venda_id, :numero_parcela, :valor_original,
                            0, :valor_restante, :data_vencimento, 'pendente'
                        )
                        """
                    ),
                    {
                        "venda_id": sale_id,
                        "numero_parcela": index,
                        "valor_original": value,
                        "valor_restante": value,
                        "data_vencimento": _add_months(sale_date, index),
                    },
                )

        await self._recalculate_summary(cliente_id)
        await self.session.commit()
        return CreateSaleOut(id=str(sale_id))

    async def _validate_client(self, cliente_id: int) -> None:
        exists = (
            await self.session.execute(
                text(
                    """
                    select exists(
                        select 1 from clientes where id = :id and ativo = true
                    )
                    """
                ),
                {"id": cliente_id},
            )
        ).scalar_one()
        if not exists:
            raise ValidationError(f"Cliente {cliente_id} nao encontrado")

    async def _validate_sale_items(self, items: list[SaleItemIn]) -> None:
        requested_by_product: dict[int, int] = {}
        for item in items:
            product_id = _parse_db_id(item.produto_id, "produto")
            if item.quantidade <= 0:
                raise ValidationError(
                    "A quantidade vendida precisa ser maior que zero"
                )
            if item.preco_unitario < 0:
                raise ValidationError("O preco unitario nao pode ser negativo")
            requested_by_product[product_id] = (
                requested_by_product.get(product_id, 0) + item.quantidade
            )

        for product_id, requested in requested_by_product.items():
            row = (
                await self.session.execute(
                    text(
                        """
                        select nome, estoque
                        from produtos
                        where id = :id and ativo = true
                        """
                    ),
                    {"id": product_id},
                )
            ).mappings().first()
            if row is None:
                raise ValidationError(f"Produto {product_id} nao encontrado")
            if int(row["estoque"]) < requested:
                raise ValidationError(
                    f"Estoque insuficiente para {row['nome']}: "
                    f"disponivel {row['estoque']}, solicitado {requested}"
                )

    async def _clientes(self) -> list[ClienteOut]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select
                        c.id, c.nome_completo, c.telefone, coalesce(c.bairro, '') as bairro,
                        coalesce(r.score_pagador, 0) as score,
                        coalesce(r.status_pagador, 'warn') as status_pagador,
                        coalesce(r.valor_total_em_aberto, 0) as em_aberto,
                        coalesce(r.total_vendas, 0) as total_compras,
                        coalesce(r.total_parcelas_atrasadas, 0) as parcelas_atraso,
                        coalesce(r.valor_total_comprado, 0) as total_comprado
                    from clientes c
                    left join resumo_financeiro_cliente r on r.cliente_id = c.id
                    where c.ativo = true
                    order by c.nome_completo
                    """
                )
            )
        ).mappings()
        return [
            ClienteOut(
                id=str(row["id"]),
                nome=row["nome_completo"],
                telefone=row["telefone"],
                bairro=row["bairro"],
                score=int(row["score"]),
                status=row["status_pagador"],
                em_aberto=float(row["em_aberto"]),
                total_compras=int(row["total_compras"]),
                parcelas_atraso=int(row["parcelas_atraso"]),
                total_comprado=float(row["total_comprado"]),
            )
            for row in rows
        ]

    async def _client_by_id(self, client_id: int) -> ClienteOut | None:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                        c.id, c.nome_completo, c.telefone,
                        coalesce(c.bairro, '') as bairro,
                        coalesce(r.score_pagador, 0) as score,
                        coalesce(r.status_pagador, 'warn') as status_pagador,
                        coalesce(r.valor_total_em_aberto, 0) as em_aberto,
                        coalesce(r.total_vendas, 0) as total_compras,
                        coalesce(r.total_parcelas_atrasadas, 0) as parcelas_atraso,
                        coalesce(r.valor_total_comprado, 0) as total_comprado
                    from clientes c
                    left join resumo_financeiro_cliente r on r.cliente_id = c.id
                    where c.id = :id and c.ativo = true
                    """
                ),
                {"id": client_id},
            )
        ).mappings().first()
        return _client_from_row(row) if row else None

    async def _produtos(self) -> list[ProdutoOut]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.nome, p.categoria, p.preco_base,
                        coalesce(p.custo, 0) as custo,
                        coalesce(p.estoque, 0) as estoque,
                        coalesce(p.estoque_minimo, 1) as estoque_minimo,
                        coalesce(p.volume_ml, 100) as volume_ml,
                        coalesce(p.frasco_color_value, 4285558395) as frasco_color_value,
                        p.possui_modelo_3d,
                        m.caminho_arquivo_modelo,
                        m.caminho_imagem_preview
                    from produtos p
                    left join modelos_3d_produto m on m.produto_id = p.id
                    where p.ativo = true
                    order by p.nome
                    """
                )
            )
        ).mappings()
        return [_produto_from_row(row) for row in rows]

    async def _product_by_id(self, product_id: int) -> ProdutoOut | None:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.nome, p.categoria, p.preco_base,
                        coalesce(p.custo, 0) as custo,
                        coalesce(p.estoque, 0) as estoque,
                        coalesce(p.estoque_minimo, 1) as estoque_minimo,
                        coalesce(p.volume_ml, 100) as volume_ml,
                        coalesce(p.frasco_color_value, 4285558395) as frasco_color_value,
                        p.possui_modelo_3d,
                        m.caminho_arquivo_modelo,
                        m.caminho_imagem_preview
                    from produtos p
                    left join modelos_3d_produto m on m.produto_id = p.id
                    where p.id = :id and p.ativo = true
                    """
                ),
                {"id": product_id},
            )
        ).mappings().first()
        return _produto_from_row(row) if row else None

    async def _vendas(self) -> list[VendaOut]:
        sale_rows = (
            await self.session.execute(
                text(
                    """
                    select id, cliente_id, data_venda, valor_total, valor_entrada,
                           numero_parcelas, observacoes
                    from vendas
                    order by data_venda desc, id desc
                    """
                )
            )
        ).mappings()
        item_rows = (
            await self.session.execute(
                text(
                    """
                    select venda_id, produto_id, quantidade, preco_unitario
                    from itens_venda
                    order by id
                    """
                )
            )
        ).mappings()
        items_by_sale: dict[int, list[ItemVendaOut]] = {}
        for row in item_rows:
            items_by_sale.setdefault(int(row["venda_id"]), []).append(
                ItemVendaOut(
                    produto_id=str(row["produto_id"]),
                    quantidade=int(row["quantidade"]),
                    preco_unitario=float(row["preco_unitario"]),
                )
            )
        return [
            VendaOut(
                id=str(row["id"]),
                cliente_id=str(row["cliente_id"]),
                data=as_datetime(row["data_venda"]),
                itens=items_by_sale.get(int(row["id"]), []),
                total=float(row["valor_total"]),
                entrada=float(row["valor_entrada"]),
                num_parcelas=int(row["numero_parcelas"]),
                observacoes=row["observacoes"],
            )
            for row in sale_rows
        ]

    async def _parcelas(self) -> list[ParcelaOut]:
        parcel_rows = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.venda_id, p.numero_parcela, v.numero_parcelas,
                        p.valor_original, p.valor_pago, p.data_vencimento,
                        case
                            when p.status <> 'paga' and p.data_vencimento < current_date
                                then 'atrasada'
                            else p.status
                        end as status
                    from parcelas p
                    join vendas v on v.id = p.venda_id
                    order by p.data_vencimento, p.id
                    """
                )
            )
        ).mappings()
        event_rows = (
            await self.session.execute(
                text(
                    """
                    select parcela_id, tipo_evento, data_evento, valor_afetado, observacoes
                    from eventos_parcela
                    order by data_evento
                    """
                )
            )
        ).mappings()
        events_by_parcel: dict[int, list[EventoParcelaOut]] = {}
        for row in event_rows:
            events_by_parcel.setdefault(int(row["parcela_id"]), []).append(
                EventoParcelaOut(
                    tipo=row["tipo_evento"],
                    data=row["data_evento"],
                    descricao=row["observacoes"] or row["tipo_evento"],
                    valor=float(row["valor_afetado"]) if row["valor_afetado"] else None,
                )
            )
        return [
            ParcelaOut(
                id=str(row["id"]),
                venda_id=str(row["venda_id"]),
                numero=int(row["numero_parcela"]),
                total=int(row["numero_parcelas"]),
                valor=float(row["valor_original"]),
                vencimento=as_datetime(row["data_vencimento"]),
                status=row["status"],
                valor_pago=float(row["valor_pago"]),
                eventos=events_by_parcel.get(int(row["id"]), []),
            )
            for row in parcel_rows
        ]

    async def _installment_by_id(self, installment_id: int) -> ParcelaOut | None:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                        p.id, p.venda_id, p.numero_parcela, v.numero_parcelas,
                        p.valor_original, p.valor_pago, p.data_vencimento,
                        case
                            when p.status <> 'paga' and p.data_vencimento < current_date
                                then 'atrasada'
                            else p.status
                        end as status
                    from parcelas p
                    join vendas v on v.id = p.venda_id
                    where p.id = :id
                    """
                ),
                {"id": installment_id},
            )
        ).mappings().first()
        if row is None:
            return None
        event_rows = (
            await self.session.execute(
                text(
                    """
                    select parcela_id, tipo_evento, data_evento,
                           valor_afetado, observacoes
                    from eventos_parcela
                    where parcela_id = :id
                    order by data_evento
                    """
                ),
                {"id": installment_id},
            )
        ).mappings()
        events = [
            EventoParcelaOut(
                tipo=event["tipo_evento"],
                data=event["data_evento"],
                descricao=event["observacoes"] or event["tipo_evento"],
                valor=(
                    float(event["valor_afetado"])
                    if event["valor_afetado"] is not None
                    else None
                ),
            )
            for event in event_rows
        ]
        return _installment_from_row(row, events)

    async def _pagamentos(self) -> list[PagamentoOut]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select id, parcela_id, data_pagamento, valor_pago,
                           forma_pagamento, observacoes
                    from pagamentos
                    order by data_pagamento desc, id desc
                    """
                )
            )
        ).mappings()
        return [
            PagamentoOut(
                id=str(row["id"]),
                parcela_id=str(row["parcela_id"]),
                data=as_datetime(row["data_pagamento"]),
                valor=float(row["valor_pago"]),
                forma=row["forma_pagamento"],
                observacoes=row["observacoes"],
            )
            for row in rows
        ]

    async def _payment_receipt_by_request_id(
        self,
        request_id: str,
    ) -> PaymentReceiptOut | None:
        row = (
            await self.session.execute(
                text("select id from pagamentos where request_id = :request_id"),
                {"request_id": request_id},
            )
        ).mappings().first()
        if row is None:
            return None
        return await self._payment_receipt_by_payment_id(int(row["id"]))

    async def _payment_receipt_by_payment_id(
        self,
        payment_id: int,
    ) -> PaymentReceiptOut | None:
        row = (
            await self.session.execute(
                text(
                    """
                    select id, parcela_id, data_pagamento, valor_pago,
                           forma_pagamento, observacoes
                    from pagamentos
                    where id = :id
                    """
                ),
                {"id": payment_id},
            )
        ).mappings().first()
        if row is None:
            return None
        installment = await self._installment_by_id(int(row["parcela_id"]))
        if installment is None:  # pragma: no cover - FK garante a parcela
            return None
        return PaymentReceiptOut(
            payment=_payment_from_row(row),
            installment=installment,
        )

    async def _ensure_billing_notifications(
        self,
        *,
        installment_id: int | None = None,
    ) -> None:
        await self.session.execute(
            text(
                """
                insert into notificacoes (
                    cliente_id, parcela_id, tipo_notificacao,
                    tipo_destinatario, agendada_para, status,
                    mensagem, valor, lida
                )
                select
                    v.cliente_id,
                    p.id,
                    schedule.tipo,
                    'vendedor',
                    schedule.agendada_para,
                    'pendente',
                    schedule.mensagem,
                    p.valor_restante,
                    false
                from parcelas p
                join vendas v on v.id = p.venda_id
                join clientes c on c.id = v.cliente_id
                cross join lateral (
                    values
                        (
                            'vence_amanha',
                            (p.data_vencimento - interval '1 day') + time '09:00',
                            'Parcela de ' || c.nome_completo ||
                            ' vence amanha.'
                        ),
                        (
                            'vence_hoje',
                            p.data_vencimento + time '09:00',
                            'Parcela de ' || c.nome_completo ||
                            ' vence hoje.'
                        ),
                        (
                            'atraso',
                            (p.data_vencimento + interval '1 day') + time '09:00',
                            'Parcela de ' || c.nome_completo ||
                            ' esta em atraso.'
                        )
                ) as schedule(tipo, agendada_para, mensagem)
                where p.valor_restante > 0
                  and (
                    cast(:installment_id as bigint) is null
                    or p.id = cast(:installment_id as bigint)
                  )
                on conflict (parcela_id, tipo_notificacao)
                    where tipo_notificacao in (
                        'vence_amanha', 'vence_hoje', 'atraso'
                    )
                do update set
                    agendada_para = excluded.agendada_para,
                    mensagem = excluded.mensagem,
                    valor = excluded.valor,
                    status = 'pendente',
                    lida = case
                        when notificacoes.agendada_para is distinct from
                             excluded.agendada_para
                            then false
                        else notificacoes.lida
                    end
                """
            ),
            {"installment_id": installment_id},
        )

    async def _notificacoes(self) -> list[NotificacaoOut]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select
                        n.id, n.cliente_id, n.parcela_id,
                        n.tipo_notificacao, n.agendada_para,
                        n.mensagem, n.valor, n.lida
                    from notificacoes n
                    left join parcelas p on p.id = n.parcela_id
                    where n.agendada_para <= current_timestamp
                      and (
                          n.tipo_notificacao = 'pagamento'
                          or (
                              coalesce(p.valor_restante, 0) > 0
                              and case n.tipo_notificacao
                                  when 'vence_amanha' then
                                      p.data_vencimento = current_date + 1
                                  when 'vence_hoje' then
                                      p.data_vencimento = current_date
                                  when 'atraso' then
                                      p.data_vencimento < current_date
                                  else true
                              end
                          )
                      )
                    order by n.lida, n.agendada_para desc
                    """
                )
            )
        ).mappings()
        return [_notification_from_row(row) for row in rows]

    async def _recalculate_summary(self, cliente_id: int) -> None:
        await self.session.execute(
            text(
                """
                insert into resumo_financeiro_cliente (
                    cliente_id, total_vendas, total_produtos_comprados,
                    valor_total_comprado, valor_total_pago, valor_total_em_aberto,
                    total_parcelas, total_parcelas_pagas, total_parcelas_atrasadas,
                    total_atrasos, data_ultima_venda, data_ultimo_pagamento,
                    score_pagador, status_pagador, atualizado_em
                )
                select
                    c.id,
                    coalesce(vs.total_vendas, 0),
                    coalesce(iv.total_produtos_comprados, 0),
                    coalesce(vs.valor_total_comprado, 0),
                    coalesce(vs.valor_entrada_total, 0) + coalesce(pg.valor_pago_total, 0),
                    coalesce(pa.valor_total_em_aberto, 0),
                    coalesce(pa.total_parcelas, 0),
                    coalesce(pa.total_parcelas_pagas, 0),
                    coalesce(pa.total_parcelas_atrasadas, 0),
                    coalesce(pa.total_parcelas_atrasadas, 0),
                    vs.data_ultima_venda,
                    pg.data_ultimo_pagamento,
                    case
                        when coalesce(pa.total_parcelas_atrasadas, 0) > 0 then 50
                        when coalesce(pa.valor_total_em_aberto, 0) > 0 then 75
                        else 95
                    end,
                    case
                        when coalesce(pa.total_parcelas_atrasadas, 0) > 0 then 'bad'
                        when coalesce(pa.valor_total_em_aberto, 0) > 0 then 'warn'
                        else 'good'
                    end,
                    current_timestamp
                from clientes c
                left join (
                    select cliente_id, count(*)::int as total_vendas,
                           sum(valor_total) as valor_total_comprado,
                           sum(valor_entrada) as valor_entrada_total,
                           max(data_venda) as data_ultima_venda
                    from vendas
                    group by cliente_id
                ) vs on vs.cliente_id = c.id
                left join (
                    select v.cliente_id, sum(i.quantidade)::int as total_produtos_comprados
                    from vendas v
                    join itens_venda i on i.venda_id = v.id
                    group by v.cliente_id
                ) iv on iv.cliente_id = c.id
                left join (
                    select v.cliente_id,
                           count(p.*)::int as total_parcelas,
                           count(*) filter (where p.status = 'paga')::int as total_parcelas_pagas,
                           count(*) filter (
                               where p.status <> 'paga' and p.data_vencimento < current_date
                           )::int as total_parcelas_atrasadas,
                           sum(p.valor_restante) filter (where p.status <> 'paga') as valor_total_em_aberto
                    from vendas v
                    join parcelas p on p.venda_id = v.id
                    group by v.cliente_id
                ) pa on pa.cliente_id = c.id
                left join (
                    select v.cliente_id,
                           sum(pg.valor_pago) as valor_pago_total,
                           max(pg.data_pagamento) as data_ultimo_pagamento
                    from vendas v
                    join parcelas p on p.venda_id = v.id
                    join pagamentos pg on pg.parcela_id = p.id
                    group by v.cliente_id
                ) pg on pg.cliente_id = c.id
                where c.id = :cliente_id
                on conflict (cliente_id) do update set
                    total_vendas = excluded.total_vendas,
                    total_produtos_comprados = excluded.total_produtos_comprados,
                    valor_total_comprado = excluded.valor_total_comprado,
                    valor_total_pago = excluded.valor_total_pago,
                    valor_total_em_aberto = excluded.valor_total_em_aberto,
                    total_parcelas = excluded.total_parcelas,
                    total_parcelas_pagas = excluded.total_parcelas_pagas,
                    total_parcelas_atrasadas = excluded.total_parcelas_atrasadas,
                    total_atrasos = excluded.total_atrasos,
                    data_ultima_venda = excluded.data_ultima_venda,
                    data_ultimo_pagamento = excluded.data_ultimo_pagamento,
                    score_pagador = excluded.score_pagador,
                    status_pagador = excluded.status_pagador,
                    atualizado_em = current_timestamp
                """
            ),
            {"cliente_id": cliente_id},
        )


def _client_from_row(row) -> ClienteOut:
    return ClienteOut(
        id=str(row["id"]),
        nome=row["nome_completo"],
        telefone=row["telefone"],
        bairro=row["bairro"],
        score=int(row["score"]),
        status=row["status_pagador"],
        em_aberto=float(row["em_aberto"]),
        total_compras=int(row["total_compras"]),
        parcelas_atraso=int(row["parcelas_atraso"]),
        total_comprado=float(row["total_comprado"]),
    )


def _produto_from_row(row) -> ProdutoOut:
    model_path = row["caminho_arquivo_modelo"]
    preview_img = row["caminho_imagem_preview"]
    return ProdutoOut(
        id=str(row["id"]),
        nome=row["nome"],
        categoria=row["categoria"],
        preco_base=float(row["preco_base"]),
        custo=float(row["custo"]),
        estoque=int(row["estoque"]),
        estoque_minimo=int(row["estoque_minimo"]),
        volume_ml=int(row["volume_ml"]),
        frasco_color_value=int(row["frasco_color_value"]),
        tem_3d=bool(row["possui_modelo_3d"] or model_path),
        modelo_3d_path=model_path,
        preview_img=preview_img,
    )


def _installment_from_row(
    row,
    events: list[EventoParcelaOut] | None = None,
) -> ParcelaOut:
    return ParcelaOut(
        id=str(row["id"]),
        venda_id=str(row["venda_id"]),
        numero=int(row["numero_parcela"]),
        total=int(row["numero_parcelas"]),
        valor=float(row["valor_original"]),
        vencimento=as_datetime(row["data_vencimento"]),
        status=row["status"],
        valor_pago=float(row["valor_pago"]),
        eventos=events or [],
    )


def _payment_from_row(row) -> PagamentoOut:
    return PagamentoOut(
        id=str(row["id"]),
        parcela_id=str(row["parcela_id"]),
        data=as_datetime(row["data_pagamento"]),
        valor=float(row["valor_pago"]),
        forma=row["forma_pagamento"],
        observacoes=row["observacoes"],
    )


def _notification_from_row(row) -> NotificacaoOut:
    return NotificacaoOut(
        id=str(row["id"]),
        cliente_id=str(row["cliente_id"]),
        parcela_id=str(row["parcela_id"]),
        tipo=_notification_type(row["tipo_notificacao"]),
        data=row["agendada_para"],
        texto=row["mensagem"] or "",
        valor=float(row["valor"]),
        lida=bool(row["lida"]),
    )


def _parse_db_id(raw: str, label: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"ID de {label} invalido: {raw}") from exc


def _notification_type(raw: str) -> str:
    mapping = {
        "vence_hoje": "venceHoje",
        "venceHoje": "venceHoje",
        "vence_amanha": "venceAmanha",
        "venceAmanha": "venceAmanha",
        "atraso": "atraso",
        "pagamento": "pagamento",
    }
    return mapping.get(raw, raw)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)
