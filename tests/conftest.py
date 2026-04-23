"""Configuração global do pytest.

Garante que o pacote `app` seja importável nos testes, independentemente do
cwd em que `pytest` for chamado.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACK_ROOT = Path(__file__).resolve().parent.parent
if str(_BACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACK_ROOT))
