# Configuración del proyecto

Todos los parámetros del pipeline viven aquí. Ningún módulo en `src/` debe
tener rutas, departamentos, umbrales o listas de categorías hardcodeadas:
todos se leen desde este archivo (vía `src/config.py`, que lo parsea).

## Departamentos analizados

Exactamente tres, uno por macro-región. Cambiar aquí no requiere tocar código.

| Rol | Departamento | Código UBIGEO (dep) |
|---|---|---|
| Costa | Piura | 20 |
| Andino | Cusco | 08 |
| Amazónico | Loreto | 16 |

## Definición de "resolutivo"

- Estado operativo: `activo` (ver normalización de estados en `validation.py`)
- Categoría (RENIPRESS, normalizada): `II-1`, `II-2`, `II-E`, `III-1`, `III-2`, `III-E`
- Todo lo demás (`I-1`..`I-4`, sin categoría, categorías no reconocidas) se
  mantiene en el dataset pero se excluye del cómputo de facility más cercana.

## Bounding box Perú (validación de coordenadas)

- Longitud: `-81.4` a `-68.6`
- Latitud: `-18.4` a `-0.04`

## Reglas de validación (Fase 1)

1. Coordenadas nulas / cero
2. Coordenadas fuera del bounding box
3. Lat/lon posiblemente invertidas
4. Punto fuera del polígono distrital que declara su propio registro
5. Códigos de establecimiento duplicados
6. Problemas de encoding en campos de texto (UTF-8 vs. latin-1)

## Routing (Fase 2)

- Motor: `osrm` (Docker, perfil `car` para el cómputo principal; perfil
  `foot` para el tramo urbano a pie)
- Extracto OSM: `peru-latest.osm.pbf` (Geofabrik)
- Puerto local OSRM: `5000` (car), `5001` (foot)
- Tope de puntos de demanda: `5000` (si se excede, muestreo estratificado
  por distrito, ponderado por población)
- Caché de rutas: `data/processed/routing_cache/` (Parquet, nunca se
  recomputa lo ya existente)

## Rutas

- Datos crudos: `data/raw/`
- Datos procesados: `data/processed/` (GeoParquet / GeoPackage)
- Salidas (tablas/figuras para el reporte): `data/outputs/`
- Logs de ejecución: `logs/`

## Umbrales de cobertura (Fase 3)

- Bandas de acceso: `30`, `60`, `120` minutos (y `>120`)

## Fuentes de datos

- RENIPRESS / SUSALUD: https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress
- MINEDU / SIGMED (centros poblados): https://sigmed.minedu.gob.pe/descargas/
- OSM Perú: https://download.geofabrik.de/south-america/peru-latest.osm.pbf
- Límites administrativos: *por definir y citar en el reporte*

## Fecha de descarga de datos crudos

*Se completa automáticamente por `acquisition.py` en `logs/download_manifest.json`
la primera vez que se corre cada fuente.*
