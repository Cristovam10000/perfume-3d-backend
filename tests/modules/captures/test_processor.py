from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.modules.captures.processor import (
    FakeProcessor,
    Processor,
    ProcessingInput,
    _build_cube_glb,
)


def _assert_valid_glb(data: bytes) -> None:
    """Verifica header + layout mínimo de um binário glTF 2.0."""
    assert len(data) >= 20, "GLB muito pequeno para conter header + chunk JSON"

    magic, version, total_length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "Magic header deve ser 'glTF'"
    assert version == 2, "Apenas glTF 2.0 é suportado"
    assert total_length == len(data), "Campo length do header não bate com o tamanho real"

    # Primeiro chunk deve ser JSON.
    json_chunk_length, json_chunk_type = struct.unpack_from("<II", data, 12)
    assert json_chunk_type == 0x4E4F534A, "Primeiro chunk precisa ser JSON"
    assert json_chunk_length % 4 == 0, "Chunk JSON deve ser múltiplo de 4"


class TestBuildCubeGlb:
    def test_bytes_form_valid_glb_header(self):
        data = _build_cube_glb()
        _assert_valid_glb(data)

    def test_contains_bin_chunk_after_json(self):
        data = _build_cube_glb()
        json_len = struct.unpack_from("<I", data, 12)[0]
        bin_offset = 12 + 8 + json_len
        bin_len, bin_type = struct.unpack_from("<II", data, bin_offset)
        assert bin_type == 0x004E4942, "Segundo chunk precisa ser BIN"
        assert bin_len > 0, "Buffer binário do cubo não pode ser vazio"


class TestFakeProcessor:
    def test_is_processor_subclass(self):
        assert issubclass(FakeProcessor, Processor)

    @pytest.mark.asyncio
    async def test_writes_valid_glb_to_output_path(self, tmp_path: Path):
        output = tmp_path / "models" / "job-123.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        result = await processor.process(
            ProcessingInput(
                job_id="job-123",
                image_paths=[tmp_path / "a.jpg", tmp_path / "b.jpg"],
                output_path=output,
            )
        )

        assert result.output_path == output
        assert output.exists(), "Processor deveria ter criado o arquivo .glb"
        _assert_valid_glb(output.read_bytes())

    @pytest.mark.asyncio
    async def test_creates_parent_directory_if_missing(self, tmp_path: Path):
        output = tmp_path / "does" / "not" / "exist" / "model.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        await processor.process(
            ProcessingInput(
                job_id="job-xyz",
                image_paths=[],
                output_path=output,
            )
        )

        assert output.exists()

    @pytest.mark.asyncio
    async def test_message_mentions_image_count(self, tmp_path: Path):
        output = tmp_path / "model.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        result = await processor.process(
            ProcessingInput(
                job_id="j",
                image_paths=[tmp_path / f"{i}.jpg" for i in range(7)],
                output_path=output,
            )
        )

        assert "7" in result.message
