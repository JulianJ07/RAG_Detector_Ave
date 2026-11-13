# Registra trazas por etapa para localizar fallos en casos de evaluación.
"""Ejecuta casos etiquetados y guarda respuestas, trazas y métricas comparables."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from avesco.asistente import AsistenteAves
from avesco.configuracion import RAIZ, Configuracion
from avesco.datos import Catalogo
from avesco.evaluacion import ChatObservado, IndiceObservado, revisar, resumir
from avesco.indice import crear_indice
from avesco.modelos import ErrorModelo


def cargar_casos(ruta, grupos, catalogo):
    # Lee los casos solicitados y comprueba sus etiquetas contra el catálogo.
    casos = json.loads(ruta.read_text(encoding="utf-8"))["casos"]
    ids = [c["id"] for c in casos]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay identificadores de caso repetidos.")
    for caso in casos:
        if caso["esperado"] is not None and caso["esperado"] not in catalogo.aves:
            raise ValueError(f"Especie esperada fuera del catálogo: {caso['id']}")
        if not isinstance(caso["consulta"], str) or not 0 < len(caso["consulta"]) <= 1600:
            raise ValueError(f"Consulta inválida: {caso['id']}")
    elegidos = [c for c in casos if c["grupo"] in grupos]
    if not elegidos:
        raise ValueError("No hay casos en los grupos solicitados.")
    return elegidos


def informe_md(informe):
    # Convierte las métricas y fallos en un informe legible.
    r = informe["resumen"]
    lineas = ["# Evaluación de AvesCO", "", f"Fecha UTC: {informe['metadata']['fecha_utc']}", "",
              f"Primera opción: **{r['top1']}/{r['positivas']}**. Entre las tres primeras: **{r['top3']}/{r['positivas']}**.",
              f"Casos negativos con estado permitido: **{r['negativas_con_estado_correcto']}/{r['negativas']}**.",
              f"Todos los criterios aprobados: **{r['aprobadas']}/{r['ejecuciones']}**.", "",
              "Los casos sintéticos proceden del catálogo y requieren revisión humana. Los casos de regresión ya se usaron para ajustar el sistema; estos resultados no miden precisión en observaciones independientes.", "",
              "Las etapas indicadas localizan síntomas observables; la causa debe revisarse en las trazas. Una cita válida pertenece al catálogo, pero eso no prueba que su contenido respalde cada afirmación.", "",
              "## Resultados por grupo", "",
              "| Grupo | Primera opción | Top 3 | Negativos con estado correcto | Todos los criterios |",
              "|---|---|---|---|---|"]
    for grupo in sorted({f["grupo"] for f in informe["casos"]}):
        g = resumir([f for f in informe["casos"] if f["grupo"] == grupo])
        lineas.append(f"| {grupo} | {g['top1']}/{g['positivas']} | {g['top3']}/{g['positivas']} | {g['negativas_con_estado_correcto']}/{g['negativas']} | {g['aprobadas']}/{g['ejecuciones']} |")
    lineas += ["", "## Ejecuciones", "", "| Caso | Grupo | Primero | Top 3 | Estado | Fallos | Segundos |",
               "|---|---|---|---|---|---|---|"]
    for fila in informe["casos"]:
        v = fila.get("revision", {})
        marca = lambda valor: "—" if valor is None else ("Sí" if valor else "No")
        lineas.append(f"| {fila['id']} · {fila['repeticion']} | {fila['grupo']} | {marca(v.get('top1'))} | {marca(v.get('top3'))} | {fila.get('respuesta', {}).get('estado', 'error')} | {', '.join(v.get('fallos', [])) or '—'} | {fila['segundos']:.2f} |")
    lineas += ["", "## Casos para revisar", ""]
    for fila in informe["casos"]:
        v = fila.get("revision", {})
        if v.get("aprobado"):
            continue
        respuesta = fila.get("respuesta", {})
        lineas += [f"### {fila['id']} · repetición {fila['repeticion']}", "",
                   "> " + fila["entrada_utilizada"].replace("\n", "\n> "), "",
                   f"Esperado: `{fila['esperado']}`. Estado recibido: `{respuesta.get('estado', 'error')}`.",
                   "Especies devueltas: " + (", ".join(a["nombre_comun"] for a in respuesta.get("aves", [])) or "ninguna") + ".", "",
                   "Fallos: " + ", ".join(v.get("fallos", [])) + ".", ""]
        for error in v.get("errores_atributos", []):
            lineas += ["- " + json.dumps(error, ensure_ascii=False)]
        lineas.append("")
    lineas += ["", "## Próxima revisión", "",
               "1. Revisar los casos fallidos en el JSON: entrada utilizada, atributos, IDs elegibles, ranking, preselección y respuesta.",
               "2. Confirmar la especie y la calidad de su ficha con una fuente o una persona conocedora de aves.",
               "3. Cambiar una sola cosa: instrucciones, datos, filtro o selección. Repetir el grupo de desarrollo y comprobar las regresiones.",
               "4. Añadir observaciones reales etiquetadas por una persona y mantener la reserva fuera de los ajustes.", ""]
    return "\n".join(lineas)


def main():
    # Lee las opciones del programa y prepara los recursos que necesita.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casos", type=Path, default=RAIZ / "evaluacion/casos_robustez.json")
    parser.add_argument("--grupos", nargs="+", choices=["regresion", "desarrollo", "reserva"], default=["regresion", "desarrollo"])
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--salida", type=Path, required=True, help="Informe JSON; también se crea un Markdown del mismo nombre.")
    args = parser.parse_args()
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser al menos 1")
    catalogo = Catalogo.cargar()
    casos = cargar_casos(args.casos, args.grupos, catalogo)
    config = Configuracion.cargar()
    codigo = [RAIZ / "app.py", RAIZ / "evaluar_robustez.py", *sorted((RAIZ / "avesco").glob("*.py"))]
    metadata = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RAIZ, text=True).strip(),
        "huella_codigo": hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in codigo)).hexdigest(),
        "huella_casos": hashlib.sha256(args.casos.read_bytes()).hexdigest(),
        "huella_catalogo": catalogo.huella_fichas, "grupos": args.grupos,
        "modelo_chat": config.modelo_chat, "modelo_embed": config.modelo_embed,
        "umbral": config.umbral_similitud, "tolerancia_tamano": config.tolerancia_tamano,
        "repeticiones": args.repeticiones,
    }
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    filas = []

    def guardar():
        # Persiste las ejecuciones acumuladas para conservar resultados parciales.
        informe = {"metadata": metadata, "resumen": resumir(filas), "casos": filas}
        args.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.salida.with_suffix(".md").write_text(informe_md(informe), encoding="utf-8")

    indice = crear_indice(config, catalogo)
    traza = {}
    asistente = AsistenteAves(config, catalogo, IndiceObservado(indice, traza), ChatObservado(indice.modelo, traza))
    try:
        for repeticion in range(1, args.repeticiones + 1):
            for caso in casos:
                traza.clear()
                inicio = time.perf_counter()
                consulta = caso["consulta"]
                if caso.get("historial"):
                    from app import reunir_pistas
                    consulta = reunir_pistas(consulta, caso["historial"])
                fila = {**caso, "repeticion": repeticion, "entrada_utilizada": consulta}
                try:
                    respuesta = asistente.responder(consulta)
                    fila.update(respuesta=respuesta, revision=revisar(caso, respuesta, catalogo, traza))
                except ErrorModelo as error:
                    fila.update(error=str(error), revision={"aprobado": False, "fallos": ["api"]})
                fila.update(traza=dict(traza), segundos=round(time.perf_counter() - inicio, 3))
                filas.append(fila)
                guardar()
                print(f"{caso['id']} [{repeticion}]: {','.join(fila['revision']['fallos']) or 'OK'}", flush=True)
    finally:
        indice.cerrar()
    print(json.dumps(resumir(filas), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
