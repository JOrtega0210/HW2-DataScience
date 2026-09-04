"""Fase 4 - dashboard Streamlit.

Lee unicamente archivos precomputados de data/outputs/, data/processed/ y
logs/ (Fases 1-3) -- no llama al motor de ruteo ni recalcula metricas en
vivo (esa logica vive en src/metrics.py). Requiere haber corrido
acquisition.py, demand_urbano.py, validation.py, routing.py y metrics.py
al menos una vez (ver README.md).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import geopandas as gpd
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import ROOT, load_config
from metrics import coverage_pct, simulate_facility_upgrade, weighted_median_access
from routing import load_candidate_points

OUTPUTS = ROOT / "data" / "outputs"
LOGS = ROOT / "logs"
ADMIN3_PATH = ROOT / "data" / "raw" / "boundaries" / "per_admin3.geojson"
RENIPRESS_PATH = ROOT / "data" / "processed" / "renipress_validado.parquet"

CFG = load_config()
DEPARTAMENTOS = list(CFG["departamentos"].values())
BANDS = CFG["coverage_bands_min"]

st.set_page_config(page_title="Accesibilidad a salud de emergencia - Peru", layout="wide")


# ---------------------------------------------------------------------------
# Carga de datos (cacheada -- todo precomputado, nada se recalcula aqui)
# ---------------------------------------------------------------------------

@st.cache_data
def load_access_table() -> pd.DataFrame:
    return pd.read_csv(OUTPUTS / "access_table.csv")


@st.cache_data
def load_district_geo() -> gpd.GeoDataFrame:
    adm3 = gpd.read_file(ADMIN3_PATH)
    adm3["ubigeo"] = adm3["adm3_pcode"].str[2:]
    adm3 = adm3[adm3["adm1_name"].str.upper().isin(DEPARTAMENTOS)][["ubigeo", "geometry"]]
    weighted = pd.read_csv(OUTPUTS / "access_por_distrito.csv")
    weighted["ubigeo"] = weighted["ubigeo"].astype(str).str.zfill(6)
    return adm3.merge(weighted, on="ubigeo", how="left")


@st.cache_data
def load_facilities() -> gpd.GeoDataFrame:
    df = gpd.read_parquet(RENIPRESS_PATH)
    return df[df["DEPARTAMENTO"].str.upper().isin(DEPARTAMENTOS) & df["coords_utilizables"]]


@st.cache_data
def load_quality_report() -> dict:
    return json.loads((LOGS / "data_quality_report.json").read_text(encoding="utf-8"))


@st.cache_data
def load_routing_reports() -> dict:
    return {
        dep: json.loads((LOGS / f"routing_report_{dep.lower()}.json").read_text(encoding="utf-8"))
        for dep in DEPARTAMENTOS
    }


@st.cache_data
def load_download_manifest() -> dict:
    return json.loads((LOGS / "download_manifest.json").read_text(encoding="utf-8"))


@st.cache_data
def load_gini() -> dict:
    return json.loads((OUTPUTS / "gini_lorenz.json").read_text(encoding="utf-8"))


@st.cache_data
def load_distritos_criticos() -> pd.DataFrame:
    return pd.read_csv(OUTPUTS / "distritos_criticos.csv")


@st.cache_data
def load_urbano_rural() -> pd.DataFrame:
    return pd.read_csv(OUTPUTS / "urbano_vs_rural.csv")


@st.cache_data
def load_cruce_poblacion() -> dict:
    return json.loads((OUTPUTS / "cruce_poblacion_acceso.json").read_text(encoding="utf-8"))


@st.cache_data
def load_candidatos(departamento: str) -> gpd.GeoDataFrame:
    return load_candidate_points(departamento)


access_full = load_access_table()
facilities_full = load_facilities()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.header("Filtros")
sel_departamentos = st.sidebar.multiselect("Departamento", DEPARTAMENTOS, default=DEPARTAMENTOS)
umbral_min = st.sidebar.slider("Umbral de tiempo (min)", min_value=15, max_value=180, value=60, step=15)

categorias_disponibles = sorted(facilities_full["categoria_norm"].unique().tolist())
sel_categorias = st.sidebar.multiselect("Categoria de establecimiento", categorias_disponibles, default=categorias_disponibles)

instituciones_disponibles = sorted(facilities_full["INSTITUCION"].dropna().unique().tolist())
sel_instituciones = st.sidebar.multiselect("Institucion", instituciones_disponibles, default=instituciones_disponibles)

st.sidebar.divider()
st.sidebar.caption(
    "Dashboard de solo lectura: todo viene de data/outputs, data/processed y "
    "logs (Fases 1-3), ya precomputado. Ver config.md para la metodologia completa."
)

if not sel_departamentos:
    st.warning("Selecciona al menos un departamento en la barra lateral para ver resultados.")
    st.stop()

access = access_full[access_full["departamento"].isin(sel_departamentos)]
facilities = facilities_full[
    facilities_full["DEPARTAMENTO"].str.upper().isin(sel_departamentos)
    & facilities_full["categoria_norm"].isin(sel_categorias)
    & facilities_full["INSTITUCION"].isin(sel_instituciones)
]


# ---------------------------------------------------------------------------
# Titulo + KPIs
# ---------------------------------------------------------------------------

st.title("Accesibilidad a salud de emergencia en Peru — \"Golden Hour\"")
st.caption(
    "Tiempo de viaje por carretera desde centros poblados hasta el establecimiento de salud "
    "resolutivo mas cercano (capacidad quirurgica / cesarea). Piura (costa), Cusco (andino), Loreto (amazonico)."
)

pob_total = access["poblacion"].sum()
pob_cubierta = coverage_pct(access, umbral_min) * pob_total
pob_mas_alla_60 = (1 - coverage_pct(access, 60)) * pob_total
mediana = weighted_median_access(access)

dist_geo_all = load_district_geo()
dist_sel = dist_geo_all[dist_geo_all["departamento"].isin(sel_departamentos)] if "departamento" in dist_geo_all.columns else dist_geo_all
peor_distrito_row = dist_sel.loc[dist_sel["t_min_ponderado"].idxmax()] if dist_sel["t_min_ponderado"].notna().any() else None

k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Poblacion cubierta (<= {umbral_min} min)", f"{pob_cubierta:,.0f}", f"{pob_cubierta / pob_total:.1%}" if pob_total else "—")
k2.metric("Poblacion a mas de 60 min", f"{pob_mas_alla_60:,.0f}", f"{pob_mas_alla_60 / pob_total:.1%}" if pob_total else "—")
k3.metric(
    "Distrito con peor acceso",
    f"{peor_distrito_row['dist']}" if peor_distrito_row is not None else "—",
    f"{peor_distrito_row['t_min_ponderado']:.0f} min" if peor_distrito_row is not None else "",
)
k4.metric("Mediana de acceso (ponderada)", f"{mediana:.0f} min" if mediana == mediana else "—")

st.divider()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_mapa, tab_dist, tab_criticos, tab_sim, tab_calidad = st.tabs(
    ["Mapa", "Distribucion", "Distritos criticos", "Simulador de escenarios", "Calidad de datos"]
)

with tab_mapa:
    st.subheader("Tiempo de acceso ponderado por distrito y establecimientos de salud")

    map_df = dist_sel.dropna(subset=["t_min_ponderado"]).copy()
    if len(map_df) == 0:
        st.info("No hay distritos con datos de acceso confiables para esta seleccion.")
    else:
        geojson = json.loads(map_df.to_json())
        center = {"lat": map_df.geometry.centroid.y.mean(), "lon": map_df.geometry.centroid.x.mean()}

        fig = go.Figure()
        fig.add_trace(
            go.Choroplethmapbox(
                geojson=geojson,
                locations=map_df.index,
                z=map_df["t_min_ponderado"],
                colorscale="YlOrRd",
                marker_opacity=0.75,
                marker_line_width=0.5,
                colorbar_title="min",
                customdata=map_df[["dist", "prov", "dep", "t_min_ponderado", "poblacion_total", "pct_poblacion_sin_dato_confiable"]],
                hovertemplate=(
                    "<b>%{customdata[0]}</b> (%{customdata[1]}, %{customdata[2]})<br>"
                    "Acceso ponderado: %{customdata[3]:.0f} min<br>"
                    "Poblacion: %{customdata[4]:,.0f}<br>"
                    "%% sin dato confiable: %{customdata[5]:.1%}<extra></extra>"
                ),
            )
        )

        show_resolutivo = st.checkbox("Mostrar establecimientos resolutivos", value=True)
        show_no_resolutivo = st.checkbox("Mostrar establecimientos NO resolutivos", value=False)
        fac_map = facilities[
            (facilities["es_resolutivo"] & show_resolutivo) | (~facilities["es_resolutivo"] & show_no_resolutivo)
        ]
        if len(fac_map) > 0:
            fig.add_trace(
                go.Scattermapbox(
                    lat=fac_map.geometry.y,
                    lon=fac_map.geometry.x,
                    mode="markers",
                    marker=dict(
                        size=8,
                        color=fac_map["es_resolutivo"].map({True: "#1a9850", False: "#4575b4"}),
                    ),
                    text=fac_map["NOMBRE"] + " (" + fac_map["categoria_norm"] + ")",
                    hovertemplate="%{text}<extra></extra>",
                    name="Establecimientos",
                )
            )

        fig.update_layout(
            mapbox_style="open-street-map",
            mapbox_zoom=5.5,
            mapbox_center=center,
            margin=dict(l=0, r=0, t=0, b=0),
            height=600,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Puntos verdes = establecimientos resolutivos (II-1+, activos). Puntos azules = no resolutivos "
            "(mostrar con el checkbox). Distritos en gris: sin dato de acceso confiable."
        )

with tab_dist:
    st.subheader("Distribucion del tiempo de acceso")
    split_by = st.radio("Separar por", ["departamento", "tipo_demanda"], horizontal=True)
    plot_data = access[access["confiabilidad"] == "confiable"]
    if len(plot_data) == 0:
        st.info("No hay puntos con datos confiables para esta seleccion.")
    else:
        fig_hist = px.histogram(
            plot_data, x="t_min", color=split_by, nbins=40, barmode="overlay", opacity=0.6,
            labels={"t_min": "Tiempo de acceso (min)"},
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        fig_ecdf = px.ecdf(plot_data, x="t_min", color=split_by, labels={"t_min": "Tiempo de acceso (min)"})
        st.plotly_chart(fig_ecdf, use_container_width=True)

    n_no_confiable = (access["confiabilidad"] != "confiable").sum()
    if n_no_confiable:
        pop_no_confiable = access.loc[access["confiabilidad"] != "confiable", "poblacion"].sum()
        st.caption(
            f"{n_no_confiable} puntos ({pop_no_confiable:,.0f} hab.) excluidos de estos graficos por no tener "
            f"un tiempo de acceso confiable (ver pestana 'Calidad de datos')."
        )

with tab_criticos:
    st.subheader("Distritos con peor acceso (ponderado por poblacion)")
    criticos = load_distritos_criticos()
    criticos = criticos[criticos["departamento"].isin(sel_departamentos)]
    st.dataframe(
        criticos[
            ["departamento", "dep", "prov", "dist", "poblacion_confiable", "t_min_ponderado", "poblacion_no_confiable", "poblacion_sin_ruta", "pct_poblacion_sin_dato_confiable"]
        ].style.format({"t_min_ponderado": "{:.0f}", "pct_poblacion_sin_dato_confiable": "{:.1%}"}),
        use_container_width=True,
    )
    st.download_button(
        "Descargar CSV",
        criticos.to_csv(index=False).encode("utf-8"),
        file_name="distritos_criticos.csv",
        mime="text/csv",
    )

    st.subheader("Contraste urbano vs. rural")
    ur = load_urbano_rural()
    ur = ur[ur["departamento"].isin(sel_departamentos)]
    st.dataframe(ur.style.format({"t_min_ponderado": "{:.1f}", "poblacion_total": "{:,.0f}"}), use_container_width=True)

with tab_sim:
    st.subheader("Simulador: upgradear establecimientos I-3/I-4 a resolutivos")
    st.caption(
        "Selecciona uno o mas establecimientos I-3/I-4 (activos, con coordenadas utilizables) para simular "
        "que pasan a tener capacidad resolutiva. Recalcula el tiempo de acceso de cada punto de demanda usando "
        "la matriz precomputada demanda x candidatos (Fase 2) -- no se llama al motor de ruteo aqui."
    )

    if len(sel_departamentos) != 1:
        st.info("Selecciona exactamente un departamento en la barra lateral para correr el simulador.")
    else:
        dep_sim = sel_departamentos[0]
        candidatos = load_candidatos(dep_sim)
        opciones = {
            f"{row.NOMBRE} ({row.categoria_norm}) - {row.facility_id}": row.facility_id
            for row in candidatos.itertuples()
        }
        seleccion_labels = st.multiselect("Establecimientos a upgradear", sorted(opciones.keys()))
        seleccion_ids = [opciones[l] for l in seleccion_labels]

        access_dep = access_full[access_full["departamento"] == dep_sim]
        sim = simulate_facility_upgrade(access_dep, dep_sim, seleccion_ids)

        antes = coverage_pct(access_dep, umbral_min)
        despues = coverage_pct(sim, umbral_min, t_min_col="t_min_simulado")
        pob_dep = access_dep["poblacion"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric(f"Cobertura antes (<= {umbral_min} min)", f"{antes:.1%}", f"{antes * pob_dep:,.0f} hab.")
        c2.metric(f"Cobertura despues (<= {umbral_min} min)", f"{despues:.1%}", f"{despues * pob_dep:,.0f} hab.")
        c3.metric("Ganancia marginal", f"{(despues - antes):+.1%}", f"{(despues - antes) * pob_dep:+,.0f} hab.")

        if seleccion_ids:
            fig_sim = px.ecdf(
                pd.concat(
                    [
                        sim[["t_min"]].rename(columns={"t_min": "min"}).assign(escenario="Antes"),
                        sim[["t_min_simulado"]].rename(columns={"t_min_simulado": "min"}).assign(escenario="Despues"),
                    ]
                ),
                x="min", color="escenario", labels={"min": "Tiempo de acceso (min)"},
            )
            st.plotly_chart(fig_sim, use_container_width=True)

with tab_calidad:
    st.subheader("Fase 1b — Validacion RENIPRESS")
    quality = load_quality_report()
    st.write(f"**{quality['n_registros_3_departamentos']:,} establecimientos** en 3 departamentos (de {quality['n_registros_nacional']:,} a nivel nacional).")
    reglas_df = pd.DataFrame(
        [
            {"regla": k, "descripcion": v["descripcion"], "n_flagged": v.get("n_flagged"), "accion": v["accion"]}
            for k, v in quality["reglas"].items()
        ]
    )
    st.dataframe(reglas_df, use_container_width=True)

    st.subheader("Fase 2 — Calidad del ruteo (snapping y conectividad)")
    routing_reports = load_routing_reports()
    rows = []
    for dep in sel_departamentos:
        r = routing_reports[dep]
        rows.append(
            {
                "departamento": dep,
                "n_demanda": r["n_demanda"],
                "pares_sin_ruta": r["pares_sin_ruta"],
                "sin_ninguna_ruta": r["puntos_demanda_sin_ninguna_ruta"],
                "snap_demanda_mediana_m": r["snapping"]["demanda_mediana_m"],
                "%_snap_no_confiable": r["snapping"]["demanda_pct_snap_no_confiable"],
                "coincide_recta_vs_red": r["comparacion_recta_vs_red"]["coincide_facility_mas_cercano_pct"],
            }
        )
    st.dataframe(
        pd.DataFrame(rows).style.format(
            {"snap_demanda_mediana_m": "{:.0f}", "%_snap_no_confiable": "{:.1%}", "coincide_recta_vs_red": "{:.1%}"}
        ),
        use_container_width=True,
    )
    if "LORETO" in sel_departamentos:
        st.warning(
            "**Loreto**: la red vial mapeada en OSM practicamente no existe fuera de Iquitos. "
            "43.9% de la poblacion de Loreto no tiene un tiempo de acceso confiable en auto "
            "(ver config.md, seccion Fase 2/3, para el detalle completo). No es un error del pipeline."
        )

    st.subheader("Gini de acceso (ponderado por poblacion)")
    gini = load_gini()
    gcols = st.columns(len(sel_departamentos) + 1)
    gcols[0].metric("Total (3 deptos)", f"{gini['total']['gini']:.3f}")
    for i, dep in enumerate(sel_departamentos, start=1):
        gcols[i].metric(dep, f"{gini['por_departamento'][dep]['gini']:.3f}")

    with st.expander("Cruce con tamano de poblacion (segunda dimension, Fase 3)"):
        cruce = load_cruce_poblacion()
        st.write(cruce["interpretacion"])
        st.json(cruce["por_departamento"])
