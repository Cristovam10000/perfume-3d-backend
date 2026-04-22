from enum import Enum


class CaptureStatus(str, Enum):
    """Valores idênticos aos que o parser do Flutter reconhece.

    Ver: front/lib/features/processing/domain/processing_job.dart
    Qualquer valor fora desta lista cai em `idle` no cliente.
    """

    WAITING = "waiting"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self in (CaptureStatus.COMPLETED, CaptureStatus.ERROR)
