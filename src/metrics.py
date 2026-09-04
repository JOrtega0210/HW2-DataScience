"""Fase 3 - construccion de metricas de acceso a partir de las matrices de Fase 2.

Cada metrica es una funcion que toma un DataFrame y devuelve un DataFrame
(sin logica de metricas en el dashboard). Todo se agrega ponderado por
poblacion. Los puntos de demanda de Loreto sin ruta confiable (ver Fase 2
en config.md) NO se descartan: se tratan explicitamente como categoria
aparte ("sin_ruta" / "no_confiable"), documentado abajo.
"""

import json

import numpy as np
import pandas as pd
import geopandas as gpd

from config import ROOT, load_config
from routing import load_demand_points, CACHE_DIR

OUTPUTS_DIR = ROOT / "data" / "outputs"
ADMIN3_PATH = ROOT / "data" / "raw" / "boundaries" / "per_admin3.geojson"


# ---------------------------------------------------------------------------
# Construccion de la tabla de acceso (una fila por punto de demanda)
# ---------------------------------------------------------------------------

def _district_names() -> pd.DataFrame:
    adm3 = gpd.read_file(ADMIN3_PATH)[["adm3_pcode", "adm1_name", "adm2_name", "adm3_name"]]
    adm3["ubigeo"] = adm3["adm3_pcode"].str[2:]
    return adm3[["ubigeo", "adm1_name", "adm2_name", "adm3_name"]].rename(
        columns={"adm1_name": "dep", "adm2_name": "prov", "adm3_name": "dist"}
    )


def nearest_facility_per_demand(matrix: pd.DataFrame) -> pd.DataFrame:
    """Para cada demand_id: el facility con menor duration_s (si existe alguno)."""
    all_ids = matrix[["demand_id"]].drop_duplicates()
    routable = matrix.dropna(subset=["duration_s"])

    if len(routable) == 0:
        nearest = pd.DataFrame(
            columns=["demand_id", "facility_id", "duration_s", "distance_m", "straight_line_m", "snap_confiable"]
        )
    else:
        idx = routable.groupby("demand_id")["duration_s"].idxmin()
        nearest = routable.loc[
            idx, ["demand_id", "facility_id", "duration_s", "distance_m", "straight_line_m", "snap_confiable"]
        ].copy()

    out = all_ids.merge(nearest, on="demand_id", how="left")
    return out


def classify_confiabilidad(df: pd.DataFrame) -> pd.Series:
    """Clasifica cualquier tabla con duration_s/distance_m/snap_confiable
    (la matriz de ruteo cruda, o una tabla de 'mas cercano' ya resuelta) en
    confiable/no_confiable/sin_ruta. Un snap 'confiable' (ambos extremos
    cerca de una via mapeada) puede seguir dando una duracion sin sentido si
    esa via es una trocha que el perfil de auto trata como casi intransitable
    (velocidad promedio de pocos km/h en cientos de km) -- verificado en
    Loreto (Ramon Castilla: 409km en 4906 min = 5 km/h). Se reclasifica como
    no_confiable junto con los que fallan el chequeo de snap."""
    vel_kmh = (df["distance_m"] / 1000) / (df["duration_s"] / 3600)
    vel_min = load_config()["metricas"]["velocidad_minima_realista_kmh"]
    return pd.Series(
        np.select(
            [
                df["duration_s"].isna(),
                (df["snap_confiable"] == False) | (vel_kmh < vel_min),  # noqa: E712
            ],
            ["sin_ruta", "no_confiable"],
            default="confiable",
        ),
        index=df.index,
    )


def build_access_table(departamento: str) -> pd.DataFrame:
    """Una fila por punto de demanda: poblacion, ubigeo, tipo, t_min, confiabilidad."""
    matrix = pd.read_parquet(CACHE_DIR / f"matrix_{departamento.lower()}.parquet")
    demand = load_demand_points(departamento)
    nearest = nearest_facility_per_demand(matrix)

    df = demand.merge(nearest, on="demand_id", how="left")
    df = df.merge(_district_names(), on="ubigeo", how="left")

    df["t_min"] = df["duration_s"] / 60.0
    df["confiabilidad"] = classify_confiabilidad(df)
    df["departamento"] = departamento
    return df[
        [
            "demand_id",
            "departamento",
            "dep",
            "prov",
            "dist",
            "ubigeo",
            "tipo_demanda",
            "poblacion",
            "facility_id",
            "t_min",
            "distance_m",
            "straight_line_m",
            "confiabilidad",
        ]
    ]


def build_access_table_all(departamentos: list[str]) -> pd.DataFrame:
    return pd.concat([build_access_table(d) for d in departamentos], ignore_index=True)


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------

def coverage_bands(access: pd.DataFrame, group_col: str | None = "departamento") -> pd.DataFrame:
    """% de poblacion (ponderada) dentro de cada banda de tiempo. Solo se
    banda-ifica la poblacion 'confiable': un punto 'no_confiable' puede tener
    un t_min de OSRM absurdo (p.ej. miles de minutos, cuando el snap cae a
    decenas de km de la via real) tanto por exceso como por defecto, asi que
    NO se asume que cae en '>ultimo_umbral' -- se reporta como categoria
    aparte, igual que 'sin_ruta' (donde no hay ruta en absoluto)."""
    bands = load_config()["coverage_bands_min"]

    def _band(row):
        if row["confiabilidad"] != "confiable":
            return row["confiabilidad"]  # 'sin_ruta' o 'no_confiable', aparte
        for b in bands:
            if row["t_min"] <= b:
                return f"<={b}"
        return f">{bands[-1]}"

    df = access.copy()
    df["banda"] = df.apply(_band, axis=1)

    group_cols = [group_col, "banda"] if group_col else ["banda"]
    pop_by_band = df.groupby(group_cols)["poblacion"].sum().reset_index()
    pop_total = df.groupby(group_col)["poblacion"].sum() if group_col else df["poblacion"].sum()

    if group_col:
        pop_by_band["pct_poblacion"] = pop_by_band.apply(
            lambda r: r["poblacion"] / pop_total.loc[r[group_col]], axis=1
        )
    else:
        pop_by_band["pct_poblacion"] = pop_by_band["poblacion"] / pop_total

    return pop_by_band


def weighted_mean_access(access: pd.DataFrame, level: str) -> pd.DataFrame:
    """Tiempo de acceso promedio ponderado por poblacion, agregado a nivel
    distrito/provincia/departamento. t_min_ponderado se calcula UNICAMENTE
    con puntos 'confiable': incluir 'no_confiable' corrompe el promedio con
    duraciones de OSRM sin sentido cuando el punto snappea muy lejos de la
    red real (ver hallazgo Loreto en config.md). 'no_confiable' y 'sin_ruta'
    se reportan aparte, nunca mezclados en el promedio numerico."""
    cols = {"dist": ["departamento", "dep", "prov", "dist", "ubigeo"], "prov": ["departamento", "dep", "prov"], "dep": ["departamento", "dep"]}[level]
    confiable = access[access["confiabilidad"] == "confiable"].copy()

    def _wavg(g):
        w = g["poblacion"]
        return pd.Series(
            {
                "poblacion_confiable": w.sum(),
                "t_min_ponderado": np.average(g["t_min"], weights=w) if w.sum() > 0 else np.nan,
                "n_puntos_confiables": len(g),
            }
        )

    out = confiable.groupby(cols).apply(_wavg).reset_index()

    otras_pop = (
        access[access["confiabilidad"] != "confiable"]
        .groupby(cols + ["confiabilidad"])["poblacion"]
        .sum()
        .unstack("confiabilidad", fill_value=0)
        .reset_index()
    )
    for col in ["no_confiable", "sin_ruta"]:
        if col not in otras_pop.columns:
            otras_pop[col] = 0
    otras_pop = otras_pop.rename(columns={"no_confiable": "poblacion_no_confiable", "sin_ruta": "poblacion_sin_ruta"})

    out = out.merge(otras_pop[cols + ["poblacion_no_confiable", "poblacion_sin_ruta"]], on=cols, how="outer")
    for col in ["poblacion_confiable", "poblacion_no_confiable", "poblacion_sin_ruta"]:
        out[col] = out[col].fillna(0)
    out["poblacion_total"] = out["poblacion_confiable"] + out["poblacion_no_confiable"] + out["poblacion_sin_ruta"]
    out["pct_poblacion_sin_dato_confiable"] = (out["poblacion_no_confiable"] + out["poblacion_sin_ruta"]) / out["poblacion_total"]
    return out.sort_values("t_min_ponderado", ascending=False, na_position="last").reset_index(drop=True)


def critical_gap_list(weighted_dist: pd.DataFrame, n: int = 15, min_poblacion: int = 50) -> pd.DataFrame:
    """Los distritos con peor acceso ponderado por poblacion (poblacion minima
    para evitar que un distrito de 5 habitantes con mala suerte de ruteo
    domine el ranking)."""
    df = weighted_dist[weighted_dist["poblacion_total"] >= min_poblacion]
    return df.sort_values("t_min_ponderado", ascending=False).head(n).reset_index(drop=True)


def gini_access(access: pd.DataFrame, cap_min: float = 240.0) -> dict:
    """Gini poblacional del tiempo de acceso. Los puntos sin_ruta se topean en
    cap_min (no se excluyen: excluirlos subestimaria la desigualdad real,
    ya que son justamente los peor servidos)."""
    df = access.copy()
    df["t_min_capped"] = df["t_min"].fillna(cap_min).clip(upper=cap_min)
    df = df[df["poblacion"] > 0].sort_values("t_min_capped")

    w = df["poblacion"].to_numpy()
    x = df["t_min_capped"].to_numpy()
    cum_w = np.cumsum(w) / w.sum()
    cum_wx = np.cumsum(w * x) / (w * x).sum()
    cum_w = np.insert(cum_w, 0, 0)
    cum_wx = np.insert(cum_wx, 0, 0)
    gini = 1 - np.sum((cum_wx[1:] + cum_wx[:-1]) * np.diff(cum_w))

    return {
        "gini": float(gini),
        "cap_min_usado": cap_min,
        "n_puntos": len(df),
        "poblacion_total": float(w.sum()),
        "lorenz_cum_poblacion": cum_w.tolist(),
        "lorenz_cum_tiempo": cum_wx.tolist(),
    }


def urban_rural_contrast(access: pd.DataFrame) -> pd.DataFrame:
    valid = access[access["confiabilidad"] == "confiable"]

    def _wavg(g):
        w = g["poblacion"]
        return pd.Series(
            {
                "poblacion_total": w.sum(),
                "t_min_ponderado": np.average(g["t_min"], weights=w) if w.sum() > 0 else np.nan,
                "n_puntos": len(g),
            }
        )

    return valid.groupby(["departamento", "tipo_demanda"]).apply(_wavg).reset_index()


def cross_analysis_poblacion(access: pd.DataFrame) -> dict:
    """Cruce con una segunda dimension: tamano de poblacion del punto de
    demanda (proxy de ruralidad/aislamiento -- no tenemos pobreza/altitud
    descargadas en este proyecto, ver limitaciones en config.md). Se reporta
    la correlacion y una tabla por quintil de poblacion; se documenta como
    CORRELACIONAL, no causal (los asentamientos grandes atraen tanto vias
    como establecimientos -- variable de confusion plausible, no se puede
    descartar causalidad inversa con estos datos)."""
    valid = access[(access["confiabilidad"] == "confiable") & (access["poblacion"] > 0)].copy()
    valid["log_poblacion"] = np.log10(valid["poblacion"])

    corr_pearson = valid[["log_poblacion", "t_min"]].corr().iloc[0, 1]
    corr_spearman = valid[["log_poblacion", "t_min"]].corr(method="spearman").iloc[0, 1]

    valid["quintil_poblacion"] = pd.qcut(valid["poblacion"], 5, labels=[f"Q{i}" for i in range(1, 6)], duplicates="drop")

    def _wavg(g):
        w = g["poblacion"]
        return pd.Series({"poblacion_total": w.sum(), "t_min_ponderado": np.average(g["t_min"], weights=w), "poblacion_min": g["poblacion"].min(), "poblacion_max": g["poblacion"].max()})

    by_quintil = valid.groupby("quintil_poblacion", observed=True).apply(_wavg).reset_index()

    por_departamento = {
        dep: {
            "n": len(g),
            "pearson_logpob_tmin": float(g[["log_poblacion", "t_min"]].corr().iloc[0, 1]),
            "spearman_pob_tmin": float(g[["poblacion", "t_min"]].corr(method="spearman").iloc[0, 1]),
        }
        for dep, g in valid.groupby("departamento")
    }

    return {
        "correlacion_pearson_logpob_tmin": float(corr_pearson),
        "correlacion_spearman_pob_tmin": float(corr_spearman),
        "por_departamento": por_departamento,
        "interpretacion": (
            "Relacion debil en las 3 departamentos por separado (|r|<=0.12, verificado que no es un "
            "efecto Simpson por agregacion) -- el tamano de poblacion del centro poblado NO es un buen "
            "predictor del tiempo de acceso en estos datos. Aun si lo fuera, seria correlacional, no "
            "causal: es plausible que la causalidad vaya en ambos sentidos (los establecimientos y vias "
            "se ubican donde ya hay poblacion concentrada) -- no se puede identificar causalidad con "
            "datos observacionales de corte transversal como estos."
        ),
        "por_quintil_poblacion": by_quintil.to_dict(orient="records"),
    }


def coverage_pct(access: pd.DataFrame, threshold_min: float, t_min_col: str = "t_min") -> float:
    """% de poblacion (ponderada) con t_min_col <= threshold_min. sin_ruta/
    NaN nunca cuenta como cubierto, sea cual sea el umbral."""
    total = access["poblacion"].sum()
    if total == 0:
        return 0.0
    covered = access.loc[access[t_min_col] <= threshold_min, "poblacion"].sum()
    return covered / total


def weighted_median_access(access: pd.DataFrame, t_min_col: str = "t_min") -> float:
    """Mediana ponderada por poblacion del tiempo de acceso, solo sobre
    puntos con valor numerico (confiable)."""
    d = access.dropna(subset=[t_min_col]).sort_values(t_min_col)
    if len(d) == 0 or d["poblacion"].sum() == 0:
        return float("nan")
    cum = d["poblacion"].cumsum()
    cutoff = d["poblacion"].sum() / 2
    return float(d.loc[cum >= cutoff, t_min_col].iloc[0])


def simulate_facility_upgrade(access: pd.DataFrame, departamento: str, selected_facility_ids: list[str]) -> pd.DataFrame:
    """Fase 4 - simulador de escenarios: recalcula t_min de cada punto de
    demanda del departamento asumiendo que los facilities I-3/I-4
    seleccionados pasan a ser resolutivos. Usa la matriz demanda x
    candidatos precomputada en Fase 2b (matrix_<depto>_candidatos.parquet)
    -- nunca llama al motor de ruteo. Aplica la misma clasificacion de
    confiabilidad que build_access_table para no mezclar rutas absurdas."""
    dep_access = access[access["departamento"] == departamento].copy()
    dep_access["t_min_simulado"] = dep_access["t_min"]

    if not selected_facility_ids:
        return dep_access

    cand_matrix = pd.read_parquet(CACHE_DIR / f"matrix_{departamento.lower()}_candidatos.parquet")
    cand_matrix = cand_matrix[cand_matrix["facility_id"].isin(selected_facility_ids)].copy()
    cand_matrix["confiabilidad"] = classify_confiabilidad(cand_matrix)
    cand_matrix = cand_matrix[cand_matrix["confiabilidad"] == "confiable"]

    if len(cand_matrix) == 0:
        return dep_access

    best_cand = (cand_matrix.groupby("demand_id")["duration_s"].min() / 60.0).rename("t_min_candidato")
    dep_access = dep_access.merge(best_cand, on="demand_id", how="left")
    dep_access["t_min_simulado"] = dep_access[["t_min", "t_min_candidato"]].min(axis=1)
    return dep_access.drop(columns=["t_min_candidato"])


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

def run_all(force: bool = False):
    cfg = load_config()
    departamentos = list(cfg["departamentos"].values())
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    access = build_access_table_all(departamentos)
    access.to_csv(OUTPUTS_DIR / "access_table.csv", index=False)
    print(f"[metrics] access_table.csv: {len(access)} puntos de demanda ({access['poblacion'].sum():,.0f} hab.)")

    coverage_bands(access, group_col="departamento").to_csv(OUTPUTS_DIR / "coverage_bands_departamento.csv", index=False)
    coverage_bands(access, group_col=None).to_csv(OUTPUTS_DIR / "coverage_bands_total.csv", index=False)
    print("[metrics] coverage_bands_departamento.csv, coverage_bands_total.csv")

    for level, fname in [("dist", "access_por_distrito.csv"), ("prov", "access_por_provincia.csv"), ("dep", "access_por_departamento.csv")]:
        weighted_mean_access(access, level).to_csv(OUTPUTS_DIR / fname, index=False)
        print(f"[metrics] {fname}")

    weighted_dist = weighted_mean_access(access, "dist")
    critical_gap_list(weighted_dist).to_csv(OUTPUTS_DIR / "distritos_criticos.csv", index=False)
    print("[metrics] distritos_criticos.csv")

    gini_overall = gini_access(access)
    gini_by_dep = {dep: gini_access(access[access["departamento"] == dep]) for dep in departamentos}
    with open(OUTPUTS_DIR / "gini_lorenz.json", "w", encoding="utf-8") as f:
        json.dump({"total": gini_overall, "por_departamento": gini_by_dep}, f, indent=2, ensure_ascii=False)
    print(f"[metrics] gini_lorenz.json (Gini total = {gini_overall['gini']:.3f})")

    urban_rural_contrast(access).to_csv(OUTPUTS_DIR / "urbano_vs_rural.csv", index=False)
    print("[metrics] urbano_vs_rural.csv")

    cross = cross_analysis_poblacion(access)
    with open(OUTPUTS_DIR / "cruce_poblacion_acceso.json", "w", encoding="utf-8") as f:
        json.dump(cross, f, indent=2, ensure_ascii=False)
    print(
        f"[metrics] cruce_poblacion_acceso.json (correlacion Spearman poblacion-t_min = "
        f"{cross['correlacion_spearman_pob_tmin']:.3f})"
    )

    print()
    print("=== Resumen ===")
    for dep in departamentos:
        sub = access[access["departamento"] == dep]
        n_sin_ruta = (sub["confiabilidad"] == "sin_ruta").sum()
        n_no_conf = (sub["confiabilidad"] == "no_confiable").sum()
        pob_total = sub["poblacion"].sum()
        pob_sin_ruta = sub.loc[sub["confiabilidad"] == "sin_ruta", "poblacion"].sum()
        print(
            f"{dep}: {len(sub)} puntos ({pob_total:,.0f} hab.) | sin_ruta={n_sin_ruta} "
            f"({pob_sin_ruta:,.0f} hab., {pob_sin_ruta / pob_total:.1%}) | no_confiable={n_no_conf} | "
            f"Gini={gini_by_dep[dep]['gini']:.3f}"
        )


if __name__ == "__main__":
    run_all()
