"""Crea y consulta el índice Qdrant persistente, sin servidor independiente."""

import argparse
import hashlib
import math
import uuid

from qdrant_client import QdrantClient, models

from avesco.configuracion import CACHE, Configuracion, opcion_modo
from avesco.datos import Catalogo
from avesco.modelos import ClienteNvidia, EmbeddingsLocales


class IndiceAves:
    def __init__(self, catalogo, modelo, carpeta):
        self.catalogo = catalogo
        self.modelo = modelo
        self.huella = hashlib.sha256(f"{catalogo.huella_fichas}:{modelo.identificador}".encode()).hexdigest()
        self.coleccion = f"aves_{self.huella}"
        self.client = QdrantClient(path=str(carpeta))
        self.ids = {id_ave: str(uuid.uuid5(uuid.NAMESPACE_URL, f"avesco/{id_ave}")) for id_ave in catalogo.aves}

    def asegurar(self):
        """Reutiliza el índice si coinciden fichas, modelo y cantidad de puntos."""
        existe = self.client.collection_exists(self.coleccion)
        if existe and self.client.count(self.coleccion, exact=True).count == len(self.ids):
            return False
        print(f"Indexando {len(self.ids)} fichas con {self.modelo.identificador}...", flush=True)
        fichas = list(self.catalogo.fichas.values())
        puntos = []
        dimension = None
        for inicio in range(0, len(fichas), 16):
            lote = fichas[inicio:inicio + 16]
            vectores = self.modelo.embeddings([f["texto"] for f in lote], "passage")
            if len(vectores) != len(lote):
                raise ValueError("El modelo devolvió una cantidad incorrecta de vectores.")
            for ficha, vector in zip(lote, vectores, strict=True):
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
        if not ids_elegibles:
            return []
        (vector,) = self.modelo.embeddings([texto], "query")
        resultado = self.client.query_points(
            self.coleccion, query=vector, limit=min(top_k, len(ids_elegibles)),
            query_filter=models.Filter(must=[models.HasIdCondition(
                has_id=[self.ids[id_ave] for id_ave in ids_elegibles],
            )]),
            with_payload=True,
        )
        return [(p.payload["id_ave"], p.score) for p in resultado.points]

    def cerrar(self):
        self.client.close()


def crear_indice(config, catalogo):
    modelo = ClienteNvidia(config) if config.modo == "nvidia" else EmbeddingsLocales()
    indice = IndiceAves(catalogo, modelo, CACHE / f"qdrant_{config.modo}")
    try:
        creado = indice.asegurar()
    except Exception:
        indice.cerrar()
        raise
    print("Índice actualizado." if creado else "Índice existente reutilizado.", flush=True)
    return indice


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    opcion_modo(parser)
    args = parser.parse_args()
    crear_indice(Configuracion.cargar(args.modo), Catalogo.cargar()).cerrar()
