# Lee las regiones de la guía que sirven para transcribir las fichas.
"""Reconstruye la transcripción factual desde las fichas gráficas de Envigado."""

import argparse
import csv
import json
import re
from pathlib import Path

from fuentes import DATA, RAW, indice_guia, preparar_ocr

TAMANOS_VERIFICADOS = {75: "7,3", 77: "8,7", 182: "9,5", 201: "17", 236: "11", 303: "11", 304: "10"}
ALTITUDES_VERIFICADAS = {117: "900 a 2500"}
DIETAS_VERIFICADAS = {298: "Frugívora Nectarívora"}
DISTRIBUCIONES_VERIFICADAS = {322: "Residente"}
COLUMNAS = (
    "pagina", "nombre_cientifico", "tamano_cm", "altitud_min_m", "altitud_max_m",
    "habitat_guia", "gremio_guia", "distribucion_guia", "habito_guia",
)


def paginas_seleccionadas():
    # Devuelve las páginas necesarias para la transcripción.
    with (DATA / "plumaje_envigado.csv").open(encoding="utf-8") as archivo:
        return sorted(int(fila["pagina"]) for fila in csv.DictReader(archivo))


def transcribir():
    # Extrae los campos de la guía para producir el CSV intermedio.
    indice = {(p, n) for n, (p, _, _) in indice_guia().items()}
    for pagina in paginas_seleccionadas():
        ruta = RAW / "ocr_envigado" / f"{pagina:03}.json"
        palabras = json.loads(ruta.read_text(encoding="utf-8"))

        def zona(x_min, x_max, y_min, y_max):
            # Acota la región de la página que se lee para un campo.
            region = (w for w in palabras if x_min <= w["x"] < x_max and y_min <= w["y"] < y_max)
            return " ".join(w["texto"] for w in region)

        encabezado = zona(100, 1140, 320, 380).lower().replace(" ", "")
        nombres = [n for p, n in indice if p == pagina and n.lower().replace(" ", "") in encabezado]
        if len(nombres) != 1:
            raise ValueError(f"Página {pagina}: la ficha y el índice no coinciden.")
        tamanos = TAMANOS_VERIFICADOS.get(pagina, zona(130, 280, 475, 590))
        # Valida tamaños transcritos, por ejemplo «21 23» o «12,5».
        if not re.fullmatch(r"\d+(?:[,.]\d+)?(?: \d+(?:[,.]\d+)?)?", tamanos):
            raise ValueError(f"Página {pagina}: revisar tamaño {tamanos!r}.")
        altitud = ALTITUDES_VERIFICADAS.get(pagina, zona(775, 1150, 565, 640)).replace("o", "0")
        minimo, maximo = altitud.split(" a ")
        yield {
            "pagina": pagina,
            "nombre_cientifico": nombres[0],
            "tamano_cm": tamanos.replace(".", ","),
            "altitud_min_m": int(minimo),
            "altitud_max_m": int(maximo),
            "habitat_guia": zona(1225, 1680, 738, 870),
            "gremio_guia": DIETAS_VERIFICADAS.get(pagina, zona(305, 615, 950, 1065)),
            "distribucion_guia": DISTRIBUCIONES_VERIFICADAS.get(pagina, zona(1225, 1680, 515, 615)),
            "habito_guia": zona(1225, 1680, 940, 1030),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparar-ocr", action="store_true")
    parser.add_argument("--salida", type=Path, default=DATA / "guia_envigado.csv")
    argumentos = parser.parse_args()
    if argumentos.preparar_ocr:
        preparar_ocr(paginas_seleccionadas())
    else:
        filas = list(transcribir())
        with argumentos.salida.open("w", encoding="utf-8", newline="") as salida:
            escritor = csv.DictWriter(salida, fieldnames=COLUMNAS)
            escritor.writeheader()
            escritor.writerows(filas)
