# Prueba las métricas y los diagnósticos sin consultar la API.
from copy import deepcopy

import pytest

from avesco.configuracion import RAIZ
from avesco.datos import Catalogo
from avesco.evaluacion import revisar, resumir
from evaluar_robustez import cargar_casos


@pytest.fixture(scope="module")
def catalogo():
    # Carga el mismo catálogo para las comprobaciones de este módulo.
    return Catalogo.cargar()


def respuesta_para(catalogo, ids, estado="coincidencias"):
    # Construye una respuesta controlada para probar el evaluador.
    return {"estado": estado, "diagnostico": {"atributos": {"rango_tamano_cm": [18, 22], "vuelo": []}},
            "aves": [{"id": i, "citas": catalogo.citas(i, ["nombre_comun"])} for i in ids]}


@pytest.mark.parametrize(("traza", "etapa"), [
    ({"ids_elegibles": []}, "filtros"),
    ({"ids_elegibles": ["tyrannus_melancholicus"], "recuperadas": []}, "recuperacion"),
    ({"ids_elegibles": ["tyrannus_melancholicus"], "recuperadas": [{"id": "tyrannus_melancholicus"}]}, "reglas_de_preseleccion"),
    ({"ids_elegibles": ["tyrannus_melancholicus"], "recuperadas": [{"id": "tyrannus_melancholicus"}],
      "preseleccion": ["tyrannus_melancholicus"]}, "seleccion_nvidia"),
])
def test_localiza_perdida_de_candidata(catalogo, traza, etapa):
    # Comprueba localiza perdida de candidata.
    r = revisar({"esperado": "tyrannus_melancholicus"}, respuesta_para(catalogo, []), catalogo, traza)
    assert etapa in r["fallos"]
    assert not r["aprobado"]


def test_top3_no_disfraza_error_de_orden(catalogo):
    # Comprueba top3 no disfraza error de orden.
    esperado = "tyrannus_melancholicus"
    traza = {"ids_elegibles": [esperado], "recuperadas": [{"id": esperado}], "preseleccion": [esperado]}
    r = revisar({"esperado": esperado}, respuesta_para(catalogo, ["pitangus_sulphuratus", esperado]), catalogo, traza)
    assert r["top3"] and not r["top1"]
    assert "orden_de_respuesta" in r["fallos"]


def test_atributo_inventado_falla_aunque_acierte_especie(catalogo):
    # Comprueba atributo inventado falla aunque acierte especie.
    caso = {"esperado": "tyrannus_melancholicus", "atributos_esperados": {"vuelo": []}}
    respuesta = respuesta_para(catalogo, [caso["esperado"]])
    respuesta["diagnostico"]["atributos"]["vuelo"] = ["planeo"]
    r = revisar(caso, respuesta, catalogo, {})
    assert r["top1"] and "interpretacion" in r["fallos"]


def test_cita_inventada_no_aprueba(catalogo):
    # Comprueba cita inventada no aprueba.
    caso = {"esperado": "tyrannus_melancholicus"}
    respuesta = deepcopy(respuesta_para(catalogo, [caso["esperado"]]))
    respuesta["aves"][0]["citas"][0]["url"] = "https://example.com/fuente-inventada"
    assert "citas" in revisar(caso, respuesta, catalogo, {})["fallos"]


def test_opciones_tentativas_no_son_identificacion_firme(catalogo):
    # Comprueba opciones tentativas no son identificacion firme.
    caso = {"esperado": None, "estados_permitidos": ["abstencion", "tentativas"]}
    respuesta = respuesta_para(catalogo, ["tyrannus_melancholicus"], "tentativas")
    assert revisar(caso, respuesta, catalogo, {})["aprobado"]
    respuesta["estado"] = "coincidencias"
    assert "estado_o_abstencion" in revisar(caso, respuesta, catalogo, {})["fallos"]


def test_reserva_no_se_ejecuta_por_defecto(catalogo):
    # Comprueba reserva no se ejecuta por defecto.
    casos = cargar_casos(RAIZ / "evaluacion/casos_robustez.json", ["regresion", "desarrollo"], catalogo)
    assert len(casos) == 26
    assert all(c["grupo"] != "reserva" for c in casos)


def test_resumen_separa_positivas_y_negativas():
    # Comprueba resumen separa positivas y negativas.
    filas = [{"esperado": "ave", "revision": {"top1": False, "top3": True, "aprobado": False, "fallos": ["orden_de_respuesta"]}},
             {"esperado": None, "revision": {"estado_valido": True, "aprobado": True, "fallos": []}}]
    r = resumir(filas)
    assert (r["top1"], r["top3"], r["positivas"]) == (0, 1, 1)
    assert (r["negativas_con_estado_correcto"], r["negativas"]) == (1, 1)
