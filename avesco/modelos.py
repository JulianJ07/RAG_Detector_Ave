"""Clientes preentrenados para embeddings y chat. El modo local usa CPU."""

import json
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
from openai import APIConnectionError, APIStatusError, OpenAI

from avesco.configuracion import CACHE, NVIDIA_URL

REVISION_E5 = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class ErrorModelo(RuntimeError):
    """Error apto para mostrar al usuario, sin valores de credenciales."""


class ClienteNvidia:
    def __init__(self, config):
        self.client = OpenAI(base_url=NVIDIA_URL, api_key=config.clave_nvidia, timeout=45, max_retries=1)
        self.modelo_chat = config.modelo_chat
        self.identificador = config.modelo_embed

    def _llamar(self, operacion, **argumentos):
        try:
            return operacion(**argumentos)
        except APIConnectionError as error:
            raise ErrorModelo("No se pudo conectar con NVIDIA. Revisa tu conexión e inténtalo otra vez.") from error
        except APIStatusError as error:
            codigo = error.status_code
            if codigo in (401, 403):
                detalle = "NVIDIA rechazó la autenticación. Revisa la clave y el acceso al modelo."
            elif codigo == 429:
                detalle = "NVIDIA limitó la solicitud. Revisa tu cuota o inténtalo en un momento."
            elif codigo == 404:
                detalle = "NVIDIA no encontró el modelo configurado. Revisa los IDs de los modelos."
            else:
                detalle = f"NVIDIA devolvió un error HTTP {codigo}."
            raise ErrorModelo(detalle) from error

    def embeddings(self, textos, tipo):
        respuesta = self._llamar(
            self.client.embeddings.create, input=textos, model=self.identificador,
            encoding_format="float", extra_body={"input_type": tipo},
        )
        return [fila.embedding for fila in sorted(respuesta.data, key=lambda fila: fila.index)]

    def chat_json(self, instrucciones, entrada):
        """Usa el patrón de mensajes del notebook y devuelve un objeto validable."""
        messages = [
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": json.dumps(entrada, ensure_ascii=False)},
        ]
        respuesta = self._llamar(
            self.client.chat.completions.create, model=self.modelo_chat, messages=messages,
            max_tokens=384, temperature=0, response_format={"type": "json_object"},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        try:
            valor = json.loads(respuesta.choices[0].message.content or "")
            return valor if isinstance(valor, dict) else None
        except (json.JSONDecodeError, IndexError):
            return None


class EmbeddingsLocales:
    """E5 multilingüe cuantizado con prefijos query/passage y promedio enmascarado."""

    identificador = f"intfloat/multilingual-e5-small@{REVISION_E5}"

    def __init__(self, carpeta=CACHE / "modelo_e5"):
        self.carpeta = carpeta
        self.sesion = None
        self.tokenizador = None

    def _descargar(self, nombre, remoto):
        destino = self.carpeta / nombre
        if destino.is_file():
            return destino
        self.carpeta.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/intfloat/multilingual-e5-small/resolve/{REVISION_E5}/{remoto}"
        print(f"Descargando {nombre} para el modo local (solo la primera vez)...", flush=True)
        with tempfile.TemporaryDirectory(dir=self.carpeta) as carpeta:
            temporal = Path(carpeta) / nombre
            urlretrieve(url, temporal)
            temporal.replace(destino)
        return destino

    def _cargar(self):
        from onnxruntime import InferenceSession, SessionOptions
        from tokenizers import Tokenizer

        opciones = SessionOptions()
        opciones.intra_op_num_threads = 4
        modelo = self._descargar("model.onnx", "onnx/model_qint8_avx512_vnni.onnx")
        vocab = self._descargar("tokenizer.json", "tokenizer.json")
        tokenizador = Tokenizer.from_file(str(vocab))
        tokenizador.enable_truncation(max_length=512)
        tokenizador.enable_padding(pad_id=1, pad_token="<pad>")
        self.sesion = InferenceSession(str(modelo), opciones, providers=["CPUExecutionProvider"])
        self.tokenizador = tokenizador

    def embeddings(self, textos, tipo):
        if self.sesion is None:
            self._cargar()
        tokens = self.tokenizador.encode_batch([f"{tipo}: {texto}" for texto in textos])
        mascara = np.asarray([t.attention_mask for t in tokens], dtype=np.int64)
        entrada = {
            "input_ids": np.asarray([t.ids for t in tokens], dtype=np.int64),
            "attention_mask": mascara,
            "token_type_ids": np.asarray([t.type_ids for t in tokens], dtype=np.int64),
        }
        entrada = {i.name: entrada[i.name] for i in self.sesion.get_inputs()}
        vectores_token = self.sesion.run(["last_hidden_state"], entrada)[0]
        vectores = (vectores_token * mascara[..., None]).sum(axis=1) / mascara.sum(axis=1, keepdims=True)
        vectores /= np.linalg.norm(vectores, axis=1, keepdims=True)
        return vectores.tolist()
