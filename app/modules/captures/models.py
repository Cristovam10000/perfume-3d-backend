from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base
from .status import CaptureStatus


class CaptureJob(Base):
    __tablename__ = "capture_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CaptureStatus.WAITING.value,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # product_id opcional: quando o POST /captures vem amarrado a um produto 
    # do tenant (em /sales). Usado pelo IntegratedPipeline para fazer UPSERT
    # em modelos_3d_produto ao final do pipeline.
    product_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Material do frasco informado pelo usuário no app ("glass" | "opaque").
    # NULL = não informado; o pipeline cai no ClipTransparencyClassifier.
    # Existe porque o CLIP não separa as classes: um frasco de vidro chegou a
    # pontuar abaixo de um opaco (ver docs/16), então nenhum threshold acerta
    # os dois. Um toque na tela acerta sempre.
    material: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    images: Mapped[list[CaptureImage]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CaptureImage(Base):
    __tablename__ = "capture_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capture_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    # Rótulo de vista enviado pelo cliente quando o app captura em modo
    # guiado (front/left/back/right/extra). Quando NULL, o pipeline recorre
    # ao CLIPViewRouter para decidir a vista por similaridade.
    view: Mapped[str | None] = mapped_column(String(16), nullable=True)

    job: Mapped[CaptureJob] = relationship(back_populates="images")
