# Accesibilidad a salud de emergencia en Perú ("Golden Hour")

Proyecto integrador (HW_02_202602): tiempos de viaje por carretera desde
centros poblados hasta el establecimiento de salud resolutivo más cercano
(capacidad quirúrgica / cesárea), en tres departamentos de Perú que
representan costa, sierra y selva.

Ver el enunciado completo en el issue del curso y los parámetros del
análisis (departamentos, umbrales, motor de ruteo) en [`config.md`](config.md).

## Estado del proyecto

Este repo se construye de forma incremental, fase por fase. Estado actual:

- [x] Fase 0 — Scaffold del repositorio
- [x] Fase 1a — Adquisición de datos (RENIPRESS, límites administrativos, centros poblados)
- [x] Fase 1b — Validación de datos (6 reglas sobre RENIPRESS + reporte de calidad)
- [ ] Fase 2 — Ruteo y matriz de tiempos de viaje
- [ ] Fase 3 — Construcción de métricas
- [ ] Fase 4 — Dashboard Streamlit
- [ ] Fase 5 — Reporte LaTeX
- [ ] Presentación (video)

## Estructura del repositorio

```
├── config.md               # todos los parámetros (departamentos, umbrales, rutas, motor de ruteo)
├── requirements.txt
├── src/
│   ├── config.py             # parser del bloque yaml en config.md
│   ├── acquisition.py       # Fase 1 — descarga de fuentes
│   ├── demand_urbano.py      # Fase 1 — construye puntos de demanda urbana (ver config.md)
│   ├── validation.py        # Fase 1 — reglas de calidad de datos
│   ├── routing.py           # Fase 2 — motor de ruteo + caché
│   ├── metrics.py           # Fase 3 — indicadores de acceso
│   └── export.py            # tablas/figuras para el reporte
├── data/
│   ├── raw/                 # descargas crudas, nunca se modifican (no versionado, ver .gitignore)
│   ├── processed/           # datasets limpios (GeoParquet/GeoPackage)
│   └── outputs/             # tablas/figuras finales usadas en el reporte y dashboard
├── app.py                   # Fase 4 — dashboard Streamlit
├── report/
│   ├── main.tex              # Fase 5 — reporte técnico
│   └── figures/
└── logs/                     # logs de ejecución y reporte de calidad de datos
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### Motor de ruteo (OSRM vía Docker)

Requiere Docker Desktop (WSL2 backend en Windows). Con el extracto de
`data/raw/osm/peru-latest.osm.pbf` ya descargado (ver `logs/download_manifest.json`),
el grafo se construye una sola vez con:

```bash
docker run -t -v "${PWD}/data/raw/osm:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/peru-latest.osm.pbf
docker run -t -v "${PWD}/data/raw/osm:/data" osrm/osrm-backend osrm-partition /data/peru-latest.osrm
docker run -t -v "${PWD}/data/raw/osm:/data" osrm/osrm-backend osrm-customize /data/peru-latest.osrm
```

Y se sirve con:

```bash
docker run -d -p 5000:5000 -v "${PWD}/data/raw/osm:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/peru-latest.osrm
```

Los archivos `peru-latest.osrm*` (~1.5GB) no se versionan en git; se
regeneran con los comandos de arriba.

## Cómo correr el pipeline

### Fase 1a — Adquisición de datos

```bash
cd src
python acquisition.py
```

Descarga (o reutiliza si ya existen) RENIPRESS, límites administrativos,
centros poblados dispersos, capitales distritales y población distrital
proyectada hacia `data/raw/`, y registra cada descarga en
`logs/download_manifest.json`. Es re-ejecutable sin re-descargar: pasar
`force=True` a las funciones individuales para forzar una descarga nueva.

Luego, para construir los puntos de demanda urbana (población urbana
estimada por distrito = población total proyectada − población dispersa,
ver [`config.md`](config.md)):

```bash
python demand_urbano.py
```

Genera `data/processed/demand_points_urbano.geojson` e imprime una
verificación cruzada contra los totales departamentales del Excel de
INEI (ver salida del script para las diferencias residuales conocidas).

### Fase 1b — Validación de datos

```bash
python validation.py
```

Aplica las 6 reglas de calidad de datos (ver [`config.md`](config.md))
sobre los establecimientos RENIPRESS de los 3 departamentos, normaliza
`CATEGORIA`/`ESTADO` a la definición de "resolutivo", y exporta:

- `data/processed/renipress_validado.parquet` — todos los registros, con
  una columna de banderas por regla (nada se descarta silenciosamente) y
  `coords_utilizables` para saber cuáles sirven para ruteo en Fase 2.
- `logs/data_quality_report.json` — conteos y la acción tomada por cada
  regla.

## Cómo correr el dashboard

```bash
streamlit run app.py
```

(Disponible desde la Fase 4.)

## Fuentes de datos

- RENIPRESS / SUSALUD (establecimientos de salud) — CSV mensual de datosabiertos.gob.pe
- Centros poblados dispersos (INEI, vía geoportal IDEP, ArcGIS REST) —
  **sustituye** a MINEDU/SIGMED, que resultó ser una app interactiva sin
  endpoint estable. Ver la sección "Fuentes de datos y sustituciones
  documentadas" en [`config.md`](config.md) para el detalle y una
  limitación conocida (solo cubre población rural dispersa, no urbana).
- Límites administrativos (departamento/provincia/distrito) — HDX COD-AB
  Perú, fuente original IGN
- OpenStreetMap — extracto de Perú (Geofabrik)

Fechas de descarga, tamaños y publishers se documentan automáticamente en
`logs/download_manifest.json` cada vez que se corre `acquisition.py`.

## Limitaciones conocidas

*Se completa en la Fase 5 (reporte), pero se resume aquí también para
quien solo revise el repo.*
