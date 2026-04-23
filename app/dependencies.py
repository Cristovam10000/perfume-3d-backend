from fastapi import Request

from .modules.captures.service import CaptureService


def get_capture_service(request: Request) -> CaptureService:
    """Injeta o CaptureService registrado em `app.state` durante o lifespan.

    Manter o service em `app.state` (em vez de um singleton global) facilita
    criar apps isoladas nos testes sem alinhar estado global.
    """
    service = getattr(request.app.state, "capture_service", None)
    if service is None:
        raise RuntimeError(
            "CaptureService não configurado em app.state — verifique o lifespan."
        )
    return service
