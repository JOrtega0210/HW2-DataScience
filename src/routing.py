"""Fase 2a - ruteo piloto: matriz origen (demanda) x destino (facility resolutiva) via OSRM.

Requiere el servidor OSRM corriendo localmente (ver README.md, seccion
"Motor de ruteo"). Consulta /table por lotes (para no exceder limites de
URL), cachea cada lote en Parquet, y no vuelve a pedir lo que ya tiene en
cache. Tambien compara distancia recta (haversine) vs. tiempo/distancia
por red para el facility mas cercano de cada punto de demanda.
"""

import json
import math
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from config import ROOT, load_config

OSRM_BASE = "http://localhost:{port}"
CACHE_DIR = ROOT / "data" / "processed" / "routing_cache"
BATCH_SIZE = 150  # puntos de demanda por consulta /table (mantiene la URL en un tamano razonable)


def _osrm_url(port: int) -> str:
    return OSRM_BASE.format(port=port)


def check_osrm_up(port: int) -> bool:
    try:
        r = requests.get(f"{_osrm_url(port)}/route/v1/driving/-77.0428,-12.0464;-77.1465,-11.9950", timeout=5)
        return r.status_code == 200 and r.json().get("code") == "Ok"
    except requests.exceptions.RequestException:
        return False


def load_demand_points(departamento: str) -> gpd.GeoDataFrame:
    dep_lower = departamento.lower()

    dispersos_path = ROOT / "data" / "raw" / "centros_poblados" / f"centros_poblados_dispersos_{dep_lower}.geojson"
    dispersos = gpd.read_file(dispersos_path)
    dispersos = dispersos.rename(columns={"cod_dist": "ubigeo", "pob_total": "poblacion"})
    dispersos["tipo_demanda"] = "disperso"
    dispersos["demand_id"] = "D" + dispersos["cod_ccpp"].astype(str)
    dispersos = dispersos[["demand_id", "ubigeo", "poblacion", "tipo_demanda", "geometry"]]

    urbano_path = ROOT / "data" / "processed" / "demand_points_urbano.geojson"
    urbano = gpd.read_file(urbano_path)
    urbano = urbano[urbano["dep"].str.upper() == departamento.upper()].copy()
    urbano = urbano.rename(columns={"pob_urbana_estimada": "poblacion"})
    urbano["tipo_demanda"] = "urbano"
    urbano["demand_id"] = "U" + urbano["ubigeo"].astype(str)
    urbano = urbano[["demand_id", "ubigeo", "poblacion", "tipo_demanda", "geometry"]]

    demand = pd.concat([dispersos, urbano], ignore_index=True)
    demand = gpd.GeoDataFrame(demand, geometry="geometry", crs="EPSG:4326")
    demand = demand[demand["poblacion"].fillna(0) > 0].reset_index(drop=True)
    return demand


def load_supply_points(departamento: str) -> gpd.GeoDataFrame:
    renipress_path = ROOT / "data" / "processed" / "renipress_validado.parquet"
    df = gpd.read_parquet(renipress_path)
    supply = df[
        (df["DEPARTAMENTO"].str.upper() == departamento.upper())
        & df["es_resolutivo"]
        & df["coords_utilizables"]
    ].copy()
    supply["facility_id"] = "F" + supply["COD_IPRESS"].astype(str)
    supply = supply[["facility_id", "COD_IPRESS", "NOMBRE", "categoria_norm", "geometry"]]
    return supply.reset_index(drop=True)


def load_candidate_points(departamento: str) -> gpd.GeoDataFrame:
    """Establecimientos I-3/I-4 activos (no resolutivos hoy, pero candidatos
    plausibles a 'upgrade' -- son los que ya tienen mas capacidad dentro de
    la escala no-resolutiva). Usado por el simulador de escenarios (Fase 4)."""
    renipress_path = ROOT / "data" / "processed" / "renipress_validado.parquet"
    df = gpd.read_parquet(renipress_path)
    cand = df[
        (df["DEPARTAMENTO"].str.upper() == departamento.upper())
        & df["categoria_norm"].isin(["I-3", "I-4"])
        & df["es_activo"]
        & df["coords_utilizables"]
    ].copy()
    cand["facility_id"] = "F" + cand["COD_IPRESS"].astype(str)
    cand = cand[["facility_id", "COD_IPRESS", "NOMBRE", "categoria_norm", "geometry"]]
    return cand.reset_index(drop=True)


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _query_table_batch(port: int, demand_batch: gpd.GeoDataFrame, supply: gpd.GeoDataFrame) -> pd.DataFrame:
    coords = [f"{p.x},{p.y}" for p in demand_batch.geometry] + [f"{p.x},{p.y}" for p in supply.geometry]
    n_demand = len(demand_batch)
    n_supply = len(supply)
    sources = ";".join(str(i) for i in range(n_demand))
    destinations = ";".join(str(i) for i in range(n_demand, n_demand + n_supply))

    url = f"{_osrm_url(port)}/table/v1/driving/{';'.join(coords)}"
    params = {"sources": sources, "destinations": destinations, "annotations": "duration,distance"}
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM /table fallo: {data.get('code')} - {data.get('message')}")

    rows = []
    src_meta = data["sources"]
    dst_meta = data["destinations"]
    for i, demand_row in enumerate(demand_batch.itertuples()):
        snap_dist_demand = src_meta[i]["distance"] if src_meta[i] else None
        for j, supply_row in enumerate(supply.itertuples()):
            duration_s = data["durations"][i][j]
            distance_m = data["distances"][i][j]
            snap_dist_supply = dst_meta[j]["distance"] if dst_meta[j] else None
            straight_m = _haversine_m(
                demand_row.geometry.x, demand_row.geometry.y, supply_row.geometry.x, supply_row.geometry.y
            )
            rows.append(
                {
                    "demand_id": demand_row.demand_id,
                    "facility_id": supply_row.facility_id,
                    "duration_s": duration_s,
                    "distance_m": distance_m,
                    "straight_line_m": straight_m,
                    "snap_dist_demand_m": snap_dist_demand,
                    "snap_dist_supply_m": snap_dist_supply,
                }
            )
    return pd.DataFrame(rows)


def build_matrix(departamento: str, port: int = None, force: bool = False, candidatos: bool = False) -> Path:
    """candidatos=True construye la matriz demanda x I-3/I-4 (para el
    simulador de escenarios de Fase 4) en vez de demanda x resolutivas."""
    cfg = load_config()
    port = port or cfg["routing"]["car_port"]
    dep_lower = departamento.lower()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_candidatos" if candidatos else ""
    dest = CACHE_DIR / f"matrix_{dep_lower}{suffix}.parquet"

    if dest.exists() and not force:
        print(f"[routing] {dest.name} ya existe, se omite (force=True para regenerar).")
        return dest

    if not check_osrm_up(port):
        raise RuntimeError(
            f"OSRM no responde en el puerto {port}. Levantar el servidor (ver README.md, seccion 'Motor de ruteo')."
        )

    demand = load_demand_points(departamento)
    supply = load_candidate_points(departamento) if candidatos else load_supply_points(departamento)
    tipo_oferta = "candidatas (I-3/I-4)" if candidatos else "resolutivas"
    print(f"[routing] {departamento}: {len(demand)} puntos de demanda, {len(supply)} facilities {tipo_oferta}")

    if len(supply) == 0:
        raise RuntimeError(f"No hay facilities {tipo_oferta} con coordenadas utilizables en {departamento}.")

    batches = [demand.iloc[i : i + BATCH_SIZE] for i in range(0, len(demand), BATCH_SIZE)]
    all_rows = []
    t0 = time.time()
    for i, batch in enumerate(batches, start=1):
        batch_df = _query_table_batch(port, batch, supply)
        all_rows.append(batch_df)
        elapsed = time.time() - t0
        print(f"[routing] lote {i}/{len(batches)} ({len(batch)} puntos) OK - {elapsed:.1f}s transcurridos")

    matrix = pd.concat(all_rows, ignore_index=True)
    snap_max = cfg["routing"]["snap_confiable_max_m"]
    # snap_confiable es a nivel de PAR (demanda, facility): solo True si ambos
    # extremos snappean cerca de una via mapeada. Para el diagnostico "cuantos
    # PUNTOS DE DEMANDA tienen mala calidad de snap" (independiente de que
    # facility le toque emparejado), ver summarize_nearest() -- ahi se agrupa
    # solo por snap_dist_demand_m, sin mezclar el snap del lado de la oferta.
    matrix["snap_confiable"] = (matrix["snap_dist_demand_m"] <= snap_max) & (matrix["snap_dist_supply_m"] <= snap_max)
    matrix.to_parquet(dest)
    print(f"[routing] matriz completa: {len(matrix)} filas ({len(demand)} demanda x {len(supply)} facilities) -> {dest}")
    return dest


def summarize_nearest(departamento: str, write_report: bool = True) -> pd.DataFrame:
    """Para cada punto de demanda: facility mas cercano por red vs. por linea recta, y si difieren."""
    dep_lower = departamento.lower()
    matrix = pd.read_parquet(CACHE_DIR / f"matrix_{dep_lower}.parquet")

    routable = matrix.dropna(subset=["duration_s"])
    unroutable_pairs = int(matrix["duration_s"].isna().sum())

    nearest_red = routable.loc[routable.groupby("demand_id")["duration_s"].idxmin()]
    nearest_recta = matrix.loc[matrix.groupby("demand_id")["straight_line_m"].idxmin()]

    cmp = nearest_red[["demand_id", "facility_id", "duration_s", "distance_m"]].merge(
        nearest_recta[["demand_id", "facility_id", "straight_line_m"]],
        on="demand_id",
        suffixes=("_red", "_recta"),
    )
    cmp["coincide"] = cmp["facility_id_red"] == cmp["facility_id_recta"]
    cmp["detour_factor"] = cmp["distance_m"] / cmp["straight_line_m"].replace(0, pd.NA)

    n_demand_sin_ninguna_ruta = matrix["demand_id"].nunique() - routable["demand_id"].nunique()

    demand_snap = matrix.groupby("demand_id")["snap_dist_demand_m"].first()
    supply_snap = matrix.groupby("facility_id")["snap_dist_supply_m"].first()
    snap_max = load_config()["routing"]["snap_confiable_max_m"]
    n_demand_snap_no_confiable = int((demand_snap > snap_max).sum())

    print(f"[routing] {departamento}: {len(cmp)} puntos con al menos una ruta valida")
    print(f"[routing]   pares demanda-facility sin ruta (islas / red no conectada): {unroutable_pairs}")
    print(f"[routing]   puntos de demanda sin NINGUNA ruta valida a ninguna facility: {n_demand_sin_ninguna_ruta}")
    print(f"[routing]   coincide facility mas cercano (red == linea recta): {cmp['coincide'].mean():.1%}")
    print(f"[routing]   factor de desvio promedio (distancia_red / distancia_recta): {cmp['detour_factor'].mean():.2f}")
    print(
        f"[routing]   snap demanda: media {demand_snap.mean():.0f}m, mediana {demand_snap.median():.0f}m, "
        f"p99 {demand_snap.quantile(0.99):.0f}m, max {demand_snap.max():.0f}m ({demand_snap.isna().sum()} fallidos)"
    )
    print(
        f"[routing]   snap facilities: media {supply_snap.mean():.0f}m, max {supply_snap.max():.0f}m "
        f"({supply_snap.isna().sum()} fallidos)"
    )
    print(
        f"[routing]   puntos de demanda con snap > {snap_max}m (sin via mapeada cercana, poca confianza en "
        f"el tiempo de auto): {n_demand_snap_no_confiable} ({n_demand_snap_no_confiable / len(demand_snap):.1%})"
    )

    if write_report:
        report = {
            "departamento": departamento,
            "n_demanda": int(matrix["demand_id"].nunique()),
            "n_facilities": int(matrix["facility_id"].nunique()),
            "n_pares_matriz": len(matrix),
            "pares_sin_ruta": unroutable_pairs,
            "puntos_demanda_sin_ninguna_ruta": int(n_demand_sin_ninguna_ruta),
            "snapping": {
                "demanda_media_m": float(demand_snap.mean()),
                "demanda_mediana_m": float(demand_snap.median()),
                "demanda_p99_m": float(demand_snap.quantile(0.99)),
                "demanda_max_m": float(demand_snap.max()),
                "demanda_fallidos": int(demand_snap.isna().sum()),
                "demanda_snap_no_confiable_m": snap_max,
                "demanda_n_snap_no_confiable": n_demand_snap_no_confiable,
                "demanda_pct_snap_no_confiable": n_demand_snap_no_confiable / len(demand_snap),
                "facilities_media_m": float(supply_snap.mean()),
                "facilities_max_m": float(supply_snap.max()),
                "facilities_fallidos": int(supply_snap.isna().sum()),
            },
            "comparacion_recta_vs_red": {
                "coincide_facility_mas_cercano_pct": float(cmp["coincide"].mean()),
                "factor_desvio_promedio": float(cmp["detour_factor"].mean()),
                "factor_desvio_mediana": float(cmp["detour_factor"].median()),
            },
        }
        report_path = ROOT / "logs" / f"routing_report_{dep_lower}.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[routing] Reporte -> {report_path}")

    return cmp


if __name__ == "__main__":
    import sys

    dep = sys.argv[1] if len(sys.argv) > 1 else load_config()["departamentos"]["costa"]
    build_matrix(dep)
    summarize_nearest(dep)
