from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.exceptions import ValidationError
from app.modules.captures.processor import (
    ProcessingInput,
    ProcessingResult,
    Processor,
)
from app.modules.captures.service import CaptureService, IncomingImage
from app.modules.captures.status import CaptureStatus
from app.storage.local_storage import LocalStorage


class _RecordingProcessor(Processor):
    """Processor fake que grava os inputs e opcionalmente estoura."""

    def __init__(self, should_fail: bool = False, com_preview: bool = False):
        self.calls: list[ProcessingInput] = []
        self.should_fail = should_fail
        self.com_preview = com_preview

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self.calls.append(input)
        if self.should_fail:
            raise RuntimeError("falha simulada no pipeline")
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(b"fake-glb")
        preview: Path | None = None
        if self.com_preview:
            preview = input.output_path.with_suffix(".png")
            preview.write_bytes(b"\x89PNG")
        return ProcessingResult(
            output_path=input.output_path,
            message="ok",
            preview_path=preview,
        )


class _StubQueue:
    """Captura o que o service tentaria filar, sem rodar nada."""

    def __init__(self):
        self.submitted: list[str] = []

    async def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


@dataclass
class _Fixtures:
    service: CaptureService
    processor: _RecordingProcessor
    queue: _StubQueue
    storage: LocalStorage


def _make_fixtures(
    session_factory,
    tmp_path: Path,
    *,
    fail: bool = False,
    com_preview: bool = False,
) -> _Fixtures:
    storage = LocalStorage(root=tmp_path / "storage")
    storage.ensure_dirs()
    processor = _RecordingProcessor(should_fail=fail, com_preview=com_preview)
    queue = _StubQueue()
    service = CaptureService(session_factory, storage, processor, queue)  # type: ignore[arg-type]
    return _Fixtures(service=service, processor=processor, queue=queue, storage=storage)


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_rejects_empty_image_list(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)
        with pytest.raises(ValidationError):
            await fx.service.create_job([])
        assert fx.queue.submitted == []

    @pytest.mark.asyncio
    async def test_persists_job_and_images_and_enqueues(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)

        images = [
            IncomingImage(filename="001.jpg", content=b"\xff\xd8\xff\x00img1"),
            IncomingImage(filename="002.jpg", content=b"\xff\xd8\xff\x00img2"),
        ]
        job_id = await fx.service.create_job(images)

        # Fila recebeu exatamente este jobId.
        assert fx.queue.submitted == [job_id]

        # Job existe no DB com status inicial e 2 imagens salvas.
        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.WAITING.value
        assert len(job.images) == 2
        # product_id nao foi passado -> None.
        assert job.product_id is None

        # Arquivos gravados em disco.
        for img in job.images:
            assert Path(img.path).exists()

    @pytest.mark.asyncio
    async def test_create_job_persists_product_id_when_passed(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)
        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")],
            product_id=99,
        )
        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.product_id == 99


class TestProcessJob:
    @pytest.mark.asyncio
    async def test_happy_path_marks_completed_with_model_url(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await fx.service.process_job(job_id)

        # Processor recebeu o output_path correto.
        assert len(fx.processor.calls) == 1
        call = fx.processor.calls[0]
        assert call.job_id == job_id
        assert call.output_path == fx.storage.model_path(job_id)
        assert call.product_id is None

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.COMPLETED.value
        assert job.model_path == f"/files/models/{job_id}.glb"
        assert job.error is None

    @pytest.mark.asyncio
    async def test_product_id_propagates_to_processor(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)
        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")],
            product_id=42,
        )
        await fx.service.process_job(job_id)
        # O ProcessingInput recebeu product_id=42 lido do banco.
        assert fx.processor.calls[0].product_id == 42

    @pytest.mark.asyncio
    async def test_processor_failure_marks_error_and_rethrows(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path, fail=True)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        with pytest.raises(RuntimeError):
            await fx.service.process_job(job_id)

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.ERROR.value
        assert job.error is not None
        assert "falha simulada" in job.error

    @pytest.mark.asyncio
    async def test_nonexistent_job_is_silently_skipped(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)
        # Nenhum processor.call deve acontecer.
        await fx.service.process_job("job-que-nao-existe")
        assert fx.processor.calls == []


async def _criar_tabelas_do_tenant(session_factory) -> None:
    """Cria `produtos` e `modelos_3d_produto` no SQLite do teste.

    As duas nascem fora do SQLAlchemy do backend (schema preexistente do
    sistema comercial), entao a fixture `session_factory` nao as cria. Aqui vai
    so o subconjunto de colunas que o vinculo toca.
    """
    async with session_factory() as session:
        await session.execute(
            text(
                "CREATE TABLE produtos ("
                "  id INTEGER PRIMARY KEY, nome TEXT, "
                "  possui_modelo_3d BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        await session.execute(
            text(
                "CREATE TABLE modelos_3d_produto ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "  produto_id INTEGER NOT NULL UNIQUE, "
                "  caminho_arquivo_modelo TEXT NOT NULL, "
                "  caminho_imagem_preview TEXT, "
                "  status TEXT NOT NULL, "
                "  criado_em TIMESTAMP NOT NULL, "
                "  atualizado_em TIMESTAMP NOT NULL, "
                "  capture_job_id TEXT, "
                "  modelo_universal_id TEXT)"
            )
        )
        await session.execute(
            text("INSERT INTO produtos (id, nome, possui_modelo_3d) VALUES (7, 'X', 0)")
        )
        await session.commit()


async def _linha_do_produto(session_factory, produto_id: int):
    async with session_factory() as session:
        resultado = await session.execute(
            text(
                "SELECT m.caminho_arquivo_modelo, m.capture_job_id, m.status, "
                "       p.possui_modelo_3d "
                "FROM modelos_3d_produto m JOIN produtos p ON p.id = m.produto_id "
                "WHERE m.produto_id = :pid"
            ),
            {"pid": produto_id},
        )
        return resultado.mappings().one_or_none()


class TestVinculoComProduto:
    """O produto so mostra o 3D depois que `modelos_3d_produto` aponta para o GLB.

    Esse vinculo morava dentro do `ModelCache.store()` e, com `CACHE_ENABLED=false`,
    nunca era escrito: o job concluia, o GLB existia em disco e o app seguia
    mostrando o placeholder. Estes testes prendem o vinculo no service, onde ele
    independe do cache.
    """

    @pytest.mark.asyncio
    async def test_job_com_produto_grava_vinculo_e_liga_a_flag(
        self, session_factory, tmp_path
    ):
        await _criar_tabelas_do_tenant(session_factory)
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")],
            product_id=7,
        )
        await fx.service.process_job(job_id)

        linha = await _linha_do_produto(session_factory, 7)
        assert linha is not None, "produto ficou sem vinculo apos o job concluir"
        # URL publica, nao caminho de disco: o app resolve essa string como URL.
        assert linha["caminho_arquivo_modelo"] == f"/files/models/{job_id}.glb"
        assert linha["capture_job_id"] == job_id
        assert linha["status"] == "completo"
        assert bool(linha["possui_modelo_3d"]) is True

    @pytest.mark.asyncio
    async def test_segundo_job_do_mesmo_produto_substitui_o_vinculo(
        self, session_factory, tmp_path
    ):
        """UNIQUE(produto_id): regerar o molde troca o modelo, nao duplica linha."""
        await _criar_tabelas_do_tenant(session_factory)
        fx = _make_fixtures(session_factory, tmp_path)

        primeiro = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")], product_id=7
        )
        await fx.service.process_job(primeiro)
        segundo = await fx.service.create_job(
            [IncomingImage(filename="b.jpg", content=b"b")], product_id=7
        )
        await fx.service.process_job(segundo)

        async with session_factory() as session:
            total = await session.execute(
                text("SELECT count(*) FROM modelos_3d_produto WHERE produto_id = 7")
            )
            assert total.scalar_one() == 1

        linha = await _linha_do_produto(session_factory, 7)
        assert linha is not None
        assert linha["capture_job_id"] == segundo

    @pytest.mark.asyncio
    async def test_falha_no_vinculo_nao_perde_o_modelo(
        self, session_factory, tmp_path
    ):
        """Sem as tabelas do tenant o vinculo estoura — o job conclui assim mesmo.

        O GLB foi gerado e continua servivel; o que nao pode e a falha sumir,
        entao ela vai para a `message`, que o app mostra.
        """
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")], product_id=7
        )
        await fx.service.process_job(job_id)

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.COMPLETED.value
        assert job.model_path == f"/files/models/{job_id}.glb"
        assert job.message is not None
        assert "nao vinculado ao produto" in job.message

    @pytest.mark.asyncio
    async def test_preview_renderizado_vai_para_o_card(
        self, session_factory, tmp_path
    ):
        await _criar_tabelas_do_tenant(session_factory)
        fx = _make_fixtures(session_factory, tmp_path, com_preview=True)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")], product_id=7
        )
        await fx.service.process_job(job_id)

        async with session_factory() as session:
            preview = await session.execute(
                text(
                    "SELECT caminho_imagem_preview FROM modelos_3d_produto "
                    "WHERE produto_id = 7"
                )
            )
            assert preview.scalar_one() == f"/files/models/{job_id}.png"

    @pytest.mark.asyncio
    async def test_sem_preview_a_coluna_fica_nula(self, session_factory, tmp_path):
        """Preview e opcional: o card volta ao visual generico, o resto segue."""
        await _criar_tabelas_do_tenant(session_factory)
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")], product_id=7
        )
        await fx.service.process_job(job_id)

        linha = await _linha_do_produto(session_factory, 7)
        assert linha is not None
        assert linha["caminho_arquivo_modelo"] == f"/files/models/{job_id}.glb"
        async with session_factory() as session:
            preview = await session.execute(
                text(
                    "SELECT caminho_imagem_preview FROM modelos_3d_produto "
                    "WHERE produto_id = 7"
                )
            )
            assert preview.scalar_one() is None

    @pytest.mark.asyncio
    async def test_regerar_sem_preview_preserva_o_preview_anterior(
        self, session_factory, tmp_path
    ):
        """COALESCE no UPSERT: regerar o modelo nao pode piorar o card.

        Se o primeiro job rendeu preview e o segundo falhou nesse estagio, o
        card deve continuar mostrando o render antigo em vez de voltar ao
        gradiente.
        """
        await _criar_tabelas_do_tenant(session_factory)

        com_preview = _make_fixtures(session_factory, tmp_path, com_preview=True)
        primeiro = await com_preview.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")], product_id=7
        )
        await com_preview.service.process_job(primeiro)

        sem_preview = _make_fixtures(session_factory, tmp_path)
        segundo = await sem_preview.service.create_job(
            [IncomingImage(filename="b.jpg", content=b"b")], product_id=7
        )
        await sem_preview.service.process_job(segundo)

        async with session_factory() as session:
            linha = await session.execute(
                text(
                    "SELECT caminho_arquivo_modelo, caminho_imagem_preview "
                    "FROM modelos_3d_produto WHERE produto_id = 7"
                )
            )
            atual = linha.mappings().one()
        # GLB novo, preview antigo.
        assert atual["caminho_arquivo_modelo"] == f"/files/models/{segundo}.glb"
        assert atual["caminho_imagem_preview"] == f"/files/models/{primeiro}.png"

    @pytest.mark.asyncio
    async def test_job_sem_produto_nao_toca_a_tabela(self, session_factory, tmp_path):
        await _criar_tabelas_do_tenant(session_factory)
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await fx.service.process_job(job_id)

        async with session_factory() as session:
            total = await session.execute(
                text("SELECT count(*) FROM modelos_3d_produto")
            )
            assert total.scalar_one() == 0
        job = await fx.service.get_job(job_id)
        assert job is not None and job.message == "ok"
