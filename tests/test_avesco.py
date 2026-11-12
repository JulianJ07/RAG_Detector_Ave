import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from avesco.asistente import AsistenteAves, comparar, menciona_nombre, OPCIONES_TENTATIVAS
from avesco.configuracion import Configuracion, NVIDIA_URL
from avesco.consulta import extraer_atributos, extraer_tamano, filtrar_por_tamano, filtrar_por_taxonomia
from avesco.datos import Catalogo
from avesco.indice import IndiceAves
from avesco.modelos import ClienteNvidia, ErrorModelo


DESCRIPCION_GALLINAZO = """es un ave rapaz carroñera de gran tamaño muy común en Colombia y en el continente americano.
Características principales
• Tamaño y peso: Mide cerca de 74 cm de longitud, con una envergadura de alas de 1.33 m a 1.67 m y un peso que ronda los 2 a 2.75 kg.
• Plumaje: Es de color negro intenso o lustroso en la mayor parte del cuerpo. Al volar, se aprecian unas manchas blancas características en la parte inferior de las puntas de las alas.
• Cabeza y cuello: No tienen plumas; su piel es de color gris oscuro o negro mate, de aspecto arrugado. Esta adaptación evita que se ensucie con la descomposición al alimentarse."""
DESCRIPCION_SIRIRI = (Path(__file__).parent / "datos/siriri.txt").read_text(encoding="utf-8").strip()
DESCRIPCION_TORCAZA = (Path(__file__).parent / "datos/torcaza.txt").read_text(encoding="utf-8").strip()
DESCRIPCION_SINSONTE = (Path(__file__).parent / "datos/sinsonte.txt").read_text(encoding="utf-8").strip()


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
    (DESCRIPCION_GALLINAZO, (59.2, 88.8)),
    (DESCRIPCION_SIRIRI, (18, 22)),
    ("Longitud: 74 cm. Envergadura: 1.33 m a 1.67 m.", (59.2, 88.8)),
    ("Tiene una envergadura aproximada de 133 a 167 cm y una longitud de 74 cm.", (59.2, 88.8)),
    ("Mide 1.5 m de envergadura y 74 cm de longitud.", (59.2, 88.8)),
    ("Mide 74 cm de longitud y 150 cm de envergadura.", (59.2, 88.8)),
    ("Envergadura de alas de 1.33 m a 1.67 m.", None),
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


@pytest.mark.parametrize("descripcion", ["Ave carroñera", "Aves carroñeras", "Se alimenta de carroña"])
def test_dieta_carronera(descripcion, catalogo):
    assert extraer_atributos(descripcion, 0.2, catalogo.vocabularios).dieta == ["carroña"]


def test_gallinazo_con_longitud_y_envergadura(config, catalogo):
    def chat_json(_instrucciones, entrada):
        if "vocabulario" in entrada:
            return {"colores_principales": ["negro", "blanco"], "dieta": ["carroña"]}
        return {"ids": ["coragyps_atratus"]}

    def buscar(_texto, ids, top_k):
        assert "coragyps_atratus" in ids
        assert "milvago_chimachima" not in ids
        assert "rupornis_magnirostris" not in ids
        return [("nycticorax_nycticorax", 0.94), ("coragyps_atratus", 0.91)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder(DESCRIPCION_GALLINAZO)
    assert respuesta["diagnostico"]["atributos"]["rango_tamano_cm"] == (59.2, 88.8)
    assert respuesta["estado"] == "coincidencias"
    assert respuesta["aves"][0]["id"] == "coragyps_atratus"
    assert respuesta["aves"][0]["citas"]


@pytest.mark.parametrize(("texto", "familia"), [
    ("Es de la familia de los tiránidos.", "Tyrannidae"),
    ("Pertenece a la familia Tyrannidae.", "Tyrannidae"),
    ("Es un colibrí.", "Trochilidae"),
])
def test_taxonomia_explicita(texto, familia, catalogo):
    ids, criterios = filtrar_por_taxonomia(catalogo.aves, texto, list(catalogo.aves))
    assert ids
    assert criterios["familia"] == [familia]
    assert all(catalogo.aves[id_ave]["familia"] == familia for id_ave in ids)


@pytest.mark.parametrize("texto", ["No es un colibrí.", "No pertenece a la familia de los tiránidos.", "Ave de vientre amarillo."])
def test_no_inferir_taxonomia(texto, catalogo):
    ids, criterios = filtrar_por_taxonomia(catalogo.aves, texto, list(catalogo.aves))
    assert not criterios
    assert len(ids) == 120


def test_siriri_respeta_tamano_y_taxonomia(config, catalogo):
    def chat_json(_instrucciones, entrada):
        if "vocabulario" in entrada:
            return {"colores_principales": ["gris", "amarillo"], "dieta": ["insectos"]}
        return {"ids": ["tyrannus_melancholicus"]}

    def buscar(_texto, ids, top_k):
        assert "tyrannus_melancholicus" in ids
        assert "sporophila_intermedia" not in ids
        assert "colaptes_punctigula" not in ids
        assert all(catalogo.aves[id_ave]["familia"] == "Tyrannidae" for id_ave in ids)
        assert all(18 <= catalogo.aves[id_ave]["longitud_min_cm"] <= 22 for id_ave in ids)
        return [("tyrannus_melancholicus", 0.91)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder(DESCRIPCION_SIRIRI)
    assert respuesta["aves"][0]["id"] == "tyrannus_melancholicus"
    assert respuesta["diagnostico"]["taxonomia_consultada"] == {
        "familia": ["Tyrannidae"], "orden": ["Passeriformes"],
    }


def test_descripcion_nueva_no_hereda_medidas():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Vi un ave marrón de unos 12 cm."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    texto = reunir_pistas(DESCRIPCION_SIRIRI, historial)
    assert texto == DESCRIPCION_SIRIRI
    assert extraer_tamano(texto, 0.2) == (18, 22)


def test_aclaracion_breve_conserva_observacion():
    from app import reunir_pistas

    historial = [{"role": "user", "content": [{"type": "text", "text": "Vi un ave gris de 22 cm."}]},
                 {"role": "assistant", "content": [{"type": "text", "text": OPCIONES_TENTATIVAS}]}]
    texto = reunir_pistas("Tenía el vientre amarillo.", historial)
    assert "gris de 22 cm" in texto
    assert "vientre amarillo" in texto
    assert extraer_tamano(texto, 0.2) == (17.6, 26.4)


@pytest.mark.parametrize("rango", ["22 y 28", "22 y 36"])
def test_nombre_en_comparacion_no_excluye_torcaza(config, catalogo, rango):
    def chat_json(_instrucciones, entrada):
        if "vocabulario" in entrada:
            return {"colores_principales": ["gris"], "dieta": [], "entorno": [], "vuelo": []}
        return {"ids": ["zenaida_auriculata"]}

    def buscar(_texto, ids, top_k):
        assert "zenaida_auriculata" in ids
        assert "leptotila_verreauxi" in ids
        assert all(catalogo.aves[i]["familia"] == "Columbidae" for i in ids)
        return [("zenaida_auriculata", 0.95), ("leptotila_verreauxi", 0.91)]

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder(DESCRIPCION_TORCAZA.replace("22 y 28", rango))
    assert respuesta["aves"][0]["id"] == "zenaida_auriculata"
    assert respuesta["diagnostico"]["especies_despues_de_taxonomia"] >= 2


def test_torcaza_datos_complementarios_citados(catalogo):
    import hashlib
    from avesco.configuracion import DATA

    ave = catalogo.aves["zenaida_auriculata"]
    assert "gris" in ave["colores_principales"]
    assert "tonos grises" in catalogo.fichas[ave["id"]]["texto"]
    citas = catalogo.citas(ave["id"], ["colores_principales", "descripcion_plumaje"])
    assert any(c["url"].startswith("https://www.sag.gob.cl/") for c in citas)
    assert catalogo.huella_fichas != hashlib.sha256((DATA / "processed/fichas_rag.jsonl").read_bytes()).hexdigest()
    # Cada carga parte del catálogo base, sin duplicar el complemento.
    recargado = Catalogo.cargar()
    assert recargado.huella_fichas == catalogo.huella_fichas
    assert recargado.aves[ave["id"]]["descripcion_plumaje"] == ave["descripcion_plumaje"]


def test_torcaza_nueva_no_hereda_medida_anterior():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Era un ave de 12 cm."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    assert reunir_pistas(DESCRIPCION_TORCAZA, historial) == DESCRIPCION_TORCAZA


@pytest.mark.parametrize(("texto", "campo", "taxon"), [
    ("Es de la familia Mimidae.", "familia", "Mimidae"),
    ("Es de la familia MIMIDAE.", "familia", "Mimidae"),
    ("Pertenece al orden Sphenisciformes.", "orden", "Sphenisciformes"),
])
def test_taxonomia_sin_cobertura_no_se_ignora(catalogo, texto, campo, taxon):
    ids, criterios = filtrar_por_taxonomia(catalogo.aves, texto, list(catalogo.aves))
    assert criterios[campo] == [taxon]
    assert ids == []


def test_familia_ausente_negada_no_restringe(catalogo):
    ids, criterios = filtrar_por_taxonomia(catalogo.aves, "No pertenece a la familia Mimidae.", list(catalogo.aves))
    assert len(ids) == 120
    assert not criterios


def test_sinonimo_paseriformes_no_crea_orden_inexistente(catalogo):
    ids, criterios = filtrar_por_taxonomia(catalogo.aves, "Es un ave paseriforme, de los paseriformes.", list(catalogo.aves))
    assert ids
    assert criterios == {"orden": ["Passeriformes"]}


def test_sinsonte_fuera_del_catalogo_no_sugiere_otras_familias(config, catalogo):
    def no_buscar(*args, **kwargs):
        pytest.fail("Una familia sin cobertura no debe llegar a la búsqueda ni a la selección.")

    def chat_json(_instrucciones, entrada):
        assert "vocabulario" in entrada
        return {"colores_principales": ["gris", "blanco"], "dieta": [], "entorno": [], "vuelo": []}

    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=no_buscar),
                              SimpleNamespace(chat_json=chat_json))
    respuesta = asistente.responder(DESCRIPCION_SINSONTE)
    assert respuesta["estado"] == "abstencion"
    assert not respuesta["aves"]
    assert respuesta["diagnostico"]["taxones_sin_cobertura"] == {"familia": ["Mimidae"]}
    assert "catálogo actual no incluye fichas" in respuesta["mensaje"]
    assert "revisar esas pistas" not in respuesta["mensaje"]


def test_sinsonte_descripcion_nueva_no_hereda_otro_tamano():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Ave de 12 cm en el parque."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    assert reunir_pistas(DESCRIPCION_SINSONTE, historial) == DESCRIPCION_SINSONTE


@pytest.mark.parametrize("pista_intermedia", [None, "Tenía alas blancas."])
def test_cambio_de_familia_descarta_la_observacion_anterior(pista_intermedia):
    from app import reunir_pistas

    historial = [{"role": "user", "content": DESCRIPCION_SINSONTE},
                 {"role": "assistant", "content": "No puedo identificar el ave con la información disponible."}]
    if pista_intermedia:
        historial.extend([{"role": "user", "content": pista_intermedia},
                          {"role": "assistant", "content": OPCIONES_TENTATIVAS}])
    mensaje = "Alaudidae esta es la familia del ave, no me acuerdo mucho su forma"
    assert reunir_pistas(mensaje, historial) == mensaje


def test_aclaracion_no_reincorpora_observacion_de_otra_familia():
    from app import reunir_pistas

    historial = [{"role": "user", "content": DESCRIPCION_SINSONTE},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS},
                 {"role": "user", "content": "Tenía las alas blancas."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS},
                 {"role": "user", "content": "La familia es Alaudidae."},
                 {"role": "assistant", "content": "No puedo identificar el ave con la información disponible."}]
    texto = reunir_pistas("No recuerdo su color.", historial)
    assert "Alaudidae" in texto
    assert "No recuerdo su color" in texto
    assert "Mimidae" not in texto
    assert "blancas" not in texto
    assert "25 cm" not in texto


def test_misma_familia_conserva_las_pistas():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Familia Mimidae, ave gris de 25 cm."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    texto = reunir_pistas("Confirmo que es de la familia Mimidae.", historial)
    assert "gris de 25 cm" in texto


def test_familia_negada_no_inicia_otra_observacion():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Es un tiránido gris de 22 cm."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    assert "gris de 22 cm" in reunir_pistas("No pertenece a la familia Mimidae.", historial)


def test_solo_familia_sin_cobertura_responde_sobre_esa_familia(config, catalogo):
    def no_buscar(*args, **kwargs):
        pytest.fail("No debe buscar candidatas de una familia sin cobertura.")

    modelo = SimpleNamespace(chat_json=lambda *_: {"colores_principales": [], "dieta": [], "entorno": [], "vuelo": []})
    asistente = AsistenteAves(config, catalogo, SimpleNamespace(retrieve_relevant_chunks=no_buscar), modelo)
    r = asistente.responder("Alaudidae esta es la familia del ave, no me acuerdo mucho su forma")
    assert r["estado"] == "abstencion"
    assert r["diagnostico"]["taxonomia_consultada"] == {"familia": ["Alaudidae"]}
    assert r["diagnostico"]["atributos"]["rango_tamano_cm"] is None
    assert r["diagnostico"]["atributos"]["colores_principales"] == []
    assert "Alaudidae" in r["mensaje"]
    assert "Mimidae" not in r["mensaje"]
    assert "¿De qué color" not in r["mensaje"]


def test_rasgos_inventados_por_el_modelo(catalogo):
    inventados = {"colores_principales": ["marrón", "blanco"], "dieta": ["insectos"], "entorno": ["parque_jardin"]}
    atributos = extraer_atributos("Vi un Turdus fuscater en el parque.", 0.2, catalogo.vocabularios, inventados)
    assert atributos.colores_principales == []
    assert atributos.dieta == []
    assert atributos.entorno == ["parque_jardin"]


def test_verifica_cada_rasgo_y_normaliza_sinonimos(catalogo):
    atributos = extraer_atributos("Era gris claro, de alas pardas. Comía moras.", 0.2, catalogo.vocabularios, {
        "colores_principales": ["gris_claro", "pardo", "rojo"],
        "dieta": ["frutas", "insectos"],
    })
    assert atributos.colores_principales == ["gris", "marrón"]
    assert atributos.dieta == ["frutas"]


def test_cambio_de_observacion_con_nombres_comunes():
    from app import reunir_pistas

    historial = [{"role": "user", "content": "Vi un colibrí verde de 10 cm."},
                 {"role": "assistant", "content": OPCIONES_TENTATIVAS}]
    mensaje = "Ahora vi un tiránido amarillo."
    assert reunir_pistas(mensaje, historial) == mensaje


@pytest.mark.parametrize(("nombre", "texto", "esperado"), [
    ("Mayo", "vi un ave amarilla en mayo", False),
    ("Caravana", "paso una caravana de carros", False),
    ("Caravana", "creo que era una caravana", True),
    ("Gallinazo Común", "vi un gallinazo comun", True),
    ("Turdus fuscater", "vi un turdus fuscater", True),
])
def test_nombres_que_son_palabras_comunes(nombre, texto, esperado):
    assert menciona_nombre(nombre, texto) is esperado


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
