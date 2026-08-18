"""Identidade pública e compatibilidade de configuração do CoerIA."""

from __future__ import annotations

import os


APP_NAME = "CoerIA"
APP_VERSION = (os.getenv("COERIA_APP_VERSION", "0.2.1").strip() or "0.2.1")
APP_FULL_NAME = (
    "Sistema de IA com agentes para elaboração de programas de unidades "
    "curriculares e recursos educativos pedagogicamente alinhados"
)
APP_TAGLINE = "Do programa da UC aos recursos educativos alinhados"
LEGACY_APP_NAMES = ("AGIR-SOLO", "AlignUC", "PRISM")


def config_value(suffix: str, default: str = "") -> str:
    """Lê a configuração CoerIA, aceitando prefixos legados como fallback."""

    return (
        os.getenv(f"COERIA_{suffix}")
        or os.getenv(f"AGIR_SOLO_{suffix}")
        or os.getenv(f"PRISM_{suffix}")
        or default
    )
