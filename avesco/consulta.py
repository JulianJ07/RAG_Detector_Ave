"""Normalización de atributos y filtro numérico en centímetros."""

import re
import unicodedata
from dataclasses import dataclass, field

ALIAS = {
    "colores_principales": {
        "negro": "negr[oa]s?|oscuro|oscuras|negruzc[oa]", "blanco": "blanc[oa]s?|blanquecin[oa]",
        "gris": "gris(?:es|ace[oa])?", "marrón": "marron(?:es)?|pard[oa]s?|castan[oa]s?|cafes?",
        "rojo": "roj[oa]s?|rojiz[oa]s?|escarlata", "naranja": "naranjas?|anaranjad[oa]s?|canela",
        "amarillo": "amarill[oa]s?|amarillent[oa]s?|dorad[oa]s?",
        "verde": "verdes?|olivace[oa]s?|oliva|olivaceo",
        "azul": "azul(?:es|ad[oa]s?)?|turquesa", "violeta": "violetas?|morad[oa]s?|violace[oa]s?",
        "iridiscente": "iridiscentes?|reflejos",
    },
    "dieta": {
        "semillas": "semillas?|granos?|granivor[oa]", "insectos": "insectos?|moscas?|bichos?|insectivor[oa]",
        "frutas": "frut[oa]s?|bayas?|frugivor[oa]", "néctar": "nectar|nectarivor[oa]",
        "peces": "peces|pescados?|piscivor[oa]", "carroña": "carrona|carroner[oa]s?",
        "pequeños vertebrados": "pequenos vertebrados|ratones|lagartijas",
        "carnívoro": "carnivor[oa]", "omnívoro": "omnivor[oa]",
    },
    "entorno": {
        "parque_jardin": "parques?|jardin(?:es)?", "urbano": "urban[oa]s?|ciudad|barrios?|edificios?",
        "bosque": "bosques?", "bosque_andino": "bosques? andinos?",
        "bosque_humedo": "bosques? humedos?", "herbazal": "herbazal(?:es)?|pastizal(?:es)?",
        "matorral": "matorral(?:es)?", "humedal": "humedal(?:es)?|pantanos?|cienagas?",
        "acuatico": "acuatic[oa]s?|lagunas?|lagos?", "rio_o_quebrada": "rios?|quebradas?",
        "zona_agropecuaria": "fincas?|cultivos?|zona agropecuaria", "paramo": "paramos?",
    },
    "vuelo": {
        "aleteo_rapido_con_cernido": "cernido|suspendid[oa]|quiet[oa] en el aire",
        "aleteo_rapido_continuo": "aleteo rapido|aleteaba rapido",
        "aleteo_lento": "aleteo lento", "vuelo_ondulado": "vuelo ondulado|volaba en ondas",
        "planeo": "planeaba|planeo|planeando", "vuelo_recto": "vuelo recto|volaba recto",
        "otro": "volaba|vuelo|aleteaba",
    },
}
CAMPOS = tuple(ALIAS)
NUMERO = r"\d{1,4}(?:[.,]\d+)?"
UNIDAD = r"centimetros?|milimetros?|metros?|cm|mm|m"
MEDIDA = re.compile(
    rf"\b(?P<primera>{NUMERO})\s*(?:(?P<u1>{UNIDAD})\b\s*)?"
    rf"(?:(?:a|y|[-–—])\s*(?P<segunda>{NUMERO})\s*)?(?P<u2>{UNIDAD})\b"
)


def normalizar(texto):
    """Ignora tildes al comparar y conserva el texto original para las citas."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))


def tokens(texto):
    return set(re.findall(r"[a-z]{3,}", normalizar(texto)))


def a_centimetros(numero, unidad):
    valor = float(numero.replace(",", "."))
    if unidad == "m" or unidad.startswith("metro"):
        return valor * 100
    if unidad == "mm" or unidad.startswith("milimetro"):
        return valor / 10
    return valor


def extraer_tamano(texto, tolerancia):
    """Un rango escrito se respeta. Una medida puntual se trata como estimación."""
    texto = normalizar(texto)
    medidas = []
    for m in MEDIDA.finditer(texto):
        antes = texto[:m.start()]
        despues = texto[m.end():]
        if re.search(r"(?:hasta|menos de|mas de|altitud de|envergadura de|distancia de|no media)\s*$", antes):
            continue
        # La envergadura puede incluir «de alas de», «aproximada» o dos unidades.
        # Se descarta esa medida, sin perder la longitud corporal de otra cláusula.
        contexto = re.split(r"[,;\n!?]|\.(?!\d)", antes)[-1]
        dimensiones = list(re.finditer(
            r"\b(?:envergadura|altitud|distancia|longitud|largo|mide|media)\b", contexto,
        ))
        es_longitud = re.match(r"\s+(?:de\s+)?(?:longitud|largo)\b", despues)
        if (dimensiones and dimensiones[-1][0] in {"envergadura", "altitud", "distancia"}
                and not es_longitud):
            continue
        if re.match(r"\s+(?:de (?:altura|envergadura|distancia)|sobre el nivel del mar|msnm)\b", despues):
            continue
        if re.match(r"\s+(?:de\s+)?(?:envergadura|distancia)\b", despues):
            continue
        medidas.append(m)
    if len(medidas) != 1:
        return None
    m = medidas[0]
    a = a_centimetros(m["primera"], m["u1"] or m["u2"])
    if m["segunda"] is not None:
        b = a_centimetros(m["segunda"], m["u2"])
        return (a, b) if 0 < a <= b else None
    return (round(a * (1 - tolerancia), 6), round(a * (1 + tolerancia), 6)) if a > 0 else None


@dataclass
class AtributosConsulta:
    rango_tamano_cm: tuple[float, float] | None = None
    colores_principales: list[str] = field(default_factory=list)
    dieta: list[str] = field(default_factory=list)
    entorno: list[str] = field(default_factory=list)
    vuelo: list[str] = field(default_factory=list)


def extraer_atributos(texto, tolerancia, vocabularios, extraidos=None):
    """Verifica medidas en la entrada original y limita atributos al vocabulario."""
    sin_tildes = normalizar(texto)
    valores = {}
    for campo, patrones in ALIAS.items():
        datos_llm = (extraidos or {}).get(campo)
        if isinstance(datos_llm, list):
            permitidos = {normalizar(v): v for v in vocabularios[campo]}
            valores[campo] = list(dict.fromkeys(
                permitidos[normalizar(v)] for v in datos_llm if isinstance(v, str) and normalizar(v) in permitidos
            ))
            continue
        valores[campo] = [
            etiqueta for etiqueta, patron in patrones.items()
            if any(
                not re.search(r"\b(?:no(?: era| es| tenia| vi| parecia)?|sin)(?: manchas| plumas| color)?\s*$",
                              sin_tildes[:m.start()])
                for m in re.finditer(rf"\b(?:{patron})\b", sin_tildes)
            )
        ]
    if len(valores["vuelo"]) > 1 and "otro" in valores["vuelo"]:
        valores["vuelo"].remove("otro")
    return AtributosConsulta(extraer_tamano(texto, tolerancia), **valores)


def filtrar_por_tamano(aves, rango_tamano_cm):
    """Conserva intervalos que se tocan o se solapan, incluidos sus extremos."""
    if rango_tamano_cm is None:
        return list(aves)
    minimo, maximo = rango_tamano_cm
    return [
        id_ave for id_ave, ave in aves.items()
        if ave["longitud_min_cm"] <= maximo and ave["longitud_max_cm"] >= minimo
    ]


def extraer_taxonomia(texto, aves=None):
    """Reconoce taxones afirmados, incluso cuando no hay fichas de ese grupo."""
    texto = normalizar(texto)
    alias = {
        "familia": {"Tyrannidae": r"tiranidos?", "Trochilidae": r"colibri(?:es|s)?"},
        "orden": {"Passeriformes": r"paseriformes?"},
    }
    criterios = {}
    for campo in ("familia", "orden"):
        mencionados = []
        taxones = {normalizar(ave[campo]): ave[campo] for ave in (aves or {}).values()}
        # Las familias y órdenes fuera del catálogo también son restricciones.
        # Ignorarlos permitiría responder con especies de otro grupo taxonómico.
        sufijo = "idae" if campo == "familia" else "formes"
        for m in re.finditer(rf"\b[a-z]{{3,}}{sufijo}\b", texto):
            literal = m[0]
            canonico = next((taxon for taxon, patron in alias[campo].items()
                             if re.fullmatch(patron, literal)), literal.capitalize())
            taxones.setdefault(normalizar(canonico), canonico)
        for taxon in sorted(taxones.values()):
            patron = re.escape(normalizar(taxon))
            if taxon in alias[campo]:
                patron += "|" + alias[campo][taxon]
            for m in re.finditer(rf"\b(?:{patron})\b", texto):
                if re.search(
                    r"\bno(?:\s+(?:es|son|era|eran|parecia|vi|pertenece|pertenecen|a|la|el|familia|de|los|las|un|una))*\s*$",
                    texto[:m.start()],
                ):
                    continue
                mencionados.append(taxon)
                break
        if mencionados:
            criterios[campo] = mencionados
    return criterios


def filtrar_por_taxonomia(aves, texto, ids):
    """Filtra solo familias y órdenes mencionados explícitamente en la descripción."""
    criterios = extraer_taxonomia(texto, aves)
    return ([id_ave for id_ave in ids
             if all(aves[id_ave][campo] in valores for campo, valores in criterios.items())], criterios)
