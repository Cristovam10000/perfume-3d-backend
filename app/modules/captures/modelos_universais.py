"""Modelo SQLAlchemy da tabela `modelos_3d_universais` (cache global cross-tenant).

A tabela e a chave do cache: cada linha guarda um GLB gerado pelo Hunyuan +
embedding CLIP + metadata. A busca por similaridade percorre todas as linhas e
escolhe a mais parecida com as fotos novas.

Caracteristicas:
- **Cache global**: nao tem FK para `produtos`. Vinculo com produto comercial
  (por tenant) acontece em `modelos_3d_produto.modelo_universal_id`. Permite que
  vendedores diferentes apontem para o mesmo molde.
- **Embedding em bytea**: 512 floats float32 = 2KB por linha. Busca linear ate
  ~10k entradas; acima troca-se a impl mantendo a ABC `ModelCache`.
- **Schema gerenciado por `ensure_captures_schema`** (estilo `ensure_sales_schema`),
  porque a tabela `modelos_3d_produto` existente precisa ganhar a coluna
  `modelo_universal_id` via ALTER TABLE IF NOT EXISTS — `create_all()` do
  SQLAlchemy nao mexe em tabelas que ele nao criou.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class ModeloUniversal(Base):
    """Entrada do cache global de moldes 3D.

    Uma linha = um GLB gerado pelo Hunyuan para um frasco especifico,
    identificado pelo embedding visual das fotos que o originaram.
    """

    __tablename__ = "modelos_3d_universais"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    caminho_arquivo_modelo: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    liquid_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    label_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_hit_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


async def ensure_captures_schema(engine: AsyncEngine) -> None:
    """Cria/migra tabelas do captures que nao sao 100% gerenciadas pelo ORM.

    Em particular, `modelos_3d_produto` ja existe no banco com um schema
    pre-existente fora do controle do SQLAlchemy do backend. Aqui apenas
    adicionamos a coluna `modelo_universal_id` (FK opcional para
    `modelos_3d_universais`) sem mexer no resto do schema dela.

    A tabela `modelos_3d_universais` em si e criada pelo `Base.metadata.create_all()`
    via importacao deste modulo em `database.py`. Esta funcao garante apenas a
    coluna nova em `modelos_3d_produto` + indice associado.

    Idempotente: roda sempre no startup; faz nada se a coluna ja existe.
    """
    statements = [
        # Coluna nova ligando o modelo do produto (por tenant) ao molde universal.
        "ALTER TABLE IF EXISTS modelos_3d_produto "
        "ADD COLUMN IF NOT EXISTS modelo_universal_id varchar(36)",
        # Indice para o JOIN inverso (universal -> produtos que o usam).
        "CREATE INDEX IF NOT EXISTS idx_modelos_3d_produto_universal "
        "ON modelos_3d_produto(modelo_universal_id)",
        # product_id opcional em capture_jobs (ambientes antigos podem nao ter).
        "ALTER TABLE IF EXISTS capture_jobs "
        "ADD COLUMN IF NOT EXISTS product_id bigint",
        "CREATE INDEX IF NOT EXISTS idx_capture_jobs_product_id "
        "ON capture_jobs(product_id)",
        # view do app guiado em capture_images (front/left/back/right/extra).
        # NULL = cliente legado, dispara CLIPViewRouter no pipeline.
        "ALTER TABLE IF EXISTS capture_images "
        "ADD COLUMN IF NOT EXISTS view varchar(16)",
        # material do frasco informado pelo usuario (glass|opaque) em
        # capture_jobs. NULL = nao informado, o pipeline usa o CLIP.
        "ALTER TABLE IF EXISTS capture_jobs "
        "ADD COLUMN IF NOT EXISTS material varchar(16)",
    ]

    # A constraint de FK e adicionada separadamente porque Postgres nao tem
    # IF NOT EXISTS para ADD CONSTRAINT; checamos no information_schema antes.
    add_fk = """
        do $$
        begin
            if not exists (
                select 1
                from information_schema.table_constraints
                where table_name = 'modelos_3d_produto'
                  and constraint_name = 'fk_modelos_3d_produto_universal'
            ) then
                alter table modelos_3d_produto
                add constraint fk_modelos_3d_produto_universal
                foreign key (modelo_universal_id)
                references modelos_3d_universais(id)
                on delete set null;
            end if;
        end$$;
    """

    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))
        await conn.execute(text(add_fk))
