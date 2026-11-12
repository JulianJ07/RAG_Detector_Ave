# Cómo evaluar y ajustar AvesCO

`tests/` comprueba el código sin llamadas reales a NVIDIA. `evaluar_robustez.py` comprueba el sistema completo con la API y registra en qué etapa aparece cada fallo. Estas pruebas no entrenan ni modifican los pesos de NVIDIA.

## Casos y etiquetas

`casos_robustez.json` incluye 26 casos: 10 de regresión (ejemplos originales y fallos ya conocidos), 12 de desarrollo y 4 de reserva. Los casos sintéticos proceden del propio catálogo; sus etiquetas requieren revisión humana y no son observaciones independientes. La reserva tampoco constituye una validación de campo. Los dos casos de torcaza cubren una comparación con otra especie y un historial sintético; el historial real del reporte no está disponible.

Para añadir un caso, conserva la descripción exacta, indica `id`, `grupo`, `origen`, `consulta` y `esperado` (ID del catálogo o `null` si no debería identificar). Documenta quién comprobó la especie y con qué fuente. Usa `historial` para reproducir una conversación, sin datos privados ni credenciales.

`atributos_esperados` comprueba los extremos del tamaño y exige que las listas incluyan los elementos indicados. Una lista vacía exige ausencia de ese atributo. `atributos_prohibidos` detecta, por ejemplo, un color negado o el color de la comida. `estados_permitidos` permite distinguir una identificación firme de opciones tentativas. Por defecto se exige `coincidencias` en positivos y `abstencion` en negativos.

## Ejecutar

Desde la raíz del repositorio, con la aplicación detenida para liberar el índice Qdrant:

```powershell
.\.venv\Scripts\python.exe evaluar_robustez.py --grupos regresion desarrollo --salida ..\outputs\baseline_robustez.json
```

Se guardan un JSON completo y un informe Markdown. Se actualizan tras cada caso, por lo que los resultados anteriores sobreviven si se interrumpe la ejecución. No se guardan claves de API. Las descripciones se envían a NVIDIA; evita información privada en los casos.

Para observar variación entre respuestas del servicio, ejecuta `--repeticiones 3` sobre los mismos casos. Los resultados cuentan ejecuciones, no observaciones independientes. No cambies umbrales durante esa comparación.

```powershell
.\.venv\Scripts\python.exe evaluar_robustez.py --grupos desarrollo --repeticiones 3 --salida ..\outputs\estabilidad.json
```

La reserva se ejecuta solo cuando se pide explícitamente con `--grupos reserva`. Mantén sus resultados fuera del proceso de ajuste y amplíala con observaciones reales verificadas por alguien con conocimiento de aves.

## Leer los errores

| Señal | Qué revisar |
|---|---|
| Atributos incorrectos, inventados o negados | Instrucciones de extracción, normalización y contexto de la conversación |
| La especie esperada no queda entre IDs elegibles | Lectura de medidas, familia, orden y datos de la ficha |
| Era elegible, pero no se recuperó | Índice, embeddings y consulta enviada al buscador |
| Se recuperó, pero no llegó a preselección | Umbrales, límites y reglas de compatibilidad |
| Estaba en preselección, pero no en la respuesta | Selección del modelo NVIDIA |
| Aparece segunda o tercera | Orden de candidatas; revisar si la descripción distingue realmente las especies |
| Respuesta firme con pistas insuficientes | Abstención y preguntas aclaratorias |
| Cita ausente o ajena a la ficha | Construcción de la respuesta y procedencia de fuentes |

La clasificación localiza síntomas observables y puede señalar varias etapas. No demuestra por sí sola que el modelo sea la causa. La pertenencia de una cita al catálogo tampoco comprueba que respalde semánticamente cada afirmación.

## Ciclo de mejora

1. Guarda una línea base con modelos, código, datos y umbral identificados en los metadatos.
2. Revisa primero los fallos de desarrollo y la calidad de sus etiquetas. Una ficha incompleta puede impedir una identificación correcta aunque el código funcione.
3. Cambia una sola cosa y repite desarrollo. Comprueba después las regresiones.
4. Compara primera posición, primeras tres, abstención, atributos inventados y citas. No uses únicamente un porcentaje global.
5. Si un caso motivó un cambio, pásalo a regresión y añade nuevos casos de desarrollo. Valida al final con ejemplos que no usaste para ajustar.
