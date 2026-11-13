# Envía consultas de texto y embeddings a NVIDIA y traduce los errores.
"""Cliente de NVIDIA NIM para embeddings y chat."""

import json
from openai import APIConnectionError, APIStatusError, OpenAI

from avesco.configuracion import NVIDIA_URL


class ErrorModelo(RuntimeError):
    """Error apto para mostrar al usuario, sin valores de credenciales."""


class ClienteNvidia:
    def __init__(self, config):
        # Conserva las dependencias que el objeto reutiliza durante el flujo.
        # Comparte el cliente y sus límites de espera entre las llamadas.
        self.client = OpenAI(base_url=NVIDIA_URL, api_key=config.clave_nvidia, timeout=45, max_retries=1)
        self.modelo_chat = config.modelo_chat
        self.identificador = config.modelo_embed

    def _llamar(self, operacion, **argumentos):
        # Traduce errores de la API a mensajes que se pueden mostrar.
        try:
            return operacion(**argumentos)
        except APIConnectionError as error:
            raise ErrorModelo("No se pudo conectar con NVIDIA. Revisa tu conexión e inténtalo otra vez.") from error
        except APIStatusError as error:
            codigo = error.status_code
            # Distingue autenticación, cuota y modelo no disponible.
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
        # Devuelve un vector por entrada y conserva el orden del lote.
        respuesta = self._llamar(
            self.client.embeddings.create, input=textos, model=self.identificador,
            encoding_format="float", extra_body={"input_type": tipo},
        )
        return [fila.embedding for fila in sorted(respuesta.data, key=lambda fila: fila.index)]

    def chat_json(self, instrucciones, entrada):
        """Usa el patrón de mensajes del notebook y devuelve un objeto validable."""
        # Separa instrucciones del sistema y datos de la consulta.
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
        except (json.JSONDecodeError, IndexError) as error:
            raise ErrorModelo("NVIDIA devolvió una respuesta que no se pudo leer. Inténtalo otra vez.") from error
        if not isinstance(valor, dict):
            raise ErrorModelo("NVIDIA devolvió una respuesta inesperada. Inténtalo otra vez.")
        return valor

    def chat_texto(self, instrucciones, entrada, max_tokens=260):
        """Redacta texto libre a partir de datos suministrados. Devuelve cadena vacía si no hay contenido."""
        # Separa instrucciones del sistema y datos de la consulta.
        messages = [
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": json.dumps(entrada, ensure_ascii=False)},
        ]
        respuesta = self._llamar(
            self.client.chat.completions.create, model=self.modelo_chat, messages=messages,
            max_tokens=max_tokens, temperature=0.2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        try:
            return (respuesta.choices[0].message.content or "").strip()
        except IndexError:
            return ""
