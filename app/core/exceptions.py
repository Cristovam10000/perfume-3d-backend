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
