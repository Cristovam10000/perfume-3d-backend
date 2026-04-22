from pydantic import BaseModel, Field


class CreateCaptureResponse(BaseModel):
    """Resposta de POST /captures. Formato espelha o contrato do app Flutter."""

    job_id: str = Field(..., serialization_alias="jobId")

    model_config = {"populate_by_name": True}


class CaptureStatusResponse(BaseModel):
    """Resposta de GET /captures/{jobId}/status.

    Campos com aliases em camelCase para casar com o parser do front
    (processing_repository.dart). Campos None são serializados como null.
    """

    status: str
    message: str | None = None
    model_url: str | None = Field(default=None, serialization_alias="modelUrl")
    error: str | None = None

    model_config = {"populate_by_name": True}
