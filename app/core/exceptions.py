from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Erro de domínio da aplicação. Mapeado para HTTP na camada de rotas."""

    status_code: int = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ValidationError(AppError):
    status_code = 422


def register_exception_handlers(app: FastAPI) -> None:
    """Converte AppError em JSON HTTP consistente.

    Chamado tanto pelo bootstrap da app quanto pelas fixtures de teste, para
    que o tratamento seja idêntico nos dois contextos.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message},
        )
