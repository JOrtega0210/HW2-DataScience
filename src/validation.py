"""Fase 1b - reglas de calidad de datos y normalizacion de RENIPRESS.

Aplica las 6 reglas de validacion de config.md sobre los establecimientos
de salud de nuestros 3 departamentos, normaliza CATEGORIA/ESTADO a la
definicion de "resolutivo", y exporta:

  - data/processed/renipress_validado.parquet   (todos los registros, con
    columnas de flags; nada se descarta silenciosamente)
  - logs/data_quality_report.json               (conteos + decision tomada
    por cada regla)

Nota: NORTE/ESTE en el csv crudo de RENIPRESS son, pese al nombre (que
sugiere UTM), coordenadas decimales WGS84: NORTE = latitud, ESTE = longitud
(verificado contra el rango de Peru).
"""

import json
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from config import ROOT, load_config

RAW_RENIPRESS_DIR = ROOT / "data" / "raw" / "renipress"
RAW_BOUNDARIES_ADM3 = ROOT / "data" / "raw" / "boundaries" / "per_admin3.geojson"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORT_PATH = ROOT / "logs" / "data_quality_report.json"

ZERO_EPS = 0.001  # grados (~100m) - umbral para considerar una coordenada "cero/nula" en la practica
ESTADO_ACTIVO = "ACTIVO"
TEXT_COLUMNS_TO_CHECK_ENCODING = ["NOMBRE", "DIRECCION", "INSTITUCION", "PROVINCIA", "DISTRITO", "TIPO_ESTABLECIMIENTO"]


def load_renipress_raw() -> pd.DataFrame:
    csv_path = sorted(RAW_RENIPRESS_DIR.glob("RENIPRESS_*.csv"))[-1]
    df = pd.read_csv(csv_path, encoding="utf-8", sep=";")
    df.columns = [c.replace("﻿", "") for c in df.columns]
    return df


def normalize_categoria_estado(df: pd.DataFrame) -> pd.DataFrame:
    cfg = load_config()
    resolutivas = set(cfg["resolutivo"]["categorias"])

    df = df.copy()
    df["categoria_norm"] = df["CATEGORIA"].astype(str).str.strip().str.upper()
    # "0" es el valor que usa RENIPRESS para establecimientos a los que no
    # aplica la escala I-1..III-E (servicios de apoyo, sin internamiento, etc.)
    df.loc[df["categoria_norm"] == "0", "categoria_norm"] = "SIN_CATEGORIA"

    df["estado_norm"] = df["ESTADO"].astype(str).str.strip().str.upper()
    df["es_activo"] = df["estado_norm"] == ESTADO_ACTIVO
    df["es_resolutivo"] = df["categoria_norm"].isin(resolutivas) & df["es_activo"]
    return df


def rule_1_missing_or_zero_coords(df: pd.DataFrame) -> pd.Series:
    lat, lon = df["NORTE"], df["ESTE"]
    missing = lat.isna() | lon.isna()
    near_zero = lat.abs().lt(ZERO_EPS) & lon.abs().lt(ZERO_EPS)
    return missing | (near_zero & ~missing)


def rule_2_outside_bbox(df: pd.DataFrame, already_flagged: pd.Series) -> pd.Series:
    cfg = load_config()["bbox_peru"]
    lat, lon = df["NORTE"], df["ESTE"]
    in_bbox = lat.between(cfg["lat_min"], cfg["lat_max"]) & lon.between(cfg["lon_min"], cfg["lon_max"])
    return ~already_flagged & ~in_bbox


def rule_3_lat_lon_swapped(df: pd.DataFrame, already_flagged: pd.Series) -> pd.Series:
    cfg = load_config()["bbox_peru"]
    lat, lon = df["NORTE"], df["ESTE"]
    would_fit_swapped = lon.between(cfg["lat_min"], cfg["lat_max"]) & lat.between(cfg["lon_min"], cfg["lon_max"])
    return already_flagged & would_fit_swapped


def rule_4_outside_declared_district(df: pd.DataFrame, checkable: pd.Series) -> pd.Series:
    adm3 = gpd.read_file(RAW_BOUNDARIES_ADM3)[["adm3_pcode", "geometry"]]
    adm3["ubigeo"] = adm3["adm3_pcode"].str[2:]

    sub = df.loc[checkable, ["UBIGEO", "NORTE", "ESTE"]].copy()
    sub["ubigeo_str"] = sub["UBIGEO"].astype("Int64").astype(str).str.zfill(6)
    geom = [Point(xy) for xy in zip(sub["ESTE"], sub["NORTE"])]
    gdf = gpd.GeoDataFrame(sub, geometry=geom, crs="EPSG:4326")

    joined = gpd.sjoin(gdf, adm3, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    mismatch = (joined["ubigeo"] != joined["ubigeo_str"]) | joined["ubigeo"].isna()

    flags = pd.Series(False, index=df.index)
    flags.loc[mismatch.index] = mismatch
    return flags


def rule_5_duplicate_cod_ipress(df: pd.DataFrame) -> pd.Series:
    return df["COD_IPRESS"].duplicated(keep=False)


def rule_6_encoding_issues(df: pd.DataFrame) -> pd.Series:
    flag = pd.Series(False, index=df.index)
    for col in TEXT_COLUMNS_TO_CHECK_ENCODING:
        flag = flag | df[col].astype(str).str.contains("�", na=False)
    return flag


def validate_and_export(force: bool = False):
    dest = PROCESSED_DIR / "renipress_validado.parquet"
    if dest.exists() and not force:
        print(f"[validation] {dest.name} ya existe, se omite (force=True para regenerar).")
        return dest

    cfg = load_config()
    departamentos = list(cfg["departamentos"].values())

    df = load_renipress_raw()
    n_total_nacional = len(df)

    df = df[df["DEPARTAMENTO"].isin(departamentos)].reset_index(drop=True)
    n_total = len(df)

    df = normalize_categoria_estado(df)

    df["flag_coords_missing_or_zero"] = rule_1_missing_or_zero_coords(df)
    df["flag_coords_outside_bbox"] = rule_2_outside_bbox(df, df["flag_coords_missing_or_zero"])
    ya_flag_1_2 = df["flag_coords_missing_or_zero"] | df["flag_coords_outside_bbox"]
    df["flag_coords_swapped"] = rule_3_lat_lon_swapped(df, df["flag_coords_outside_bbox"])

    checkable = ~ya_flag_1_2
    df["flag_outside_declared_district"] = rule_4_outside_declared_district(df, checkable)
    df["flag_duplicate_cod_ipress"] = rule_5_duplicate_cod_ipress(df)
    df["flag_encoding_issue"] = rule_6_encoding_issues(df)

    # Coordenadas utilizables para ruteo (Fase 2): tienen que existir, estar
    # dentro del bbox, y no quedar marcadas como posiblemente invertidas.
    df["coords_utilizables"] = ~(df["flag_coords_missing_or_zero"] | df["flag_coords_outside_bbox"])

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    geom = [
        Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
        for lon, lat in zip(df["ESTE"], df["NORTE"])
    ]
    gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
    gdf.to_parquet(dest)
    print(f"[validation] {n_total} establecimientos de {departamentos} -> {dest}")

    report = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": str(sorted(RAW_RENIPRESS_DIR.glob("RENIPRESS_*.csv"))[-1].relative_to(ROOT)),
        "n_registros_nacional": n_total_nacional,
        "n_registros_3_departamentos": n_total,
        "departamentos": departamentos,
        "reglas": {
            "1_coords_missing_or_zero": {
                "descripcion": "Coordenadas nulas o efectivamente cero (|valor| < 0.001 grados)",
                "n_flagged": int(df["flag_coords_missing_or_zero"].sum()),
                "accion": "Se mantienen en el dataset (columna coords_utilizables=False); se excluyen del ruteo en Fase 2.",
            },
            "2_coords_outside_bbox": {
                "descripcion": "Coordenadas presentes pero fuera del bounding box de Peru",
                "n_flagged": int(df["flag_coords_outside_bbox"].sum()),
                "accion": "Se mantienen en el dataset (columna coords_utilizables=False); se excluyen del ruteo en Fase 2.",
            },
            "3_coords_swapped": {
                "descripcion": "De las marcadas fuera de bbox, cuantas caen dentro de Peru si se invierte lat/lon",
                "n_flagged": int(df["flag_coords_swapped"].sum()),
                "accion": "Ninguna encontrada en estos 3 departamentos; de existir, la correccion (invertir) queda pendiente de aplicar manualmente antes de usarse en ruteo.",
            },
            "4_outside_declared_district": {
                "descripcion": "El punto (cuando tiene coordenadas utilizables) no cae dentro del poligono del distrito que declara su propio UBIGEO",
                "n_flagged": int(df["flag_outside_declared_district"].sum()),
                "n_verificables": int(checkable.sum()),
                "accion": "Se mantienen en el dataset con la bandera activada; no se excluyen automaticamente (el distrito declarado puede ser correcto y el punto simplemente estar cerca del limite).",
            },
            "5_duplicate_cod_ipress": {
                "descripcion": "COD_IPRESS duplicado dentro de los 3 departamentos",
                "n_flagged": int(df["flag_duplicate_cod_ipress"].sum()),
                "accion": "Ninguno encontrado.",
            },
            "6_encoding_issues": {
                "descripcion": f"Caracter de reemplazo U+FFFD en columnas de texto ({', '.join(TEXT_COLUMNS_TO_CHECK_ENCODING)})",
                "n_flagged": int(df["flag_encoding_issue"].sum()),
                "accion": "Ninguno encontrado en RENIPRESS para estos 3 departamentos (si aparecieran, se mantendrian con la bandera activa; ver limites_administrativos.geojson que si presenta este problema, documentado en config.md).",
            },
        },
        "normalizacion_categoria": {
            "categoria_0_a_sin_categoria": int((df["categoria_norm"] == "SIN_CATEGORIA").sum()),
            "descripcion": "RENIPRESS usa el valor literal '0' quiere decir que no aplica la escala I-1..III-E (servicios de apoyo, sin internamiento). Se normaliza a 'SIN_CATEGORIA' y se trata como no resolutivo.",
        },
        "normalizacion_estado": {
            "valores_unicos_encontrados": sorted(df["estado_norm"].unique().tolist()),
            "descripcion": "ESTADO es un campo controlado (sin typos detectados); solo 'ACTIVO' cuenta como operativo para la definicion de resolutivo. El resto son variantes de cierre temporal/definitivo.",
        },
        "resolutivo": {
            dep: {
                "n_resolutivo": int(((df["DEPARTAMENTO"] == dep) & df["es_resolutivo"]).sum()),
                "n_resolutivo_coords_utilizables": int(
                    ((df["DEPARTAMENTO"] == dep) & df["es_resolutivo"] & df["coords_utilizables"]).sum()
                ),
            }
            for dep in departamentos
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[validation] Reporte de calidad de datos -> {REPORT_PATH}")

    return dest


if __name__ == "__main__":
    validate_and_export()
