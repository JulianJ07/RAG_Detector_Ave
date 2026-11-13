# Guarda los embeddings en Qdrant y recupera fichas entre los IDs elegibles.
"""Crea y consulta el índice Qdrant persistente, sin servidor independiente."""

import argparse
import hashlib
import math
import uuid

from qdrant_client import QdrantClient, models

from avesco.configuracion import CACHE, Configuracion
from avesco.datos import Catalogo
from avesco.modelos import ClienteNvidia


class IndiceAves:
    def __init__(self, catalogo, modelo, carpeta):
        # Conserva las dependencias que el objeto reutiliza durante el flujo.
        self.catalogo = catalogo
        self.modelo = modelo
        # La huella cambia cuando cambian las fichas o el modelo de embeddings.
        self.huella = hashlib.sha256(f"{catalogo.huella_fichas}:{modelo.identificador}".encode()).hexdigest()
        self.coleccion = f"aves_{self.huella}"
        self.client = QdrantClient(path=str(carpeta))
        # Deriva IDs estables para que el mismo registro se pueda recuperar al reabrir.
        self.ids = {id_ave: str(uuid.uuid5(uuid.NAMESPACE_URL, f"avesco/{id_ave}")) for id_ave in catalogo.aves}

    def asegurar(self):
        """Reutiliza el índice si coinciden fichas, modelo y cantidad de puntos."""
        # Verifica que la colección existente tenga todas las fichas esperadas.
        existe = self.client.collection_exists(self.coleccion)
        if existe and self.client.count(self.coleccion, exact=True).count == len(self.ids):
            return False
        print(f"Indexando {len(self.ids)} fichas con {self.modelo.identificador}...", flush=True)
        fichas = list(self.catalogo.fichas.values())
        puntos = []
        # Exige que todos los vectores tengan la misma cantidad de componentes.
        dimension = None
        # Envía grupos de fichas para evitar una solicitud por cada especie.
        for inicio in range(0, len(fichas), 16):
            lote = fichas[inicio:inicio + 16]
            vectores = self.modelo.embeddings([f["texto"] for f in lote], "passage")
            # Evita asociar una ficha con el vector de otra si el lote es incompleto.
            if len(vectores) != len(lote):
                raise ValueError("El modelo devolvió una cantidad incorrecta de vectores.")
            for ficha, vector in zip(lote, vectores, strict=True):
                # Exige que todos los vectores tengan la misma cantidad de componentes.
                dimension = dimension or len(vector)
                if not dimension or len(vector) != dimension or not all(math.isfinite(v) for v in vector) or not any(vector):
                    raise ValueError("El modelo devolvió un vector inválido.")
                id_ave = ficha["id"]
                puntos.append(models.PointStruct(
                    id=self.ids[id_ave], vector=vector, payload={"id_ave": id_ave},
                ))
        # Calcula todos los embeddings antes de tocar el índice persistente.
        if not existe:
            self.client.create_collection(self.coleccion, vectors_config=models.VectorParams(
                size=dimension, distance=models.Distance.COSINE,
            ))
        self.client.upsert(self.coleccion, puntos, wait=True)
        return True

    def retrieve_relevant_chunks(self, texto, ids_elegibles, top_k=12):
        # Devuelve pares de ID y similitud solo para las especies permitidas.
        if not ids_elegibles:
            return []
        # Marca el texto como consulta para el modelo de embeddings.
        (vector,) = self.modelo.embeddings([texto], "query")
        # Aplica el filtro de IDs dentro de la búsqueda por coseno.
        resultado = self.client.query_points(
            self.coleccion, query=vector, limit=min(top_k, len(ids_elegibles)),
            query_filter=models.Filter(must=[models.HasIdCondition(
                has_id=[self.ids[id_ave] for id_ave in ids_elegibles],
            )]),
            with_payload=True,
        )
        return [(p.payload["id_ave"], p.score) for p in resultado.points]

    def cerrar(self):
        # Libera el índice para que otro proceso pueda abrir su carpeta.
        self.client.close()


def crear_indice(config, catalogo):
    # Abre o reconstruye el índice con el modelo configurado.
    modelo = ClienteNvidia(config)
    try:
        indice = IndiceAves(catalogo, modelo, CACHE / "qdrant_nvidia")
    except RuntimeError as error:
        if "already accessed" not in str(error):
            raise
        raise SystemExit(
            "Otro proceso está usando el índice en .avesco/qdrant_nvidia. "
            "Cierra la app (app.py) antes de evaluar o reconstruir el índice."
        ) from None
    try:
        creado = indice.asegurar()
    except Exception:
        indice.cerrar()
        raise
    print("Índice actualizado." if creado else "Índice existente reutilizado.", flush=True)
    return indice


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    crear_indice(Configuracion.cargar(), Catalogo.cargar()).cerrar()
