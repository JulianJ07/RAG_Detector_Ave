"""Normalización de atributos y filtro numérico en centímetros."""

import re
import unicodedata
from dataclasses import dataclass, field

ALIAS = {
    "colores_principales": {
        "negro": "negr[oa]s?|oscur[oa]s?|negruzc[oa]s?", "blanco": "blanc[oa]s?|blanquecin[oa]s?|crema|beige",
        "gris": "gris(?:es|ace[oa]s?)?|plomiz[oa]s?",
        "marrón": "marron(?:es)?|pard[oa]s?|castan[oa]s?|cafes?|ruf[oa]s?",
        "rojo": "roj[oa]s?|rojiz[oa]s?|escarlata", "naranja": "naranjas?|anaranjad[oa]s?|canela",
        "amarillo": "amarill[oa]s?|amarillent[oa]s?|dorad[oa]s?",
        "verde": "verdes?|verdos[oa]s?|olivace[oa]s?|oliva",
        "azul": "azul(?:es|ad[oa]s?)?|turquesa|celestes?", "violeta": "violetas?|morad[oa]s?|violace[oa]s?",
        "iridiscente": "iridiscentes?|reflejos",
    },
    "dieta": {
        "semillas": "semillas?|granos?|granivor[oa]",
        "insectos": "insectos?|moscas?|bichos?|gusanos?|lombrices|lombriz|insectivor[oa]",
        "frutas": "frut[oa]s?|bayas?|frugivor[oa]|bananos?|platanos?|papayas?|mangos?",
        "néctar": "nectar|nectarivor[oa]",
        "peces": "peces|pescados?|pescando|pescaba|piscivor[oa]", "carroña": "carrona",
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
CAMPOS_VERIFICADOS = ("colores_principales", "dieta")
NUMERO = r"\d{1,4}(?:[.,]\d+)?"
UNIDAD = r"centimetros?|milimetros?|metros?|pulgadas?|cms|cm|mm|m"
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
    if unidad.startswith("pulgada"):
        return round(valor * 2.54, 6)
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
        if re.match(r"\s+(?:de (?:altura|envergadura|distancia)|sobre el nivel del mar|msnm)\b", despues):
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
            # Si el texto no menciona ningún color ni alimento, el modelo los completó por su cuenta.
            if campo in CAMPOS_VERIFICADOS and not re.search(
                rf"\b(?:{'|'.join(patrones.values())})\b", sin_tildes,
            ):
                valores[campo] = []
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
