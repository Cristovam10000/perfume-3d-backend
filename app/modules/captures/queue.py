from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from ...core.logging import get_logger

_log = get_logger("captures.queue")

JobHandler = Callable[[str], Awaitable[None]]


class ProcessingQueue:
    """Fila FIFO in-process que despacha `job_id`s para um handler assíncrono.

    A fila é intencionalmente genérica — ela não conhece o `CaptureService`.
    No bootstrap, `start(handler=service.process_job)` amarra os dois sem criar
    dependência circular. Para MVP um único worker basta; aumentar workers é
    só trocar `_loop` por N tasks.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._handler: JobHandler | None = None

    async def submit(self, job_id: str) -> None:
        await self._queue.put(job_id)

    def start(self, handler: JobHandler) -> None:
        if self._task is not None:
            raise RuntimeError("ProcessingQueue já está em execução")
        self._handler = handler
        self._task = asyncio.create_task(self._loop(), name="captures.queue.worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._handler = None

    async def join(self) -> None:
        """Aguarda a fila drenar. Usado principalmente nos testes."""
        await self._queue.join()

    async def _loop(self) -> None:
        assert self._handler is not None, "start() não foi chamado com handler"
        while True:
            job_id = await self._queue.get()
            try:
                await self._handler(job_id)
            except Exception:
                # Vaza do handler não derruba o worker — apenas loga.
                # O próprio handler é responsável por marcar o job como `error`.
                _log.exception("Falha ao processar job %s", job_id)
            finally:
                self._queue.task_done()
