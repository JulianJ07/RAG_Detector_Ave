# Compara la salida y la traza de cada consulta con el caso esperado.
"""Evaluación por etapas, sin alterar las decisiones del asistente."""

from collections import Counter


class IndiceObservado:
    def __init__(self, indice, traza):
        # Conserva las dependencias que el objeto reutiliza durante el flujo.
        self.indice, self.traza = indice, traza

    def retrieve_relevant_chunks(self, texto, ids, top_k):
        # Registra qué IDs llegaron al índice antes de delegar la recuperación.
        self.traza["ids_elegibles"] = list(ids)
        filas = self.indice.retrieve_relevant_chunks(texto, ids, top_k)
        self.traza["recuperadas"] = [{"id": id_ave, "similitud": score} for id_ave, score in filas]
        return filas


class ChatObservado:
    def __init__(self, modelo, traza):
        # Conserva las dependencias que el objeto reutiliza durante el flujo.
        self.modelo, self.traza = modelo, traza

    def chat_json(self, instrucciones, entrada):
        # Identifica la etapa antes de llamar al cliente y conservar su salida.
        etapa = "extraccion" if "vocabulario" in entrada else "seleccion"
        if etapa == "seleccion":
            # Guarda qué candidatas recibió NVIDIA para la selección final.
            self.traza["preseleccion"] = [a["id"] for a in entrada["candidatas"]]
        respuesta = self.modelo.chat_json(instrucciones, entrada)
        # Conserva la salida de esa etapa para contrastarla con el caso esperado.
        self.traza[etapa] = respuesta
        return respuesta


def revisar(caso, respuesta, catalogo, traza):
    """Señala síntomas y la primera etapa observable; no demuestra causalidad."""
    esperado = caso["esperado"]
    ids = [a["id"] for a in respuesta["aves"]]
    atributos = respuesta["diagnostico"].get("atributos", {})
    errores_atributos = []
    for campo, valor in caso.get("atributos_esperados", {}).items():
        actual = atributos.get(campo)
        if campo == "rango_tamano_cm":
            coincide = actual is None if valor is None else (
                isinstance(actual, (list, tuple)) and len(actual) == 2
                and all(abs(a - b) < 1e-6 for a, b in zip(actual, valor))
            )
        else:
            coincide = actual == [] if valor == [] else (
                isinstance(actual, list) and set(valor).issubset(actual)
            )
        if not coincide:
            errores_atributos.append({"campo": campo, "esperado": valor, "actual": actual})
    for campo, valores in caso.get("atributos_prohibidos", {}).items():
        presentes = set(valores).intersection(atributos.get(campo) or [])
        if presentes:
            errores_atributos.append({"campo": campo, "prohibidos_detectados": sorted(presentes)})

    citas_validas = all(
        ave["id"] in catalogo.aves and bool(ave["citas"]) and all(
            cita["campos"] and all(
                any(c["url"] == cita["url"] and c["localizador"] == cita["localizador"]
                    for c in catalogo.citas(ave["id"], [campo]))
                for campo in cita["campos"]
            ) for cita in ave["citas"]
        ) for ave in respuesta["aves"]
    ) if ids else None
    top1 = ids[:1] == [esperado] if esperado else None
    top3 = esperado in ids[:3] if esperado else None
    estados = caso.get("estados_permitidos", ["coincidencias"] if esperado else ["abstencion"])
    estado_valido = respuesta["estado"] in estados
    recuperadas = [a["id"] for a in traza.get("recuperadas", [])]
    preseleccion = traza.get("preseleccion", [])
    fallos = []
    if errores_atributos:
        fallos.append("interpretacion")
    if esperado and not top1:
        if esperado not in catalogo.aves:
            fallos.append("catalogo")
        elif esperado not in traza.get("ids_elegibles", []):
            fallos.append("filtros")
        elif esperado not in recuperadas:
            fallos.append("recuperacion")
        elif esperado not in preseleccion:
            fallos.append("reglas_de_preseleccion")
        elif esperado not in ids:
            fallos.append("seleccion_nvidia")
        else:
            fallos.append("orden_de_respuesta")
    if not estado_valido:
        fallos.append("estado_o_abstencion")
    if citas_validas is False:
        fallos.append("citas")
    return {
        "top1": top1, "top3": top3, "estado_valido": estado_valido,
        "citas_validas": citas_validas, "errores_atributos": errores_atributos,
        "posicion_recuperada": recuperadas.index(esperado) + 1 if esperado in recuperadas else None,
        "en_preseleccion": esperado in preseleccion if esperado else None,
        "fallos": fallos, "aprobado": not fallos,
    }


def resumir(filas):
    # Separa casos con especie esperada de casos que requieren abstención.
    positivas = [f for f in filas if f["esperado"]]
    negativas = [f for f in filas if not f["esperado"]]
    return {
        "ejecuciones": len(filas), "positivas": len(positivas), "negativas": len(negativas),
        "top1": sum(f.get("revision", {}).get("top1") is True for f in positivas),
        "top3": sum(f.get("revision", {}).get("top3") is True for f in positivas),
        "negativas_con_estado_correcto": sum(f.get("revision", {}).get("estado_valido") is True for f in negativas),
        "aprobadas": sum(f.get("revision", {}).get("aprobado") is True for f in filas),
        "fallos_por_etapa": dict(Counter(etapa for f in filas for etapa in f.get("revision", {}).get("fallos", []))),
    }
