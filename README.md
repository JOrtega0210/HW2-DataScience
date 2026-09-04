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
- [ ] Fase 1 — Adquisición y validación de datos
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
│   ├── acquisition.py       # Fase 1 — descarga de fuentes
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

Requiere Docker Desktop (WSL2 backend en Windows). Instrucciones de build
del grafo OSRM para Perú se documentarán en la Fase 2, junto con
`routing.py`.

## Cómo correr el pipeline

*Se documentará a medida que cada fase quede lista.*

## Cómo correr el dashboard

```bash
streamlit run app.py
```

(Disponible desde la Fase 4.)

## Fuentes de datos

- RENIPRESS / SUSALUD (establecimientos de salud)
- MINEDU / SIGMED (centros poblados con coordenadas)
- OpenStreetMap — extracto de Perú (Geofabrik)
- Límites administrativos (distrito/provincia/departamento)

Fechas de descarga y licencias se documentan en `logs/download_manifest.json`
a partir de la Fase 1.

## Limitaciones conocidas

*Se completa en la Fase 5 (reporte), pero se resume aquí también para
quien solo revise el repo.*
