# Aves del Valle de Aburrá para identificación con RAG

El conjunto contiene **120 especies** con evidencia de presencia en el Área Metropolitana del Valle de Aburrá, Antioquia. En conjunto cubre Barbosa, Bello, Caldas, Copacabana, Envigado, Girardota, Itagüí, La Estrella, Medellín y Sabaneta. La selección deliberada incluye colibríes, palomas, tangaras, rapaces diurnas, búhos, aves de humedal y especies observadas en parques y jardines. Incluye 27 pares de parecido visual para probar la desambiguación.

## Archivos

| Archivo | Contenido |
| --- | --- |
| [processed/aves.jsonl](processed/aves.jsonl) y [processed/aves.csv](processed/aves.csv) | Los mismos 120 registros y 26 campos. JSONL usa UTF-8, listas JSON y `null`. CSV usa UTF-8 con BOM, listas serializadas como JSON y celdas vacías para nulos. |
| [processed/fichas_rag.jsonl](processed/fichas_rag.jsonl) | Una ficha en español por especie, con `id`, `nombre_cientifico` y `texto`. Cada ficha tiene entre 80 y 150 palabras. |
| [processed/evidencias.jsonl](processed/evidencias.jsonl) | Referencias por campo y especie. Cada referencia tiene fuente, URL, localizador dentro de la fuente y evidencia de hasta 20 palabras. |
| [fuentes.csv](fuentes.csv) y `raw/` | Bibliografía, licencia, fecha de consulta, enlaces oficiales de descarga y SHA-256 de los insumos usados. Los archivos descargados quedan en `raw/`, excluido de Git. |
| [guia_envigado.csv](guia_envigado.csv) y [plumaje_envigado.csv](plumaje_envigado.csv) | Transcripción factual revisable por página y observaciones visuales propias para reconstruir el dataset. |
| [vocabularios.json](vocabularios.json) | Categorías admitidas para colores, dieta, vuelo, entorno, UICN y confianza. |
| [validacion_muestra.csv](validacion_muestra.csv) | Un dato verificable para cada una de 15 especies elegidas al azar con semilla 20261111. La columna `correcto (sí/no)` queda disponible para revisión manual. |
| [especies_fuera_del_dataset.csv](especies_fuera_del_dataset.csv) | Diez aves de otras regiones biogeográficas. Se comprobó su exclusión de la selección, los registros locales usados y la lista ACO, incluidas coincidencias taxonómicas unívocas de BIRDBASE. |
| [reporte_validacion.json](reporte_validacion.json) | Cobertura por campo y entorno, controles de calidad y longitud de fichas. |

## Fuentes y licencias

| Fuente | Uso | Licencia o condición |
| --- | --- | --- |
| AMVA y Universidad Nacional, conectividad ecológica | Registros de presencia urbana en los diez municipios. | CC BY 4.0. [Ficha y cita completa en GBIF](https://doi.org/10.15472/5rp8fn) |
| Secretaría de Medio Ambiente de Medellín, Medellín y Alto de San Miguel v2.1 | Registros de casco urbano, corregimientos y reserva en Caldas. | CC BY-NC 4.0. [Ficha y cita completa en SiB](https://doi.org/10.15472/7raaek) |
| Instituto Humboldt y AMVA, caracterización de ocho humedales v1.2 | Registros de humedales. | CC BY-NC 4.0. [Ficha y cita completa en Humboldt](https://i2d.humboldt.org.co/resource?r=rrbb_animaliaplantae_amva_2022&v=1.2) |
| Sociedad Antioqueña de Ornitología, Restrepo Jaramillo y Ruiz Correa, *Guía de las aves de Envigado*, 2023 | Nombres, tamaños, gremios, hábitats, altitud, hábito y observaciones visuales de plumaje. | Derechos reservados. Las fotografías y el PDF se consultan en la copia oficial. Los datos estructurados llevan página y las observaciones visuales están redactadas en palabras propias. [Descarga oficial de la SAO](https://sao.org.co/guia-de-las-aves-del-municipio-de-envigado/) |
| Garizábal-Carmona y colaboradores, 2024 | Clasificación de relación con la urbanización, tabla 2. | CC BY. [Artículo](https://doi.org/10.3389/fevo.2024.1432340) |
| ACO y CCRO, lista de referencia de aves de Colombia v1.5 | Orden y familia. | CC BY 4.0. [Lista en GBIF](https://doi.org/10.15472/qhsz0p) |
| Şekercioğlu y colaboradores, BIRDBASE v2025.1 | Categoría global UICN de 2024, límites altitudinales de una especie y región biogeográfica para los casos fuera del dataset. | CC BY 4.0 para el archivo de datos. [Datos y cita en Figshare](https://doi.org/10.6084/m9.figshare.27051040) |

La reutilización de cada fuente conserva su atribución y sus condiciones. Los insumos con cláusula NC se emplearon para este proyecto universitario. Los archivos brutos se obtienen desde el enlace `descarga` de cada fila de `fuentes.csv`. Los registros SiB conservan el identificador original `occurrenceID` en las evidencias. [Política de uso de SiB Colombia](https://biodiversidad.co/terminos-y-condiciones/politica-de-uso)

## Variables

| Campo | Tipo y significado |
| --- | --- |
| `id`, `nombre_comun`, `nombre_cientifico` | Textos. El ID deriva del binomio. El nombre común usa el índice regional de la guía. |
| `orden`, `familia` | Textos. Clasificación de la lista ACO en la versión citada. |
| `longitud_min_cm`, `longitud_max_cm` | Números en centímetros. Se toma el tamaño de la guía como aproximación de la longitud total. Un valor puntual se repite en ambos campos. Con dos valores se conserva el intervalo entre ambos. |
| `colores_principales`, `descripcion_plumaje` | Lista controlada y texto. Observaciones visuales de las fotografías de la guía. Se identifica el sexo cuando está indicado y es relevante para el rasgo descrito. |
| `dieta`, `dieta_detalle` | Lista controlada y texto. Traducción de los gremios de la guía a alimentos o categorías generales. |
| `vuelo`, `vocalizacion` | Lista controlada y texto, respectivamente. Se requiere una descripción explícita de la maniobra o del sonido. |
| `comportamiento_otro` | Texto. Horario de actividad y, donde hay clasificación, respuesta a la urbanización según el estudio local. |
| `entorno` | Lista controlada. Hábitats indicados por la guía, con observaciones locales específicas como complemento. |
| `altitud_min_m`, `altitud_max_m` | Enteros en metros sobre el nivel del mar. Límites publicados para la especie. |
| `departamentos_o_zonas` | Lista de municipios antioqueños donde el cruce encontró registros de presencia. |
| `endemica_colombia`, `estado_uicn` | Booleano y código, con nulos cuando falta el dato. Endemismo según la distribución documentada y categoría global UICN según BIRDBASE. |
| `especies_similares` | Lista de IDs internos para pruebas de desambiguación. Los pares resultan de comparar visualmente las fichas. |
| `fuente_id`, `fuente_pagina_o_url`, `evidencia_corta` | Cita principal por especie. El archivo de evidencias detalla la procedencia de cada campo. |
| `confianza`, `campos_inferidos` | Categoría de confianza y lista de campos transformados o inferidos. Se asignó confianza media por el uso de OCR y observaciones visuales. |

## Reproducción y controles

Desde la raíz del repositorio, con Python 3.10 o posterior:

```powershell
python -m pip install -r scripts/requisitos.txt
python scripts/construir_dataset.py --descargar
```

La reconstrucción usa las transcripciones versionadas. Para volver a extraer los campos de las fichas gráficas en Windows con OCR en español de España instalado, ejecuta primero la descarga y luego:

```powershell
python scripts/extraer_guia.py --preparar-ocr
powershell.exe -NoProfile -File scripts/ocr_envigado.ps1
python scripts/extraer_guia.py
python scripts/construir_dataset.py
```

1. Se filtran los archivos Darwin Core por clase Aves, nivel de especie, nombre binomial, Antioquia, municipio de interés e identificación sin calificador de incertidumbre. Se excluyen registros marcados como ausentes. Los datos se cruzan por binomio con la guía, la lista ACO y la fila unívoca de BIRDBASE.
2. Se coteja el nombre en el encabezado de cada ficha gráfica con el índice, se transcriben los campos y se registran las observaciones visuales. Se corrigieron cuatro referencias desplazadas en el índice y las lecturas ambiguas del OCR. La extracción del índice también separa las filas que el rótulo lateral del PDF había unido en tres nombres comunes del conjunto. El extractor conserva las correcciones verificadas.
3. Se normalizan los gremios y hábitats. Se añade `humedal` cuando la guía indica hábitat acuático y existe un registro del estudio de humedales. Se añade `bosque_humedo` cuando la guía indica bosque y un registro local especifica un bosque húmedo. `parque_jardin` requiere una localidad de parque o jardín identificable.
4. Se valida cantidad de especies, unicidad, rangos, vocabulario, enlaces de similitud, presencia local, trazabilidad y extensión de fichas. El CSV de muestra conserva las marcas manuales al reconstruir cuando el dato y su referencia coinciden.

## Límites del conjunto

Los archivos de `processed/` conservan el catálogo base. `complementos.json` añade rasgos verificados al cargar `Catalogo`: amplía los colores, la descripción indexada y las evidencias, con una fuente independiente. Su contenido forma parte de la huella del índice, que se reconstruye cuando cambia. No sustituye los datos de presencia local ni las medidas de Envigado. El primer complemento corresponde a los tonos grises y brillos metálicos de *Zenaida auriculata*, documentados en la [Cartilla del SAG de Chile, edición 2018, p. 34](https://www.sag.gob.cl/sites/default/files/cartilla_para_cazadores_2018.pdf#page=35). Es un complemento morfológico descrito en Chile, no evidencia de distribución en el Valle de Aburrá. Las citas adicionales se muestran en las respuestas; las transcripciones originales siguen atribuidas a sus propias fuentes.

- La disponibilidad de fichas de Envigado y la intensidad del muestreo en Medellín influyen en la selección. La cobertura municipal refleja observaciones disponibles y la muestra de 120 especies no es un inventario exhaustivo.
- La guía denomina la medida `tamaño en centímetros` y no describe un protocolo de longitud total. Su interpretación se marca en `campos_inferidos`. Los intervalos altitudinales publicados pueden diferir de las elevaciones individuales. Para *Quiscalus mexicanus* la guía indica 0–200 m y, por ejemplo, el registro AMVA:CONECTIVIDAD_AVES:02688 indica 1310 m en Barbosa. Se usaron los límites normales de BIRDBASE, 0–2300 m. Las elevaciones individuales de los registros presentan valores atípicos y se excluyeron del cálculo de los intervalos.
- Las fotos muestran ejemplares concretos. Los colores pueden variar según edad, sexo, iluminación y población. Los pares propuestos representan parecido visual para pruebas y carecen de una estimación publicada de frecuencia de confusión.
- `vuelo` y `vocalizacion` quedaron nulos porque las fuentes usadas no describen el tipo de vuelo ni las vocalizaciones de las especies seleccionadas. Dos categorías UICN están ausentes en el corte de BIRDBASE. La cobertura de `endemica_colombia` depende de que la fuente indique una categoría que permita decidir el valor.
