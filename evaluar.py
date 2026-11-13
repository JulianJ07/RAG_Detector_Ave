# Compara el RAG y la búsqueda por palabras con los casos finales o de calibración.
"""Compara búsqueda léxica y recuperación semántica con casos separados."""

import argparse
import json
from pathlib import Path

from avesco.asistente import AsistenteAves, buscar_por_palabras
from avesco.configuracion import RAIZ, Configuracion
from avesco.datos import Catalogo
from avesco.indice import crear_indice


def evaluar(casos, asistente, umbral=None):
    # Devuelve una fila por consulta con aciertos, citas y respuesta.
    filas = []
    for caso in casos:
        consulta = caso["consulta"]
        esperado = caso["esperado"]
        resultado = asistente.responder(consulta, umbral=umbral)
        # Compara IDs para evitar diferencias por nombres comunes.
        ids_rag = [ave["id"] for ave in resultado["aves"]]
        ids_base = [id_ave for id_ave, _ in buscar_por_palabras(consulta, asistente.catalogo)]
        # Solo evalúa citas cuando la respuesta incluye especies.
        citas_validas = None
        if resultado["aves"]:
            citas_validas = all(
                ave["citas"] and all(
                    any(c["url"] == cita["url"] and c["localizador"] == cita["localizador"]
                        for c in asistente.catalogo.citas(ave["id"], [campo]))
                    for cita in ave["citas"] for campo in cita["campos"]
                )
                for ave in resultado["aves"]
            )
        filas.append({
            **caso, "linea_base_top_3": ids_base, "rag_top_3": ids_rag, "respuesta": resultado,
            "acierto_base": esperado in ids_base if esperado else not ids_base,
            "acierto_rag": esperado in ids_rag if esperado else not ids_rag,
            "citas_del_catalogo": citas_validas,
        })
    return filas


def main():
    # Lee las opciones del programa y prepara los recursos que necesita.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibracion", action="store_true", help="Ejecuta solo el conjunto de calibración.")
    parser.add_argument("--umbral", type=float)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()
    # Carga una configuración común para los casos de la ejecución.
    config = Configuracion.cargar()
    catalogo = Catalogo.cargar()
    indice = crear_indice(config, catalogo)
    try:
        asistente = AsistenteAves(config, catalogo, indice, indice.modelo)
        conjunto = "calibracion" if args.calibracion else "finales"
        casos = json.loads((RAIZ / "evaluacion/casos.json").read_text(encoding="utf-8"))[conjunto]
        resultados = evaluar(casos, asistente, args.umbral)
        resumen = {
            "modo": config.modo, "conjunto": conjunto, "umbral": resultados[0]["respuesta"]["diagnostico"]["umbral"],
            "aciertos_base": sum(r["acierto_base"] for r in resultados),
            "aciertos_rag": sum(r["acierto_rag"] for r in resultados),
            "explicaciones_generadas": sum(bool(r["respuesta"].get("explicacion")) for r in resultados),
            "total": len(resultados), "casos": resultados,
        }
        for r in resultados:
            print(f"{r['tipo']}: esperado={r['esperado']} | base={r['linea_base_top_3']} | rag={r['rag_top_3']}")
        print(f"Base {resumen['aciertos_base']}/{len(resultados)} · RAG {resumen['aciertos_rag']}/{len(resultados)}")
        print(f"Explicaciones generadas por el LLM y aceptadas: {resumen['explicaciones_generadas']}")
        if args.salida:
            args.salida.write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        indice.cerrar()


if __name__ == "__main__":
    main()
