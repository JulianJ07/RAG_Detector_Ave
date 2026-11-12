"""Descarga y lectura de los insumos fijados para el Valle de Aburrá."""

import csv
import hashlib
import io
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import fitz
from openpyxl import load_workbook

DATA = Path(__file__).resolve().parents[1] / "data"
RAW = DATA / "raw"
MUNICIPIOS = {
    "Barbosa", "Bello", "Caldas", "Copacabana", "Envigado", "Girardota",
    "Itagüí", "La Estrella", "Medellín", "Sabaneta",
}
FUENTES = {
    "AMVA_URBANA": (
        "Registros de aves del Valle de Aburrá asociados al estudio de conectividad ecológica",
        "Universidad Nacional de Colombia y Área Metropolitana del Valle de Aburrá",
        2022, "https://doi.org/10.15472/5rp8fn", "CC BY 4.0", "urbana.zip",
        "https://ipt.biodiversidad.co/sib/archive.do?r=amva_conectividad-aburra_ii&v=1.0",
    ),
    "MEDELLIN_SAN_MIGUEL": (
        "Biodiversidad de aves en el Distrito Especial de Medellín y Alto de San Miguel, v2.1",
        "Secretaría de Medio Ambiente del Distrito de Medellín",
        2026, "https://doi.org/10.15472/7raaek", "CC BY-NC 4.0", "san_miguel.zip",
        "https://ipt.biodiversidad.co/sib/archive.do?r=inventario_biodiversidad_aves_medellin_altodesanmiguel&v=2.1",
    ),
    "HUMEDALES_AMVA": (
        "Caracterización biótica de 8 humedales priorizados en el Valle de Aburrá, v1.2",
        "Instituto Humboldt y Área Metropolitana del Valle de Aburrá", 2024,
        "https://i2d.humboldt.org.co/resource?r=rrbb_animaliaplantae_amva_2022&v=1.2",
        "CC BY-NC 4.0", "humedales.zip",
        "https://i2d.humboldt.org.co/ceiba/archive.do?r=rrbb_animaliaplantae_amva_2022&v=1.2",
    ),
    "GUIA_ENVIGADO": (
        "Guía de las aves de Envigado, primera edición",
        "Sociedad Antioqueña de Ornitología, Carlos Iván Restrepo Jaramillo y Ramón David Ruiz Correa",
        2023, "https://sao.org.co/guia-de-las-aves-del-municipio-de-envigado/",
        "Derechos reservados. Consulta y cita de hechos por página. PDF y fotografías excluidos de Git.",
        "envigado.pdf", "https://sao.org.co/wp-content/uploads/2023/12/Guia-de-las-aves-de-Envigado-02-Nov-23.pdf",
    ),
    "AVES_URBANIZACION": (
        "Categorizing urban avoiders, utilizers, and dwellers for identifying bird conservation priorities in a Northern Andean city",
        "Garizábal-Carmona, Betancur, Montoya-Arango, Franco-Espinosa y Mancera-Rodríguez",
        2024, "https://doi.org/10.3389/fevo.2024.1432340", "CC BY", "urbanizacion.html",
        "https://www.frontiersin.org/journals/ecology-and-evolution/articles/10.3389/fevo.2024.1432340/full",
    ),
    "LISTA_ACO": (
        "Lista de referencia de especies de aves de Colombia - 2022, v1.5",
        "Asociación Colombiana de Ornitología y Comité Colombiano de Registros Ornitológicos",
        2023, "https://doi.org/10.15472/qhsz0p", "CC BY 4.0", "aco.zip",
        "https://ipt.biodiversidad.co/sib/archive.do?r=aco_listaavescolombia2017&v=1.5",
    ),
    "BIRDBASE": (
        "BIRDBASE v2025.1: A Global Database of Avian Biogeography, Conservation, Ecology and Life History Traits",
        "Şekercioğlu y colaboradores", 2025, "https://doi.org/10.6084/m9.figshare.27051040",
        "CC BY 4.0 (archivo de datos)", "birdbase.xlsx",
        "https://ndownloader.figshare.com/files/55634729",
    ),
}


def descargar():
    """Obtiene archivos de distribución oficiales sin rastrear fichas web."""
    RAW.mkdir(parents=True, exist_ok=True)
    for _, _, _, _, _, nombre, url in FUENTES.values():
        destino = RAW / nombre
        if destino.exists():
            continue
        solicitud = Request(url, headers={"User-Agent": "Proyecto universitario de aves del Valle de Aburra"})
        with urlopen(solicitud, timeout=120) as respuesta:
            datos = respuesta.read()
        temporal = destino.with_suffix(".part")
        temporal.write_bytes(datos)
        temporal.replace(destino)
    libro = RAW / "birdbase.xlsx"
    if hashlib.md5(libro.read_bytes()).hexdigest() != "36d53d59af1e449db1fc4c30062d9d1f":
        raise ValueError("El archivo de BIRDBASE difiere de la versión fijada.")


def normalizar_texto(texto):
    return " ".join(unicodedata.normalize("NFKC", texto or "").split())


def dwca(archivo, tabla):
    with ZipFile(RAW / archivo) as zip_file:
        with zip_file.open(tabla + ".txt") as entrada:
            yield from csv.DictReader(io.TextIOWrapper(entrada, encoding="utf-8-sig"), delimiter="\t")


def observaciones():
    resultado = defaultdict(list)
    for fuente in ("AMVA_URBANA", "MEDELLIN_SAN_MIGUEL", "HUMEDALES_AMVA"):
        for fila in dwca(FUENTES[fuente][5], "occurrence"):
            if (
                fila["class"] != "Aves" or fila["taxonRank"] != "Especie"
                or fila.get("identificationQualifier", "").strip()
                or fila.get("occurrenceStatus", "").lower() not in ("", "present")
                or fila.get("stateProvince") != "Antioquia"
                or fila["county"] not in MUNICIPIOS or not fila["occurrenceID"]
            ):
                continue
            nombre = normalizar_texto(fila["scientificName"])
            if re.fullmatch(r"[A-Z][a-z]+ [a-z]+", nombre):
                resultado[nombre].append((fuente, fila))
    return resultado


def indice_guia():
    resultado = {}
    with fitz.open(RAW / "envigado.pdf") as guia:
        for pagina in guia[354:361]:
            texto = unicodedata.normalize("NFKC", pagina.get_text(sort=True))
            # El rótulo lateral puede unir dos filas contiguas al extraer el PDF.
            texto = re.sub(r"(\d{2,3})\s*PASSERIFORMES\s+(?=[A-Z]\w+\s+[A-Z][a-z]+ )", r"\1\n", texto)
            for linea in texto.splitlines():
                campos = re.fullmatch(r"\s*(?:NO\s+)?([A-Z]\w+)\s+([A-Z][a-z]+ [a-z]+)\s+(.+?)\s+(\d{2,3})\s*", linea)
                if campos:
                    orden, especie, comun, numero = campos.groups()
                    resultado[especie] = (int(numero), orden, comun)
    # El índice impreso apunta a la ficha vecina en estos cuatro casos.
    for especie, numero in {
        "Colaptes rubiginosus": 128, "Falco sparverius": 133,
        "Pygochelidon cyanoleuca": 227, "Coereba flaveola": 313,
    }.items():
        _, orden, comun = resultado[especie]
        resultado[especie] = (numero, orden, comun)
    return resultado


def preparar_ocr(numeros):
    carpeta = RAW / "ocr_envigado"
    carpeta.mkdir(exist_ok=True)
    with fitz.open(RAW / "envigado.pdf") as guia:
        for numero in numeros:
            pagina = guia[numero + 1]
            recorte = fitz.Rect(0, 500, pagina.rect.width, 878)
            pagina.get_pixmap(matrix=fitz.Matrix(3, 3), clip=recorte).save(carpeta / f"{numero:03}.png")


def birdbase():
    """Solo acepta correspondencias exactas y unívocas entre nomenclaturas."""
    filas_por_nombre = defaultdict(dict)
    libro = load_workbook(RAW / "birdbase.xlsx", read_only=True, data_only=True)
    try:
        filas = libro["Data"].values
        next(filas)
        columnas = next(filas)
        for numero, valores in enumerate(filas, start=3):
            fila = dict(zip(columnas, valores))
            for valor in set(valores[2:7]):
                if isinstance(valor, str) and re.fullmatch(r"[A-Z][a-z]+ [a-z]+", valor):
                    filas_por_nombre[valor][numero] = fila
    finally:
        libro.close()
    return {nombre: next(iter(filas.items())) for nombre, filas in filas_por_nombre.items() if len(filas) == 1}
