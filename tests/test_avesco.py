import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from avesco.asistente import AsistenteAves, comparar
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
    return Configuracion("local", "", "chat-prueba", "embed-prueba", 0.20, 0.80)


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
    limpio = extraer_atributos("Vi un ave", 0.2, catalogo.vocabularios, {
        "colores_principales": ["AZUL", "Azul", "inventado", 3],
        "rango_tamano_cm": [20, 22],
    })
    assert limpio.colores_principales == ["azul"]
    assert limpio.rango_tamano_cm is None
    coincidencias, diferencias = comparar(catalogo.aves["columba_livia"], atributos)
    assert coincidencias["colores_principales"] == ["gris"]
    assert not diferencias


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
    asistente = AsistenteAves(config, catalogo, None)
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
    nvidia = ClienteNvidia(Configuracion("nvidia", "clave-prueba", config.modelo_chat, config.modelo_embed, 0.2, 0.6))
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
