"""Carga las fichas y comprueba que sus citas estén en el catálogo."""

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from avesco.configuracion import DATA


def leer_jsonl(ruta: Path):
    filas = {}
    with ruta.open(encoding="utf-8") as archivo:
        for numero, linea in enumerate(archivo, start=1):
            fila = json.loads(linea)
            id_ave = fila["id"]
            if id_ave in filas:
                raise ValueError(f"ID repetido en {ruta.name}:{numero}: {id_ave}")
            filas[id_ave] = fila
    return filas


def aplicar_complementos(carpeta, aves, fichas, evidencias, fuentes, vocab):
    """Añade rasgos documentados sin atribuirlos a las fuentes del catálogo base."""
    ruta = carpeta / "complementos.json"
    if not ruta.is_file():
        return b""
    contenido = ruta.read_bytes()
    for cambio in json.loads(contenido)["complementos"]:
        id_ave = cambio["id"]
        if id_ave not in aves:
            raise ValueError(f"Complemento de una especie desconocida: {id_ave}")
        fuente = cambio["fuente"]
        if fuente["id"] in fuentes and fuentes[fuente["id"]] != fuente:
            raise ValueError(f"Fuente complementaria incompatible: {fuente['id']}")
        colores = cambio["colores_adicionales"]
        if not set(colores).issubset(vocab["colores_principales"]):
            raise ValueError(f"Color complementario fuera del vocabulario: {id_ave}")
        fuentes[fuente["id"]] = fuente
        descripcion = cambio["descripcion_adicional"].strip()
        if not descripcion:
            raise ValueError(f"Descripción complementaria vacía: {id_ave}")
        aves[id_ave]["colores_principales"] = list(dict.fromkeys([*aves[id_ave]["colores_principales"], *colores]))
        aves[id_ave]["descripcion_plumaje"] = aves[id_ave]["descripcion_plumaje"].rstrip(".") + ". " + descripcion
        fichas[id_ave]["texto"] += " Descripción complementaria: " + descripcion
        for campo in ("colores_principales", "descripcion_plumaje"):
            evidencias[id_ave]["campos"][campo].append({
                "fuente_id": fuente["id"], "url": fuente["url"],
                "localizador": cambio["localizador"], "evidencia": descripcion,
            })
    return contenido


@dataclass
class Catalogo:
    aves: dict
    fichas: dict
    evidencias: dict
    fuentes: dict
    vocabularios: dict
    huella_fichas: str

    @classmethod
    def cargar(cls, carpeta=DATA):
        procesados = carpeta / "processed"
        ruta_fichas = procesados / "fichas_rag.jsonl"
        fichas = leer_jsonl(ruta_fichas)
        aves = leer_jsonl(procesados / "aves.jsonl")
        evidencias = leer_jsonl(procesados / "evidencias.jsonl")
        if len(aves) != 120 or set(aves) != set(fichas) or set(aves) != set(evidencias):
            raise ValueError("El catálogo, las fichas y las evidencias deben tener los mismos 120 IDs.")
        with (carpeta / "fuentes.csv").open(encoding="utf-8-sig", newline="") as archivo:
            fuentes = {fila["id"]: fila for fila in csv.DictReader(archivo)}
        vocab = json.loads((carpeta / "vocabularios.json").read_text(encoding="utf-8"))
        complementos = aplicar_complementos(carpeta, aves, fichas, evidencias, fuentes, vocab)
        for id_ave, ave in aves.items():
            bajo, alto = ave["longitud_min_cm"], ave["longitud_max_cm"]
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (bajo, alto)) or not 0 < bajo <= alto:
                raise ValueError(f"Longitud inválida para {id_ave}.")
            if not fichas[id_ave]["texto"].strip() or fichas[id_ave]["nombre_cientifico"] != ave["nombre_cientifico"]:
                raise ValueError(f"Ficha incompatible con {id_ave}.")
            campos = evidencias[id_ave]["campos"]
            for campo in ("nombre_comun", "longitud_min_cm", "longitud_max_cm", "colores_principales",
                          "descripcion_plumaje", "dieta", "entorno"):
                if ave[campo] is not None and not campos.get(campo):
                    raise ValueError(f"Falta evidencia para {id_ave}/{campo}.")
            for referencias in campos.values():
                for referencia in referencias:
                    url = urlsplit(referencia["url"])
                    if referencia["fuente_id"] not in fuentes or url.scheme != "https" or not url.hostname:
                        raise ValueError(f"Cita inválida para {id_ave}.")
        return cls(aves, fichas, evidencias, fuentes, vocab, hashlib.sha256(ruta_fichas.read_bytes() + complementos).hexdigest())

    def citas(self, id_ave, campos):
        """Devuelve las citas de los campos mostrados y agrupa páginas repetidas."""
        resultado = {}
        for campo in campos:
            for ref in self.evidencias[id_ave]["campos"].get(campo, []):
                localizador = ref["localizador"]
                if ref["fuente_id"] == "GUIA_ENVIGADO":
                    localizador = localizador.split(",", 1)[0]
                clave = (ref["fuente_id"], ref["url"], localizador)
                cita = resultado.setdefault(clave, {
                    "titulo": self.fuentes[ref["fuente_id"]]["titulo"],
                    "url": ref["url"], "localizador": localizador, "campos": [],
                })
                if campo not in cita["campos"]:
                    cita["campos"].append(campo)
        return list(resultado.values())
