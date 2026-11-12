"""Interfaz local de AvesCO. Ejecutar con python app.py."""

import argparse
import os

import gradio as gr

from avesco.asistente import AsistenteAves, ETIQUETAS_CAMPOS, NO_SE, OPCIONES_TENTATIVAS
from avesco.configuracion import Configuracion
from avesco.consulta import extraer_atributos
from avesco.datos import Catalogo
from avesco.indice import crear_indice
from avesco.modelos import ErrorModelo

EJEMPLOS = (
    ("Ave roja en un jardín", "Vi un ave de unos 13 cm, roja con alas negras. Atrapaba insectos en un jardín."),
    ("Ave azul junto al agua", "En un humedal vi un ave de unos 33 cm con pecho azul violáceo y alas verdosas."),
    ("Dos medidas parecidas", "Era de vientre amarillo y cabeza negra con ceja blanca. Medía entre 21 y 23 cm."),
)

CSS = """
.gradio-container {
    max-width: 1140px !important;
    margin: 0 auto !important;
    padding: 28px clamp(14px, 3vw, 34px) !important;
}
#cabecera { border-radius: 20px; padding: 26px 30px; margin-bottom: 16px;
    background: linear-gradient(115deg, #142f27, #205341); color: #f2f8f2; }
#cabecera h1 { margin: 0 0 7px; color: #fff; font-size: clamp(32px, 5vw, 52px);
    font-family: Georgia, serif; letter-spacing: -0.04em; }
#cabecera p { margin: 0; max-width: 65ch; color: #e2eee5; }
#modo { color: #35634e; font-size: .9rem; }
.dark #modo { color: #a6ceb5; }
#accion-consulta { background: #215940; border-color: #215940; color: white; }
#accion-consulta:hover { background: #174731; }
#panel-lateral { min-width: min(100%, 250px); }
"""


def formatear_respuesta(resultado):
    partes = [resultado["mensaje"]]
    if resultado["nota"]:
        partes.append(resultado["nota"])
    for i, ave in enumerate(resultado["aves"], start=1):
        partes.append(f"### {i}. {ave['nombre_comun']}\n*{ave['nombre_cientifico']}*")
        partes.append(f"**Tamaño en la guía** · {ave['tamano']}  \n{ave['plumaje']}.")
        for razon in ave["coincidencias"] + ave["diferencias"]:
            partes.append(f"- {razon}")
        citas = []
        for cita in ave["citas"]:
            campos = ", ".join(dict.fromkeys(ETIQUETAS_CAMPOS[c] for c in cita["campos"]))
            citas.append(f"- [{cita['titulo']}]({cita['url']}) · {cita['localizador']} · {campos}")
        partes.append("**Fuentes**\n" + "\n".join(citas))
    if resultado["aves"]:
        partes.append("La identificación es orientativa.")
    return "\n\n".join(partes)


def texto_del_mensaje(mensaje):
    """Gradio puede entregar el contenido como texto o como bloques."""
    contenido = mensaje["content"]
    if isinstance(contenido, str):
        return contenido
    return " ".join(bloque["text"] for bloque in contenido if bloque["type"] == "text")


def reunir_pistas(mensaje, historial):
    """Reúne las pistas de la observación hasta que haya una identificación."""
    actuales = extraer_atributos(mensaje, 0, {})
    # Una descripción extensa con medida y colores propios inicia otra observación.
    # Las respuestas breves a preguntas aclaratorias siguen acumulando pistas.
    if len(mensaje) >= 240 and actuales.rango_tamano_cm and len(actuales.colores_principales) >= 2:
        return mensaje
    pistas = [mensaje]
    for anterior, respuesta in zip(historial[-2::-2], historial[-1::-2]):
        if anterior["role"] != "user" or respuesta["role"] != "assistant":
            break
        if not texto_del_mensaje(respuesta).startswith((NO_SE, OPCIONES_TENTATIVAS)):
            break
        pistas.append(texto_del_mensaje(anterior))
    return "\n".join(reversed(pistas))


def construir_interfaz(asistente):
    def responder(mensaje, history):
        mensaje = (mensaje or "").strip()
        if not mensaje:
            return "", history or [], {}
        if len(mensaje) > 1600:
            raise gr.Error("La descripción admite hasta 1600 caracteres.")
        es_ejemplo = any(mensaje == ejemplo for _, ejemplo in EJEMPLOS)
        descripcion = mensaje if es_ejemplo else reunir_pistas(mensaje, history or [])
        if len(descripcion) > 1600:
            raise gr.Error("Las pistas juntas superan los 1600 caracteres. Limpia la conversación y resume tu observación.")
        try:
            resultado = asistente.responder(descripcion)
            respuesta = formatear_respuesta(resultado)
            diagnostico = resultado["diagnostico"]
        except ErrorModelo as error:
            respuesta = str(error)
            diagnostico = {"estado": "error_api"}
        return "", [
            *(history or []),
            {"role": "user", "content": mensaje},
            {"role": "assistant", "content": respuesta},
        ], diagnostico

    with gr.Blocks(title="AvesCO · Valle de Aburrá", analytics_enabled=False) as demo:
        gr.HTML(
            '<header id="cabecera"><h1>AvesCO</h1>'
            '<p>Describe un ave del Valle de Aburrá y compara posibles coincidencias con sus fuentes.</p></header>'
        )
        with gr.Row():
            with gr.Column(scale=3):
                history = gr.Chatbot(label="Conversación", height=480, sanitize_html=True)
                mensaje = gr.Textbox(
                    label="Describe el ave", placeholder="¿Cuánto medía? ¿Qué colores viste? ¿Dónde estaba?",
                    lines=2, max_lines=5,
                )
                with gr.Row():
                    enviar = gr.Button("Buscar coincidencias", variant="primary", elem_id="accion-consulta")
                    limpiar = gr.Button("Limpiar conversación", variant="secondary")
            with gr.Column(scale=1, elem_id="panel-lateral"):
                gr.Markdown("### Prueba una descripción")
                for etiqueta, ejemplo in EJEMPLOS:
                    boton = gr.Button(etiqueta, variant="secondary")
                    boton.click(lambda texto=ejemplo: texto, outputs=mensaje, api_visibility="private")
                gr.Markdown("NVIDIA NIM para consulta, embeddings y selección.", elem_id="modo")
                with gr.Accordion("Cómo se buscó", open=False):
                    diagnostico = gr.JSON(label="Atributos, filtro y similitud")

        gr.on(
            triggers=[mensaje.submit, enviar.click], fn=responder, inputs=[mensaje, history],
            outputs=[mensaje, history, diagnostico], api_name="identificar",
            concurrency_limit=1,
        )
        limpiar.click(lambda: ("", [], {}), outputs=[mensaje, history, diagnostico], api_visibility="private")
    return demo


def main():
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", type=int, default=7860)
    args = parser.parse_args()
    config = Configuracion.cargar()
    catalogo = Catalogo.cargar()
    indice = crear_indice(config, catalogo)
    try:
        asistente = AsistenteAves(config, catalogo, indice, indice.modelo)
        construir_interfaz(asistente).launch(
            server_name="127.0.0.1", server_port=args.puerto, share=False,
            css=CSS, show_error=True,
        )
    finally:
        indice.cerrar()


if __name__ == "__main__":
    main()
