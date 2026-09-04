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

  > **Limitación conocida (pendiente de resolver, no bloqueante para
  > avanzar el pipeline):** esta capa solo cubre centros poblados
  > *dispersos* (rurales, poblaciones pequeñas — verificado: en Piura,
  > 1711 puntos, máx. 150 hab/punto, suma total 106,051 hab. de ~2
  > millones del departamento). La población urbana concentrada no está
  > representada como puntos en esta capa. Se documentará como límite del
  > análisis en el reporte (Fase 5) y se evaluará en una sesión futura
  > si se agrega un punto de demanda urbano por distrito (capital
  > distrital + población urbana desde INEI/SIRTOD) para no subestimar
  > la cobertura en las ciudades.

- **OSM Perú**: extracto Geofabrik, ver `README.md` (sección de routing) —
  ya descargado y grafo OSRM ya construido (Sesión 1).

## Fecha de descarga de datos crudos

Registrada automáticamente por `acquisition.py` en
`logs/download_manifest.json` cada vez que se corre cada fuente.
