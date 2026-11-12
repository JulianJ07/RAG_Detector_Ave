import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from app import reunir_pistas
from avesco.asistente import AsistenteAves, comparar, menciona_nombre
from avesco.configuracion import Configuracion, NVIDIA_URL
from avesco.consulta import extraer_atributos, extraer_tamano, filtrar_por_tamano
from avesco.datos import Catalogo
from avesco.indice import IndiceAves
from avesco.modelos import ClienteNvidia, ErrorModelo


@pytest.fixture(scope="module")
def catalogo():
    return Catalogo.cargar()


@pytest.fixture
def config():
    return Configuracion("", "chat-prueba", "embed-prueba", 0.20, 0.80)


@pytest.mark.parametrize(("consulta", "esperado"), [
    ("Mide entre 21 y 23 cm.", (21, 23)),
    ("Mide entre 21 cm y 230 mm.", (21, 23)),
    ("Unos 0,36 m.", (28.8, 43.2)),
    ("8,7 centímetros", (6.96, 10.44)),
    ("La vi a 1500 m sobre el nivel del mar. Medía 12 cm.", (9.6, 14.4)),
    ("Es pequeña", None),
    ("Medía menos de 13 cm", None),
    ("Una medida de 13 cm y otra de 20 cm.", None),
    ("Medía de 23 a 21 cm.", None),
    ("Unas 10 pulgadas", (20.32, 30.48)),
])
def test_medidas(consulta, esperado):
    assert extraer_tamano(consulta, 0.20) == esperado


def test_catalogo_y_tamano(catalogo):
    assert len(catalogo.aves) == 120
    assert catalogo.aves["coereba_flaveola"]["nombre_comun"] == "Silga Mielera"
    assert catalogo.aves["falco_sparverius"]["nombre_comun"] == "Cernícalo"
    assert catalogo.aves["pygochelidon_cyanoleuca"]["nombre_comun"] == "Golondrina Azul y Blanca"
    candidatos = filtrar_por_tamano(catalogo.aves, (21, 22))
    assert "pitangus_sulphuratus" in candidatos
    assert "myiozetetes_cayanensis" not in candidatos
    assert len(filtrar_por_tamano(catalogo.aves, None)) == 120


def test_atributos(catalogo):
    atributos = extraer_atributos(
        "Gris, sin manchas rojas. Planeaba sobre un parque.", 0.2, catalogo.vocabularios,
    )
    assert atributos.colores_principales == ["gris"]
    assert atributos.vuelo == ["planeo"]
    assert atributos.entorno == ["parque_jardin"]
    limpio = extraer_atributos("Vi un ave azul", 0.2, catalogo.vocabularios, {
        "colores_principales": ["AZUL", "Azul", "inventado", 3],
        "rango_tamano_cm": [20, 22],
    })
    assert limpio.colores_principales == ["azul"]
    assert limpio.rango_tamano_cm is None
    coincidencias, diferencias = comparar(catalogo.aves["columba_livia"], atributos)
    assert coincidencias["colores_principales"] == ["gris"]
    assert not diferencias


def test_rasgos_inventados_por_el_modelo(catalogo):
    inventados = {"colores_principales": ["marrón", "blanco"], "dieta": ["insectos"], "entorno": ["parque_jardin"]}
    atributos = extraer_atributos("Vi un Turdus fuscater en el parque.", 0.2, catalogo.vocabularios, inventados)
    assert atributos.colores_principales == []
    assert atributos.dieta == []
    assert atributos.entorno == ["parque_jardin"]


@pytest.mark.parametrize(("nombre", "texto", "esperado"), [
    ("Mayo", "vi un ave amarilla en mayo", False),
    ("Caravana", "paso una caravana de carros", False),
    ("Caravana", "creo que era una caravana", True),
    ("Gallinazo Común", "vi un gallinazo comun", True),
    ("Turdus fuscater", "vi un turdus fuscater", True),
])
def test_nombres_que_son_palabras_comunes(nombre, texto, esperado):
    assert menciona_nombre(nombre, texto) is esperado


def test_sigue_sin_chat(config, catalogo):
    def chat_json(*_):
        raise ErrorModelo("NVIDIA limitó la solicitud.")

    def buscar(_texto, ids, top_k):
        return [("thraupis_episcopus", 0.91)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder("Era azul y comía fruta en un parque. Medía 16 cm.")
    assert [a["id"] for a in respuesta["aves"]] == ["thraupis_episcopus"]
    assert len(respuesta["diagnostico"]["avisos"]) == 2


def test_tentativas_con_similitud_baja(config, catalogo):
    def buscar(_texto, ids, top_k):
        return [("cinclus_leucocephalus", config.umbral_similitud - 0.05)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=lambda *_: None))
    assert asistente.responder("Ave negra y blanca sobre el hielo de un lago.")["estado"] == "abstencion"


def test_migas_de_pan_favorecen_aves_urbanas(catalogo):
    config = Configuracion("", "chat-prueba", "embed-prueba", 0.20, 0.26)
    puntajes = {"sporophila_intermedia": 0.3816, "vanellus_chilensis": 0.3373,
                "columba_livia": 0.3020, "patagioenas_fasciata": 0.2740}

    def buscar(_texto, ids, top_k):
        return sorted(((i, s) for i, s in puntajes.items() if i in ids), key=lambda p: -p[1])

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=lambda *_: None))
    respuesta = asistente.responder("vi un ave comiendo migas de pan al medio dia\nblanca con gris")
    assert respuesta["aves"][0]["id"] == "columba_livia"


def test_complemento_tras_identificacion():
    historial = [
        {"role": "user", "content": "Era rojo con alas negras, de unos 13 cm."},
        {"role": "assistant", "content": "Estas son las coincidencias mejor respaldadas por las fichas."},
    ]
    assert reunir_pistas("Atrapaba insectos en un jardín.", historial).startswith("Era rojo")
    assert reunir_pistas("Otra ave, azul de 16 cm.", historial) == "Otra ave, azul de 16 cm."


class ModeloPrueba:
    identificador = "modelo-prueba"

    def __init__(self):
        self.tipos = []

    def embeddings(self, textos, tipo):
        self.tipos.append(tipo)
        return [[1.0, 0.0] for _ in textos]


def test_indice_reutiliza_y_filtra(tmp_path, catalogo):
    modelo = ModeloPrueba()
    indice = IndiceAves(catalogo, modelo, tmp_path)
    try:
        assert indice.asegurar()
        assert set(modelo.tipos) == {"passage"}
    finally:
        indice.cerrar()
    modelo = ModeloPrueba()
    indice = IndiceAves(catalogo, modelo, tmp_path)
    try:
        assert not indice.asegurar()
        assert not modelo.tipos
        assert indice.retrieve_relevant_chunks("ave", ["pitangus_sulphuratus"]) == [("pitangus_sulphuratus", 1.0)]
        assert modelo.tipos == ["query"]
    finally:
        indice.cerrar()


def test_abstencion_sin_busqueda(config, catalogo):
    asistente = AsistenteAves(config, catalogo, None, SimpleNamespace(chat_json=lambda *_: None))
    assert asistente.responder("Vi un ave.")["estado"] == "abstencion"
    assert asistente.responder("Ave roja de entre 110 y 120 cm.")["diagnostico"]["especies_despues_del_filtro"] == 0
    assert "vuelo" in asistente.responder("Se quedaba suspendida.")["nota"]


def test_cita_y_respuesta_del_llm_invalida(config, catalogo):
    def chat_json(_instrucciones, entrada):
        if "vocabulario" in entrada:
            return {"colores_principales": ["azul"], "dieta": ["frutas"], "entorno": ["parque_jardin"]}
        return {"ids": ["especie_inventada"]}

    def buscar(_texto, ids, top_k):
        assert top_k >= 3
        assert "thraupis_episcopus" in ids
        assert "columba_livia" not in ids
        return [("thraupis_episcopus", 0.91)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder("Era azul y comía fruta en un parque. Medía 16 cm.")
    assert [a["id"] for a in respuesta["aves"]] == ["thraupis_episcopus"]
    assert "seleccion_llm" in respuesta["diagnostico"]
    assert any("p. 331" == c["localizador"] for c in respuesta["aves"][0]["citas"])


def test_contrato_nvidia_con_transporte_simulado(config):
    nvidia = ClienteNvidia(Configuracion("clave-prueba", config.modelo_chat, config.modelo_embed, 0.2, 0.6))
    llamadas = []

    def responder(request):
        llamadas.append((request.url.path, json.loads(request.content)))
        assert request.headers["authorization"] == "Bearer clave-prueba"
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}]})
        return httpx.Response(429, json={"error": {"message": "simulado"}})

    with httpx.Client(transport=httpx.MockTransport(responder)) as transporte:
        nvidia.client = OpenAI(api_key="clave-prueba", base_url=NVIDIA_URL, http_client=transporte, max_retries=0)
        assert nvidia.embeddings(["texto"], "passage") == [[0.1, 0.2]]
        assert nvidia.embeddings(["consulta"], "query") == [[0.1, 0.2]]
        with pytest.raises(ErrorModelo, match="cuota") as error:
            nvidia.chat_json("instrucciones", {"texto": "consulta"})
        assert "clave-prueba" not in str(error.value)
    assert llamadas[0][1]["input_type"] == "passage"
    assert llamadas[1][1]["input_type"] == "query"
    assert llamadas[2][1]["response_format"] == {"type": "json_object"}
