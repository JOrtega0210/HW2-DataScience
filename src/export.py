"""Fase 5 - genera las figuras y tablas del reporte LaTeX desde data/outputs/.

Nada se calcula aqui: solo lectura de los CSV/JSON ya producidos por
metrics.py y formato para matplotlib / LaTeX. Figuras -> report/figures/
(PDF vectorial). Tablas -> report/tables/ (fragmentos .tex con \\input-able,
generadas con df.to_latex(booktabs=True), nunca tipeadas a mano).
"""

import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import ROOT, load_config

OUTPUTS = ROOT / "data" / "outputs"
FIGURES_DIR = ROOT / "report" / "figures"
TABLES_DIR = ROOT / "report" / "tables"
ADMIN3_PATH = ROOT / "data" / "raw" / "boundaries" / "per_admin3.geojson"

BAND_ORDER = ["<=30", "<=60", "<=120", ">120", "no_confiable", "sin_ruta"]
BAND_COLORS = {
    "<=30": "#1a9850",
    "<=60": "#91cf60",
    "<=120": "#fee08b",
    ">120": "#d73027",
    "no_confiable": "#999999",
    "sin_ruta": "#4d4d4d",
}
BAND_LABELS = {
    "<=30": "$\\leq$30 min",
    "<=60": "31-60 min",
    "<=120": "61-120 min",
    ">120": "$>$120 min",
    "no_confiable": "Sin dato confiable",
    "sin_ruta": "Sin ruta vial",
}

plt.rcParams.update({"font.size": 10, "figure.dpi": 150, "axes.grid": True, "grid.alpha": 0.3})


def fig_coverage_bands():
    df = pd.read_csv(OUTPUTS / "coverage_bands_departamento.csv")
    deps = df["departamento"].unique().tolist()
    pivot = df.pivot(index="departamento", columns="banda", values="pct_poblacion").reindex(columns=BAND_ORDER).fillna(0) * 100

    fig, ax = plt.subplots(figsize=(7, 4))
    bottom = np.zeros(len(pivot))
    for band in BAND_ORDER:
        ax.bar(pivot.index, pivot[band], bottom=bottom, label=BAND_LABELS[band], color=BAND_COLORS[band])
        bottom += pivot[band].to_numpy()
    ax.set_ylabel("% de población")
    ax.set_ylim(0, 100)
    ax.set_title("Bandas de cobertura por departamento")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "coverage_bands.pdf")
    plt.close(fig)


def fig_ecdf():
    df = pd.read_csv(OUTPUTS / "access_table.csv")
    df = df[df["confiabilidad"] == "confiable"]

    fig, ax = plt.subplots(figsize=(7, 4))
    for dep, color in zip(["PIURA", "CUSCO", "LORETO"], ["#4575b4", "#74add1", "#d73027"]):
        sub = df[df["departamento"] == dep].sort_values("t_min")
        cum_pop = sub["poblacion"].cumsum() / sub["poblacion"].sum()
        ax.plot(sub["t_min"], cum_pop, label=dep.title(), color=color, linewidth=1.5)
    ax.axvline(60, color="grey", linestyle="--", linewidth=0.8)
    ax.text(62, 0.02, "60 min", fontsize=8, color="grey")
    ax.set_xlabel("Tiempo de acceso (min)")
    ax.set_ylabel("Proporción acumulada de población")
    ax.set_xlim(0, 300)
    ax.set_title("Distribución acumulada del tiempo de acceso (puntos confiables)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "ecdf_acceso.pdf")
    plt.close(fig)


def fig_lorenz():
    gini = json.loads((OUTPUTS / "gini_lorenz.json").read_text(encoding="utf-8"))

    fig, ax = plt.subplots(figsize=(5, 5))
    for dep, color in [("total", "black")] + list(zip(["PIURA", "CUSCO", "LORETO"], ["#4575b4", "#74add1", "#d73027"])):
        data = gini["total"] if dep == "total" else gini["por_departamento"][dep]
        label = f"Total (Gini={gini['total']['gini']:.2f})" if dep == "total" else f"{dep.title()} (Gini={data['gini']:.2f})"
        ax.plot(data["lorenz_cum_poblacion"], data["lorenz_cum_tiempo"], label=label, color=color, linewidth=1.5)
    ax.plot([0, 1], [0, 1], color="grey", linestyle="--", linewidth=0.8, label="Igualdad perfecta")
    ax.set_xlabel("Proporción acumulada de población")
    ax.set_ylabel("Proporción acumulada de tiempo de acceso")
    ax.set_title("Curva de Lorenz del tiempo de acceso\n(topeado a 240 min)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "lorenz.pdf")
    plt.close(fig)


def fig_mapa_distrital():
    cfg = load_config()
    departamentos = list(cfg["departamentos"].values())
    adm3 = gpd.read_file(ADMIN3_PATH)
    adm3["ubigeo"] = adm3["adm3_pcode"].str[2:]
    adm3 = adm3[adm3["adm1_name"].str.upper().isin(departamentos)]

    weighted = pd.read_csv(OUTPUTS / "access_por_distrito.csv")
    weighted["ubigeo"] = weighted["ubigeo"].astype(str).str.zfill(6)
    gdf = adm3.merge(weighted, on="ubigeo", how="left")

    fig, axes = plt.subplots(1, 3, figsize=(12, 5))
    for ax, dep in zip(axes, departamentos):
        sub = gdf[gdf["adm1_name"].str.upper() == dep]
        sub.plot(
            column="t_min_ponderado", cmap="YlOrRd", linewidth=0.2, edgecolor="grey",
            legend=True, legend_kwds={"label": "min", "shrink": 0.6}, ax=ax, missing_kwds={"color": "lightgrey"},
        )
        ax.set_title(dep.title())
        ax.set_axis_off()
    fig.suptitle("Tiempo de acceso ponderado por población, por distrito")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "mapa_distrital.pdf")
    plt.close(fig)


def table_access_departamento():
    df = pd.read_csv(OUTPUTS / "access_por_departamento.csv")
    gini = json.loads((OUTPUTS / "gini_lorenz.json").read_text(encoding="utf-8"))
    df["gini"] = df["departamento"].map(lambda d: gini["por_departamento"][d]["gini"])

    out = df[["dep", "poblacion_total", "t_min_ponderado", "gini", "pct_poblacion_sin_dato_confiable"]].copy()
    out.columns = ["Departamento", "Población", "T. acceso ponderado (min)", "Gini", "\\% sin dato confiable"]
    out["Población"] = out["Población"].map(lambda x: f"{x:,.0f}")
    out["T. acceso ponderado (min)"] = out["T. acceso ponderado (min)"].map(lambda x: f"{x:.1f}")
    out["Gini"] = out["Gini"].map(lambda x: f"{x:.3f}")
    out["\\% sin dato confiable"] = out["\\% sin dato confiable"].map(lambda x: f"{x*100:.1f}\%")

    tex = out.to_latex(index=False, escape=False, caption="Resumen de acceso por departamento.", label="tab:access_departamento")
    (TABLES_DIR / "access_departamento.tex").write_text(tex, encoding="utf-8")


def table_distritos_criticos(n: int = 10):
    df = pd.read_csv(OUTPUTS / "distritos_criticos.csv").head(n)
    out = df[["dep", "prov", "dist", "poblacion_total", "t_min_ponderado", "pct_poblacion_sin_dato_confiable"]].copy()
    out.columns = ["Depto.", "Provincia", "Distrito", "Población", "T. acceso (min)", "\\% sin dato confiable"]
    out["Población"] = out["Población"].map(lambda x: f"{x:,.0f}")
    out["T. acceso (min)"] = out["T. acceso (min)"].map(lambda x: f"{x:.0f}")
    out["\\% sin dato confiable"] = out["\\% sin dato confiable"].map(lambda x: f"{x*100:.1f}\%")

    tex = out.to_latex(
        index=False, escape=False,
        caption=f"Los {n} distritos con peor acceso ponderado por poblaci\\'on.",
        label="tab:distritos_criticos",
    )
    (TABLES_DIR / "distritos_criticos.tex").write_text(tex, encoding="utf-8")


def table_urbano_rural():
    df = pd.read_csv(OUTPUTS / "urbano_vs_rural.csv")
    out = df[["departamento", "tipo_demanda", "poblacion_total", "t_min_ponderado"]].copy()
    out.columns = ["Departamento", "Tipo", "Población", "T. acceso ponderado (min)"]
    out["Población"] = out["Población"].map(lambda x: f"{x:,.0f}")
    out["T. acceso ponderado (min)"] = out["T. acceso ponderado (min)"].map(lambda x: f"{x:.1f}")

    tex = out.to_latex(index=False, escape=False, caption="Contraste urbano vs. rural (solo puntos confiables).", label="tab:urbano_rural")
    (TABLES_DIR / "urbano_rural.tex").write_text(tex, encoding="utf-8")


def table_validacion():
    quality = json.loads((ROOT / "logs" / "data_quality_report.json").read_text(encoding="utf-8"))
    rows = []
    for k, v in quality["reglas"].items():
        rows.append({"Regla": k.replace("_", " "), "N marcados": v.get("n_flagged"), "Acción": v["accion"][:70] + ("..." if len(v["accion"]) > 70 else "")})
    out = pd.DataFrame(rows)
    tex = out.to_latex(index=False, escape=True, caption="Reglas de validaci\\'on aplicadas a RENIPRESS (Fase 1b).", label="tab:validacion")
    (TABLES_DIR / "validacion.tex").write_text(tex, encoding="utf-8")


def run_all():
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    fig_coverage_bands()
    fig_ecdf()
    fig_lorenz()
    fig_mapa_distrital()
    print(f"[export] 4 figuras -> {FIGURES_DIR}")

    table_access_departamento()
    table_distritos_criticos()
    table_urbano_rural()
    table_validacion()
    print(f"[export] 4 tablas -> {TABLES_DIR}")


if __name__ == "__main__":
    run_all()
