"""Configuración compartida por la aplicación, el índice y la evaluación."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
CACHE = RAIZ / ".avesco"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
CHAT_NVIDIA = "nvidia/nemotron-3.5-lightning-30b-a3b"
EMBED_NVIDIA = "nvidia/nemotron-3.5-embed-1b"


@dataclass(frozen=True)
class Configuracion:
    modo: str
    clave_nvidia: str = field(repr=False)
    modelo_chat: str
    modelo_embed: str
    tolerancia_tamano: float
    umbral_similitud: float

    @classmethod
    def cargar(cls, modo="auto"):
        load_dotenv(RAIZ / ".env")
        clave = os.getenv("NVIDIA_API_KEY", "").strip()
        if modo == "auto":
            modo = "nvidia" if clave else "local"
        if modo == "nvidia" and not clave:
            raise ValueError("Configura NVIDIA_API_KEY en .env para usar el modo NVIDIA.")
        tolerancia = float(os.getenv("TOLERANCIA_TAMANO", "0.20"))
        umbral = float(os.getenv(f"UMBRAL_{modo.upper()}", "0.80" if modo == "local" else "0.26"))
        if not 0 <= tolerancia <= 1 or not -1 <= umbral <= 1:
            raise ValueError("Revisa TOLERANCIA_TAMANO y el umbral de similitud en .env.")
        return cls(
            modo, clave, os.getenv("NVIDIA_CHAT_MODEL", CHAT_NVIDIA),
            os.getenv("NVIDIA_EMBED_MODEL", EMBED_NVIDIA), tolerancia, umbral,
        )


def opcion_modo(parser):
    parser.add_argument("--modo", choices=("auto", "local", "nvidia"), default="auto",
                        help="Auto usa NVIDIA si hay una clave configurada.")
