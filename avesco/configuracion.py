# Carga las opciones que comparten la interfaz, el índice y la evaluación.
"""Configuración compartida por la aplicación, el índice y la evaluación."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
CACHE = RAIZ / ".avesco"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
CHAT_NVIDIA = "nvidia/nemotron-3.5-lightning-30b-a3b"
EMBED_NVIDIA = "nvidia/nemotron-3.5-embed-1b"


@dataclass(frozen=True)
class Configuracion:
    modo: ClassVar[str] = "nvidia"
    clave_nvidia: str = field(repr=False)
    modelo_chat: str
    modelo_embed: str
    tolerancia_tamano: float
    umbral_similitud: float

    @classmethod
    def cargar(cls):
        # Construye el objeto compartido a partir de sus archivos o su configuración.
        load_dotenv(RAIZ / ".env")
        clave = os.getenv("NVIDIA_API_KEY", "").strip()
        if not clave:
            raise ValueError("Configura NVIDIA_API_KEY en .env para conectarte a NVIDIA NIM.")
        # El margen de 20 % contempla la incertidumbre de una medida aproximada.
        tolerancia = float(os.getenv("TOLERANCIA_TAMANO", "0.20"))
        # El valor 0,26 es el umbral general que se ajustó con casos de calibración.
        umbral = float(os.getenv("UMBRAL_NVIDIA", "0.26"))
        if not 0 <= tolerancia <= 1 or not -1 <= umbral <= 1:
            # El margen de 20 % contempla la incertidumbre de una medida aproximada.
            raise ValueError("Revisa TOLERANCIA_TAMANO y el umbral de similitud en .env.")
        return cls(
            clave, os.getenv("NVIDIA_CHAT_MODEL", CHAT_NVIDIA),
            os.getenv("NVIDIA_EMBED_MODEL", EMBED_NVIDIA), tolerancia, umbral,
        )
