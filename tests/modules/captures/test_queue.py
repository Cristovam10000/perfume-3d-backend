from __future__ import annotations

import asyncio

import pytest

from app.modules.captures.queue import ProcessingQueue


class TestProcessingQueue:
    @pytest.mark.asyncio
    async def test_submit_dispatches_to_handler(self):
        received: list[str] = []

        async def handler(job_id: str) -> None:
            received.append(job_id)

        queue = ProcessingQueue()
        queue.start(handler)
        await queue.submit("job-1")
        await queue.submit("job-2")
        await queue.join()
        await queue.stop()

        assert received == ["job-1", "job-2"]

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_worker(self):
        calls: list[str] = []

        async def handler(job_id: str) -> None:
            calls.append(job_id)
            if job_id == "boom":
                raise RuntimeError("falha simulada")

        queue = ProcessingQueue()
        queue.start(handler)
        await queue.submit("job-1")
        await queue.submit("boom")
        await queue.submit("job-2")
        await queue.join()
        await queue.stop()

        assert calls == ["job-1", "boom", "job-2"]

    @pytest.mark.asyncio
    async def test_start_twice_raises(self):
        async def handler(_: str) -> None:
            pass

        queue = ProcessingQueue()
        queue.start(handler)
        try:
            with pytest.raises(RuntimeError):
                queue.start(handler)
        finally:
            await queue.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        queue = ProcessingQueue()
        await queue.stop()  # sem start anterior
        await queue.stop()  # e de novo

    @pytest.mark.asyncio
    async def test_stop_cancels_running_worker(self):
        started = asyncio.Event()

        async def handler(_: str) -> None:
            started.set()
            await asyncio.sleep(10)

        queue = ProcessingQueue()
        queue.start(handler)
        await queue.submit("job-lento")
        await started.wait()
        await queue.stop()  # precisa cancelar mesmo com handler travado
