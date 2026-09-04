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

- Estado operativo: activo (ver normalización de estados en `validation.py`,
  Fase 1b — el campo de estado en RENIPRESS no está limpio y requiere reglas
  explícitas, no un simple `== "ACTIVO"`)
- Categoría (normalizada): ver `resolutivo.categorias` en el YAML
- Todo lo demás (`I-1`..`I-4`, sin categoría, categorías no reconocidas) se
  mantiene en el dataset pero se excluye del cómputo de facility más cercana.

## Reglas de validación (Fase 1b — pendiente)

1. Coordenadas nulas / cero
2. Coordenadas fuera del bounding box (`bbox_peru` en el YAML)
3. Lat/lon posiblemente invertidas
4. Punto fuera del polígono distrital que declara su propio registro
5. Códigos de establecimiento duplicados
6. Problemas de encoding en campos de texto (UTF-8 vs. latin-1)

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
