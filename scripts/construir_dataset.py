"""Construye y valida el dataset RAG a partir de los insumos documentados."""

import argparse
import csv
import hashlib
import html
import json
import random
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from fuentes import DATA, FUENTES, MUNICIPIOS, RAW, birdbase, descargar, dwca, indice_guia
from fuentes import normalizar_texto, observaciones

CONSULTA = "2026-11-11"
CAMPOS = """
id nombre_comun nombre_cientifico orden familia longitud_min_cm longitud_max_cm
colores_principales descripcion_plumaje dieta dieta_detalle vuelo comportamiento_otro
entorno altitud_min_m altitud_max_m departamentos_o_zonas endemica_colombia estado_uicn
vocalizacion especies_similares fuente_id fuente_pagina_o_url evidencia_corta confianza campos_inferidos
""".split()
GUIA = "GUIA_ENVIGADO"
ACO = "LISTA_ACO"
BB = "BIRDBASE"
URB = "AVES_URBANIZACION"
HUM = "HUMEDALES_AMVA"
DIETA = {
    "Granívora": "semillas", "Insectívora": "insectos", "Frugívora": "frutas",
    "Nectarívora": "néctar", "Piscívora": "peces", "Carnívora": "carnívoro",
    "Omnívora": "omnívoro",
}
HABITAT = {
    "Bosque": "bosque", "Matorral": "matorral", "Herbazal": "herbazal",
    "Urbano": "urbano", "Acuático": "acuatico", "Acuática": "acuatico",
}
ENTORNOS = {
    "bosque": "bosques", "matorral": "matorrales", "herbazal": "herbazales",
    "urbano": "zonas urbanas", "acuatico": "ambientes acuáticos",
    "humedal": "humedales", "parque_jardin": "parques o jardines",
    "bosque_humedo": "bosques húmedos",
}
HABITOS = {
    "Diurno": "Tiene actividad diurna",
    "Nocturno": "Tiene actividad nocturna",
    "Crepuscular y Diurno": "Tiene actividad crepuscular y diurna",
    "Nocturno y Diurno": "Tiene actividad nocturna y diurna",
}
CLASE_URBANA = {
    "Avoider": "Un estudio del área la clasificó entre las aves que evitan la urbanización",
    "Utilizer": "Un estudio del área la clasificó entre las aves que utilizan ambientes urbanos",
    "Dweller": "Un estudio del área la clasificó entre las aves que habitan ambientes urbanos",
}
PARES = (
    (41, 42), (43, 44), (60, 61), (68, 69), (75, 77), (86, 88), (87, 88),
    (91, 92), (99, 102), (107, 110), (113, 114), (121, 122), (128, 129),
    (139, 140), (167, 168), (186, 188), (195, 197), (195, 201), (242, 243),
    (250, 251), (264, 265), (283, 284), (300, 301), (303, 304), (305, 308),
    (322, 326), (331, 332),
)
FUERA = (
    "Calypte anna", "Cyanistes caeruleus", "Parus major", "Turdus merula",
    "Aptenodytes forsteri", "Dromaius novaehollandiae", "Struthio camelus",
    "Apteryx mantelli", "Cacatua galerita", "Haliaeetus leucocephalus",
)
REGIONES = {
    "A": "Australasia", "F": "Afrotropical", "N": "Neártica",
    "P": "Paleártica", "S": "Polar austral", "Z": "Nueva Zelanda e islas",
}


def leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def evidencia(fuente, ubicacion, extracto):
    url = FUENTES[fuente][3]
    if fuente == GUIA and (pagina := re.match(r"p\. (\d+),", ubicacion)):
        url = FUENTES[GUIA][6] + f"#page={int(pagina[1]) + 2}"
    return {
        "fuente_id": fuente, "url": url,
        "localizador": ubicacion, "evidencia": extracto,
    }


def evidencia_registro(fuente, fila, extracto):
    return evidencia(fuente, f"occurrence.txt · occurrenceID {fila['occurrenceID']}", extracto)


def leer_estudio_urbano():
    html_articulo = (RAW / "urbanizacion.html").read_text(encoding="utf-8")
    tablas = re.findall(r"<table\b.*?</table>", html_articulo, flags=re.S)
    tabla = next(tabla for tabla in tablas if all(f">{x}<" in tabla for x in CLASE_URBANA))
    resultado = {}
    for fila in re.findall(r"<tr\b.*?</tr>", tabla, flags=re.S):
        celdas = re.findall(r"<td\b[^>]*>(.*?)</td>", fila, flags=re.S)
        textos = [normalizar_texto(html.unescape(re.sub(r"<[^>]*>", "", x))) for x in celdas]
        for categoria, nombre in zip(CLASE_URBANA, textos[1::2]):
            nombre = nombre.strip(" *")
            if re.fullmatch(r"[A-Z][a-z]+ [a-z]+", nombre):
                resultado[nombre] = categoria
    if len(resultado) < 50:
        raise ValueError("La tabla 2 del estudio urbano no se pudo leer completa.")
    return resultado


def lista_natural(elementos):
    if len(elementos) < 2:
        return "".join(elementos)
    ultimo = elementos[-1]
    conjuncion = " e " if re.match(r"^(?:i|hi(?!e))", ultimo, flags=re.I) else " y "
    return ", ".join(elementos[:-1]) + conjuncion + ultimo


def registrar_zonas(registros):
    por_municipio = {}
    for fuente, fila in registros:
        municipio = fila["county"]
        por_municipio.setdefault(municipio, evidencia_registro(fuente, fila, municipio + ", Antioquia"))
    return sorted(por_municipio), [por_municipio[m] for m in sorted(por_municipio)]


def entorno_local(registros, ambientes_guia):
    """Conserva observaciones con un hábitat explícito o un parque inequívoco."""
    ambientes = {}
    for fuente, fila in registros:
        habitat = fila["habitat"]
        localidad = fila["locality"]
        if fuente == HUM and habitat == "Humedal" and "acuatico" in ambientes_guia:
            ambientes.setdefault("humedal", evidencia_registro(fuente, fila, habitat))
        if "bosque" in ambientes_guia and re.search(r"\bbosque (?:muy )?húmedo\b", habitat, flags=re.I):
            ambientes.setdefault("bosque_humedo", evidencia_registro(fuente, fila, habitat))
        if re.search(r"jardín botánico|parque de laureles|parque fátima|parque de malib[uú]", localidad, flags=re.I):
            ambientes.setdefault("parque_jardin", evidencia_registro(fuente, fila, localidad))
    return ambientes


def limites_altitud(guia, nombre, rasgos, fila_bb):
    pagina = guia["pagina"]
    if nombre == "Quiscalus mexicanus":
        return rasgos["NormMin"], rasgos["NormMax"], evidencia(
            BB, f"Data, fila {fila_bb}, NormMin y NormMax",
            f"{rasgos['NormMin']} a {rasgos['NormMax']} m",
        )
    bajo, alto = int(guia["altitud_min_m"]), int(guia["altitud_max_m"])
    return bajo, alto, evidencia(GUIA, f"p. {pagina}, rango altitudinal", f"{bajo} a {alto} m")


def construir():
    taxones = {r["scientificName"]: r for r in dwca("aco.zip", "taxon")}
    rasgos = birdbase()
    presencia = observaciones()
    indice = indice_guia()
    urbano = leer_estudio_urbano()
    filas_plumaje = leer_csv(DATA / "plumaje_envigado.csv")
    filas_guia = leer_csv(DATA / "guia_envigado.csv")
    plumajes = {int(r["pagina"]): r for r in filas_plumaje}
    guias = {int(r["pagina"]): r for r in filas_guia}
    if len(plumajes) != len(filas_plumaje) or len(guias) != len(filas_guia) or set(plumajes) != set(guias):
        raise ValueError("Las transcripciones contienen páginas repetidas o no coincidentes.")
    if len({rasgos[g["nombre_cientifico"]][0] for g in guias.values()}) != len(guias):
        raise ValueError("Hay taxones de BIRDBASE repetidos en la selección.")
    ids = {p: g["nombre_cientifico"].lower().replace(" ", "_") for p, g in guias.items()}
    pares = defaultdict(list)
    for a, b in PARES:
        pares[a].append(b)
        pares[b].append(a)
    aves, trazas = [], {}
    for pagina, guia in sorted(guias.items()):
        nombre = guia["nombre_cientifico"]
        numero, _, comun = indice[nombre]
        if numero != pagina or nombre not in presencia:
            raise ValueError(f"Falta verificación del índice o de presencia local para {nombre}.")
        ave = dict.fromkeys(CAMPOS)
        traza = {}
        inferidos = set()

        def poner(campo, valor, referencias, inferido=False):
            ave[campo] = valor
            traza[campo] = referencias if isinstance(referencias, list) else [referencias]
            if inferido:
                inferidos.add(campo)

        def ficha(dato, extracto):
            return evidencia(GUIA, f"p. {pagina}, {dato}", extracto)

        taxon = taxones[nombre]
        poner("id", ids[pagina], ficha("nombre científico", nombre), True)
        poner("nombre_cientifico", nombre, ficha("nombre científico", nombre))
        poner("nombre_comun", comun, ficha("nombre común e índice", comun))
        for campo in ("orden", "familia"):
            original = taxon["order" if campo == "orden" else "family"]
            poner(campo, original, evidencia(ACO, f"taxon.txt · {taxon['id']}", original))

        tamano = guia["tamano_cm"]
        medidas = [float(n.replace(",", ".")) for n in tamano.split()]
        for campo, valor in (("longitud_min_cm", min(medidas)), ("longitud_max_cm", max(medidas))):
            poner(campo, valor, ficha("tamaño", f"{tamano.replace(' ', ' y ')} cm"), True)

        plumaje = plumajes[pagina]
        poner("colores_principales", plumaje["colores"].split("|"), ficha("fotografías", plumaje["colores"].replace("|", ", ")), True)
        poner("descripcion_plumaje", plumaje["descripcion"], ficha("fotografías", "Descripción visual del plumaje del ejemplar fotografiado"), True)

        gremio = guia["gremio_guia"]
        dietas = [DIETA[x] for x in gremio.split()]
        poner("dieta", dietas, ficha("gremio trófico", gremio), True)
        poner("dieta_detalle", lista_natural([x.lower() for x in gremio.split()]), ficha("gremio trófico", gremio), True)

        habito = guia["habito_guia"]
        detalle = HABITOS[habito]
        ref_habito = [ficha("hábito", habito)]
        if categoria := urbano.get(nombre):
            detalle += ". " + CLASE_URBANA[categoria]
            ref_habito.append(evidencia(URB, "Tabla 2", f"{nombre} · {categoria}"))
        poner("comportamiento_otro", detalle, ref_habito, True)

        registros = presencia[nombre]
        zonas, ref_zonas = registrar_zonas(registros)
        poner("departamentos_o_zonas", zonas, ref_zonas, True)
        habitat_guia = guia["habitat_guia"]
        ambientes = [HABITAT[x] for x in habitat_guia.split()]
        locales = entorno_local(registros, ambientes)
        poner("entorno", ambientes + list(locales), [ficha("hábitat", habitat_guia), *locales.values()], True)

        fila_bb, datos_bb = rasgos[nombre]
        bajo, alto, ref_alt = limites_altitud(guia, nombre, datos_bb, fila_bb)
        poner("altitud_min_m", bajo, ref_alt)
        poner("altitud_max_m", alto, ref_alt)
        distribucion = guia["distribucion_guia"]
        if distribucion == "Endémica":
            poner("endemica_colombia", True, ficha("distribución", distribucion))
        elif distribucion in {"Casi Endémica", "Casi Endémico", "Introducida", "Migratoria Boreal"}:
            poner("endemica_colombia", False, ficha("distribución", distribucion), True)
        estado = datos_bb["2024 IUCN Red List category"]
        if estado:
            poner("estado_uicn", estado, evidencia(BB, f"Data, fila {fila_bb}, 2024 IUCN Red List category", estado))

        if pagina in pares:
            referencias = [ficha("fotografías", "Comparación de rasgos visibles")]
            referencias.extend(evidencia(GUIA, f"p. {p}, fotografías", guias[p]["nombre_cientifico"]) for p in pares[pagina])
            poner("especies_similares", [ids[p] for p in pares[pagina]], referencias, True)

        principal = ficha("tamaño", f"Tamaño consignado: {tamano.replace(' ', ' y ')} cm")
        poner("fuente_id", GUIA, principal)
        poner("fuente_pagina_o_url", principal["url"], principal)
        poner("evidencia_corta", principal["evidencia"], principal)
        # La evaluación de confianza considera la descripción visual y el OCR.
        ave["confianza"] = "media"
        ave["campos_inferidos"] = [campo for campo in CAMPOS if campo in inferidos]
        aves.append(ave)
        trazas[ave["id"]] = traza
    return aves, trazas, presencia, rasgos, taxones


def ficha_rag(ave):
    minimo, maximo = ave["longitud_min_cm"], ave["longitud_max_cm"]
    inferior, superior = (f"{n:g}".replace(".", ",") for n in (minimo, maximo))
    longitud = f"{inferior} centímetros" if minimo == maximo else f"entre {inferior} y {superior} centímetros"
    colores = lista_natural(ave["colores_principales"])
    dieta = ave["dieta"]
    if len(dieta) == 1 and dieta[0] in {"omnívoro", "carnívoro"}:
        alimentacion = f"Su dieta se describe como {ave['dieta_detalle']}."
    else:
        alimentos = {"omnívoro": "alimentos de origen vegetal y animal", "carnívoro": "alimentos de origen animal"}
        alimentacion = "En su dieta se registran " + lista_natural([alimentos.get(d, d) for d in dieta]) + "."
    sitios = lista_natural([ENTORNOS[x] for x in ave["entorno"]])
    zonas = lista_natural(ave["departamentos_o_zonas"])
    partes = [
        f"{ave['nombre_comun']} ({ave['nombre_cientifico']}) pertenece al orden {ave['orden']} y a la familia {ave['familia']}.",
        f"Su tamaño registrado es de {longitud}. Los colores observados en el plumaje son {colores}.",
        f"{ave['descripcion_plumaje']}. {alimentacion} Se encuentra en {sitios}.",
        f"El rango altitudinal consignado para la especie va de {ave['altitud_min_m']} a {ave['altitud_max_m']} metros sobre el nivel del mar.",
        f"En el Valle de Aburrá se registró en {zonas}. {ave['comportamiento_otro']}.",
    ]
    if ave["vuelo"]:
        partes.append("El tipo de vuelo registrado es " + lista_natural([x.replace("_", " ") for x in ave["vuelo"]]) + ".")
    if ave["endemica_colombia"]:
        partes.append("Es una especie endémica de Colombia.")
    texto = " ".join(partes)
    return {"id": ave["id"], "nombre_cientifico": ave["nombre_cientifico"], "texto": texto}


def validar(aves, fichas, trazas, presencia):
    vocab = json.loads((DATA / "vocabularios.json").read_text(encoding="utf-8"))
    errores = []
    ids = {ave["id"] for ave in aves}
    cientificos = {ave["nombre_cientifico"] for ave in aves}
    if not 100 <= len(aves) <= 150 or len(ids) != len(aves) or len(cientificos) != len(aves):
        errores.append("Cantidad fuera de rango o especies duplicadas.")
    if [a["id"] for a in aves] != [f["id"] for f in fichas]:
        errores.append("Los IDs y el orden de las fichas deben coincidir con los registros.")
    palabras = [len(re.findall(r"\b[\w]+(?:[,.][\d]+)?\b", f["texto"])) for f in fichas]
    for ave, longitud in zip(aves, palabras, strict=True):
        identificador = ave["id"]
        traza = trazas[identificador]
        for campo, valor in ave.items():
            if valor is not None and campo not in {"campos_inferidos", "confianza"} and not traza.get(campo):
                errores.append(f"{identificador}: falta evidencia para {campo}.")
            if valor is not None and campo in vocab:
                valores = valor if isinstance(valor, list) else [valor]
                if len(valores) != len(set(valores)) or set(valores) - set(vocab[campo]):
                    errores.append(f"{identificador}: vocabulario inválido en {campo}.")
        for prefijo, unidad in (("longitud", "cm"), ("altitud", "m")):
            bajo, alto = (ave[f"{prefijo}_{x}_{unidad}"] for x in ("min", "max"))
            if bajo is not None and alto is not None and bajo > alto:
                errores.append(f"{identificador}: rango de {prefijo} invertido.")
        if not ave["fuente_id"] or not ave["fuente_pagina_o_url"] or not ave["evidencia_corta"]:
            errores.append(f"{identificador}: falta la referencia principal.")
        similares = set(ave["especies_similares"] or [])
        if similares - ids or identificador in similares:
            errores.append(f"{identificador}: enlace de similitud inválido.")
        if set(ave["departamentos_o_zonas"]) - MUNICIPIOS or ave["nombre_cientifico"] not in presencia:
            errores.append(f"{identificador}: falta un registro del Valle de Aburrá.")
        if not 80 <= longitud <= 150:
            errores.append(f"{identificador}: ficha de {longitud} palabras.")
        for referencia in [ref for referencias in traza.values() for ref in referencias]:
            if referencia["fuente_id"] not in FUENTES or len(referencia["evidencia"].split()) > 20:
                errores.append(f"{identificador}: referencia inválida o evidencia mayor de 20 palabras.")
    if errores:
        raise ValueError("\n".join(errores))
    return {
        "especies": len(aves), "duplicados": 0, "rangos_invertidos": 0,
        "especies_sin_fuente": 0, "especies_sin_presencia_local": 0,
        "palabras_fichas_min": min(palabras), "palabras_fichas_max": max(palabras),
        "nulos_por_campo": {
            campo: {"n": (n := sum(ave[campo] is None for ave in aves)), "porcentaje": round(n / len(aves) * 100, 2)}
            for campo in CAMPOS
        },
        "especies_por_orden": dict(sorted(Counter(ave["orden"] for ave in aves).items())),
        "especies_por_entorno": dict(sorted(Counter(h for ave in aves for h in ave["entorno"]).items())),
        "municipios_representados": sorted({m for ave in aves for m in ave["departamentos_o_zonas"]}),
        "pares_de_similitud": len(PARES),
    }


def casos_fuera(aves, presencia, rasgos, taxones):
    seleccion = {a["nombre_cientifico"] for a in aves}
    identificadores_locales = {rasgos[n][0] for n in set(presencia) | set(taxones) if n in rasgos}
    for nombre in FUERA:
        fila, rasgo = rasgos[nombre]
        if nombre in seleccion or fila in identificadores_locales:
            raise ValueError(f"Caso fuera del dataset inválido: {nombre}.")
        yield {
            "nombre_cientifico": nombre, "nombre_comun_en_fuente": rasgo["English Name (BirdLife > IOC > Clements>AviList)"],
            "region_documentada": REGIONES[rasgo["RLM"]], "fuente_id": BB,
            "fuente_url": FUENTES[BB][3], "localizador": f"Data, fila {fila}, RLM",
        }


def muestra_validacion(aves, trazas):
    llave = ["id", "campo", "valor", "fuente_id", "fuente_url", "localizador", "evidencia"]
    existente = DATA / "validacion_muestra.csv"
    anteriores = {tuple(f[c] for c in llave): f["correcto (sí/no)"] for f in leer_csv(existente)} if existente.exists() else {}
    muestra = random.Random(20261111).sample(aves, 15)
    campos = ("longitud_min_cm", "longitud_max_cm", "descripcion_plumaje", "dieta", "entorno", "estado_uicn")
    for i, ave in enumerate(muestra):
        campo = campos[i % len(campos)]
        if ave[campo] is None:
            campo = "longitud_min_cm"
        ref = trazas[ave["id"]][campo][0]
        valor = ave[campo]
        if campo == "entorno":
            valor = [v for v in valor if v in HABITAT.values()]
        fila = {
            "id": ave["id"], "nombre_cientifico": ave["nombre_cientifico"],
            "campo": campo, "valor": json.dumps(valor, ensure_ascii=False),
            "fuente_id": ref["fuente_id"], "fuente_url": ref["url"], "localizador": ref["localizador"],
            "evidencia": ref["evidencia"],
        }
        fila["correcto (sí/no)"] = anteriores.get(tuple(fila[c] for c in llave), "")
        yield fila


def escribir_csv(ruta, filas):
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, bool)) else v
                for k, v in fila.items()
            })


def escribir_jsonl(ruta, filas):
    with ruta.open("w", encoding="utf-8", newline="\n") as archivo:
        for fila in filas:
            archivo.write(json.dumps(fila, ensure_ascii=False, allow_nan=False) + "\n")


def publicar(aves, fichas, trazas, reporte, casos):
    fuentes = [
        dict(
            id=clave, titulo=titulo, autor_institucion=autor, anio=anio, url=url,
            licencia_o_condiciones=licencia, fecha_consulta=CONSULTA, descarga=descarga,
            archivo_raw=archivo, sha256=hashlib.sha256((RAW / archivo).read_bytes()).hexdigest(),
        )
        for clave, (titulo, autor, anio, url, licencia, archivo, descarga) in FUENTES.items()
    ]
    reporte["casos_fuera_del_dataset"] = len(casos)
    muestra = list(muestra_validacion(aves, trazas))
    reporte["especies_muestra_manual"] = len(muestra)
    with tempfile.TemporaryDirectory(dir=DATA) as temporal:
        carpeta = Path(temporal)
        procesados = carpeta / "processed"
        procesados.mkdir()
        escribir_csv(procesados / "aves.csv", aves)
        escribir_jsonl(procesados / "aves.jsonl", aves)
        escribir_jsonl(procesados / "fichas_rag.jsonl", fichas)
        escribir_jsonl(procesados / "evidencias.jsonl", ({"id": id_, "campos": refs} for id_, refs in trazas.items()))
        escribir_csv(carpeta / "fuentes.csv", fuentes)
        escribir_csv(carpeta / "validacion_muestra.csv", muestra)
        escribir_csv(carpeta / "especies_fuera_del_dataset.csv", casos)
        (carpeta / "reporte_validacion.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (DATA / "processed").mkdir(exist_ok=True)
        for archivo in sorted(carpeta.rglob("*")):
            if archivo.is_file():
                archivo.replace(DATA / archivo.relative_to(carpeta))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descargar", action="store_true", help="Descarga los archivos oficiales faltantes.")
    opciones = parser.parse_args()
    if opciones.descargar:
        descargar()
    aves, trazas, presencia, rasgos, taxones = construir()
    fichas = [ficha_rag(ave) for ave in aves]
    reporte = validar(aves, fichas, trazas, presencia)
    casos = list(casos_fuera(aves, presencia, rasgos, taxones))
    publicar(aves, fichas, trazas, reporte, casos)
    print(json.dumps(reporte, ensure_ascii=False, indent=2))
