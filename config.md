# Configuración del proyecto

Todos los parámetros del pipeline viven en el bloque YAML de abajo.
`src/config.py` lo lee de ahí (busca el primer fence ```yaml``` del archivo).
Ningún módulo en `src/` debe tener rutas, departamentos, umbrales o listas
de categorías hardcodeadas — cambiar un parámetro aquí no requiere tocar
código.

```yaml
departamentos:
  costa: PIURA
  andino: CUSCO
  amazonico: LORETO

bbox_peru:
  lon_min: -81.4
  lon_max: -68.6
  lat_min: -18.4
  lat_max: -0.04

resolutivo:
  categorias: [II-1, II-2, II-E, III-1, III-2, III-E]

routing:
  engine: osrm
  car_port: 5000
  foot_port: 5001
  max_demand_points: 5000
  osm_extract: data/raw/osm/peru-latest.osm.pbf
  snap_confiable_max_m: 5000  # snapping mayor a esto = "cerca de ninguna via mapeada", ver hallazgo Loreto en config.md

coverage_bands_min: [30, 60, 120]

paths:
  raw: data/raw
  processed: data/processed
  outputs: data/outputs
  logs: logs

fuentes:
  renipress_url: https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_31-08-2026.csv
  admin_boundaries_url: https://data.humdata.org/dataset/54fc7f4d-f4c0-4892-91f6-2fe7c1ecf363/resource/63647792-0951-40d2-a30e-4a0e60f7a176/download/per_admin_boundaries.geojson.zip
  centros_poblados_dispersos_query_url: https://www.idep.gob.pe/geoportal/rest/services/DATOS_GEOESPACIALES/CENTROS_POBLADOS_DISPERSOS/MapServer/0/query
  capitales_distritales_query_url: https://www.idep.gob.pe/geoportal/rest/services/DATOS_GEOESPACIALES/CENTROS_POBLADOS/MapServer/3/query
  poblacion_distrital_url: https://cdn.www.gob.pe/uploads/document/file/8261096/6894980-peru-poblacion-total-proyectada-al-30-de-junio-de-cada-ano-segun-departamento-provincia-y-distrito-2018-2026.xlsx
  poblacion_distrital_anio: 2026
```

## Departamentos analizados

Exactamente tres, uno por macro-región (ver YAML arriba: `departamentos`).

| Rol | Departamento |
|---|---|
| Costa | Piura |
| Andino | Cusco |
| Amazónico | Loreto |

## Definición de "resolutivo"

- Estado operativo: `ESTADO == "ACTIVO"` (verificado en Fase 1b: el campo
  **sí** es un vocabulario controlado y limpio — 7 valores únicos, sin
  typos: `ACTIVO`, `BAJA DEFINITIVA`, `BAJA DEFINITIVA DE OFICIO`,
  `BAJA PROVISIONAL`, `BAJA PROVISIONAL DE OFICIO`,
  `CIERRE TEMPORAL DE OFICIO`, `CIERRE TEMPORAL DE PARTE`. No hace falta
  normalización difusa, solo la decisión de que únicamente `ACTIVO` cuenta
  como operativo — el resto son variantes de cierre)
- Categoría (normalizada): ver `resolutivo.categorias` en el YAML. RENIPRESS
  usa el valor literal `"0"` para establecimientos a los que no aplica la
  escala I-1..III-E (servicios médicos de apoyo, sin internamiento, etc.)
  — se normaliza a `SIN_CATEGORIA` en `validation.py`.
- Todo lo demás (`I-1`..`I-4`, `SIN_CATEGORIA`) se mantiene en el dataset
  pero se excluye del cómputo de facility más cercana.

## Reglas de validación (Fase 1b — aplicadas sobre 4,512 establecimientos
## de Piura/Cusco/Loreto, de 36,004 a nivel nacional)

Resultados completos en `logs/data_quality_report.json` (se regenera con
`python src/validation.py`). Resumen:

1. **Coordenadas nulas o cero** (`NORTE`/`ESTE` nulos, o ambos con
   `|valor| < 0.001°`): **1,309 registros (29%)**. Se mantienen en el
   dataset (`coords_utilizables=False`) y se excluyen del ruteo en Fase 2.
   Nota: `NORTE`/`ESTE` pese al nombre (que sugiere UTM) son coordenadas
   decimales WGS84 — `NORTE`=latitud, `ESTE`=longitud, verificado contra
   el rango de Perú.
2. **Coordenadas fuera del bounding box** (presentes pero no-cero): **0**.
3. **Lat/lon posiblemente invertidas**: **0** — de las flageadas en la
   regla 2, ninguna encaja en Perú al invertir lat/lon (regla 2 dio 0, así
   que no había candidatas).
4. **Punto fuera del polígono de su distrito declarado (UBIGEO)**:
   **499 de 3,203 verificables (15.6%)**. Verificado que no es un bug: 498
   de esos 499 caen dentro de un distrito *real* distinto al declarado
   (mayormente distritos contiguos dentro de la misma ciudad — p. ej.
   Cusco/San Sebastián/Wanchaq, Piura/Castilla/Veintiséis de Octubre —
   consistente con imprecisión de geocodificación en zonas urbanas densas
   donde el límite distrital cruza la propia manzana). Se mantienen con la
   bandera activada, no se excluyen automáticamente.
5. **Códigos de establecimiento duplicados** (`COD_IPRESS`): **0**
   (tampoco hay duplicados a nivel nacional).
6. **Problemas de encoding** (carácter de reemplazo U+FFFD en campos de
   texto): **0** en RENIPRESS para estos 3 departamentos. Sí se encontró
   este problema en los límites administrativos (`"Perú"` → `"Per�"` en
   `adm0_name`), documentado arriba.

## Fase 2 — Routing (`src/routing.py`)

Servidor OSRM local (Docker, ver README.md), motor `car`, algoritmo MLD.
Demanda = centros poblados dispersos + puntos de demanda urbana (Fase 1a),
filtrados a población > 0. Oferta = RENIPRESS resolutivo + activo + con
coordenadas utilizables (Fase 1b). Matriz completa origen×facility vía
`/table`, en lotes de 150 puntos de demanda para no exceder límites de URL,
cacheada en `data/processed/routing_cache/matrix_<depto>.parquet` (**sí se
versiona en git** — es un deliverable explícito del enunciado). Cada par
(demanda, facility) trae `snap_confiable` (ambos extremos snappearon a
`routing.snap_confiable_max_m` o menos de una vía mapeada). Reporte por
departamento en `logs/routing_report_<depto>.json`.

**Resultados (3 departamentos, 269,462 pares en total):**

| Depto | Demanda × Facilities | Pares sin ruta | Demanda sin ninguna ruta | Coincide recta=red | Factor desvío | Snap demanda (mediana / máx.) |
|---|---|---:|---:|---:|---:|---|
| Piura | 1,722 × 32 = 55,104 | 0 | 0 | 50.3% | 1.87x | 49m / 19.5km |
| Cusco | 7,271 × 26 = 189,046 | 0 | 0 | 75.2% | 1.90x | 90m / 65.3km |
| Loreto | 1,808 × 14 = 25,312 | 2,268 (9.0%) | **162 (9.0%)** | 55.7% | 1.18x | 43.3km / 414.5km |

- **Piura y Cusco**: red bien conectada (0 pares sin ruta). En ambas, la
  facility resolutiva más cercana en línea recta **no** es la más rápida
  por carretera en la mitad o más de los casos — el hallazgo central de
  Fase 2 que pide discutir el enunciado.
- **Loreto — hallazgo mayor, no un bug:** la red vial mapeada en OSM
  prácticamente no existe fuera de Iquitos y un puñado de pueblos. Mediana
  de distancia del punto de demanda a la vía más cercana: **43.3 km**
  (percentil 99: 331 km, máximo 414 km). **86.2% de los puntos de demanda
  de Loreto** (1,558 de 1,808) tienen `snap` mayor a
  `snap_confiable_max_m` (5 km) — es decir, para la gran mayoría de la
  población de Loreto, un "tiempo de viaje en auto" calculado por OSRM
  **no representa cómo esa población realmente se moviliza** (transporte
  fluvial). Además, **162 puntos de demanda quedan sin ninguna ruta
  válida** a ninguna facility (componente de red desconectada).
  **Consecuencia metodológica:** el análisis de "golden hour" en auto es
  estructuralmente inadecuado para la mayor parte de Loreto. Se mantiene
  el cálculo (todo queda flageado, nada se descarta silenciosamente —
  `snap_confiable=False` en la matriz), pero **Fase 3 debe excluir o
  tratar aparte** estos puntos al construir métricas de cobertura, y el
  reporte (Fase 5) debe discutir esto como limitación central, no como
  nota al pie — con una recomendación de innovación: un motor de ruteo
  fluvial/multimodal para la selva quedaría fuera de alcance de este
  proyecto pero es la extensión obviamente necesaria.

## Fuentes de datos y sustituciones documentadas

- **RENIPRESS / SUSALUD** (oferta — establecimientos de salud): CSV mensual,
  URL en `fuentes.renipress_url`. El portal publica un archivo nuevo cada
  mes (`RENIPRESS_DD-MM-AAAA.csv`); si la URL fija devuelve 404, revisar
  https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress
  y actualizar `fuentes.renipress_url` con el mes vigente.

- **Límites administrativos**: HDX COD-AB Perú (`per_admin_boundaries.geojson.zip`),
  fuente original Instituto Geográfico Nacional (IGN), publicado por
  OCHA/HDX. Niveles: departamento (25), provincia (196), distrito (1873).
  https://data.humdata.org/dataset/cod-ab-per

- **Demanda — centros poblados (SUSTITUCIÓN sobre el enunciado original)**:
  el enunciado pide el "spatial download" de MINEDU/SIGMED
  (https://sigmed.minedu.gob.pe/descargas/), pero esa herramienta es una
  aplicación ASP.NET WebForms interactiva (postbacks + ViewState) sin
  endpoint estable ni URL de descarga directa — no es automatizable ni
  re-ejecutable de forma confiable. Se sustituye por el servicio ArcGIS
  REST **"Centros Poblados Dispersos"** del geoportal oficial IDEP
  (Infraestructura de Datos Espaciales del Perú), con datos de fuente
  INEI, consultable directamente vía HTTP/GeoJSON:
  `fuentes.centros_poblados_dispersos_query_url`.

  > **Limitación detectada y resuelta:** esta capa solo cubre centros
  > poblados *dispersos* (rurales, poblaciones pequeñas — verificado: en
  > Piura, 1711 puntos, máx. 150 hab/punto, suma total 106,051 hab. de
  > ~2 millones del departamento). La población urbana concentrada no
  > está representada como puntos individuales en ninguna capa pública
  > del geoportal IDEP. Se resolvió construyendo un **punto de demanda
  > urbano sintético por distrito** (`src/demand_urbano.py`,
  > `data/processed/demand_points_urbano.geojson`):
  > `pob_urbana_estimada(distrito) = pob_total_proyectada_2026(distrito) − Σ pob_total_dispersa(distrito)`,
  > ubicado en el punto "Capital de Distrito" del gazetteer nacional IGN
  > (`CENTROS_POBLADOS/MapServer/3`, filtro `CATEGORIA='Capital de
  > Distrito'`), con la codificación UBIGEO (campo de 10 dígitos del
  > gazetteer, primeros 6 = UBIGEO distrital — el nombre de ese campo
  > llega corrupto desde el propio geoportal por pérdida de un byte en la
  > tilde, así que se detecta por patrón de valor, no por nombre de
  > columna) como llave de cruce con la población distrital. Es una
  > simplificación deliberada (un punto por distrito para toda su
  > población urbana, no manzana por manzana) — razonable porque el
  > interés del análisis es el tiempo de viaje *hacia* la ciudad, no
  > dentro de ella. Documentar como supuesto metodológico en el reporte
  > (Fase 5), no como limitación no resuelta.
  >
  > **Hallazgo de validación cruzada (residual, pendiente para Fase 1b):**
  > la suma de los distritos procesados no calza exactamente con la fila
  > de departamento del Excel de INEI: Piura calza exacto (diferencia 0);
  > Cusco queda corto en 17,943 hab. porque el Excel 2026 incluye 4
  > distritos creados en 2021 (Ley N.° 31197: Kumpirushiato, Cielo Punco,
  > Manitea, Unión Ashéninka, desprendidos de Pichari) que **no existen**
  > en la capa de límites administrativos usada (HDX/IGN, vigente al
  > 2020-07-14); Loreto queda corto en 3,179 hab., pero esa diferencia
  > **ya existe dentro del propio Excel de INEI** (la suma de sus filas
  > distritales no iguala su propia fila departamental — no es un error
  > de este pipeline). `src/demand_urbano.py` imprime esta verificación
  > en cada corrida. Pendiente para Fase 1b: decidir si se agregan los 4
  > distritos nuevos de Cusco manualmente (UBIGEO y población ya
  > identificados) o se documentan como exclusión conocida en el reporte.

- **OSM Perú**: extracto Geofabrik, ver `README.md` (sección de routing) —
  ya descargado y grafo OSRM ya construido (Sesión 1).

## Fecha de descarga de datos crudos

Registrada automáticamente por `acquisition.py` en
`logs/download_manifest.json` cada vez que se corre cada fuente.
