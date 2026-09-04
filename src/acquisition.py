"""Fase 1a - descarga RENIPRESS, limites administrativos y centros poblados hacia data/raw/.

Re-ejecutable: cada funcion se salta la descarga si el archivo destino ya
existe (usar force=True para forzar). Cada descarga exitosa se registra en
logs/download_manifest.json con URL, fecha y tamano.
"""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import ROOT, load_config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/octet-stream,application/json,*/*",
    "Accept-Language": "es-PE,es;q=0.9",
}
# datosabiertos.gob.pe corre detras de un WAF que devuelve 418 sin un
# Referer que apunte a la propia pagina del dataset.
RENIPRESS_REFERER = "https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress"
MANIFEST_PATH = ROOT / "logs" / "download_manifest.json"


def _read_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def _write_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _record(key: str, **fields) -> None:
    manifest = _read_manifest()
    manifest[key] = {**fields, "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write_manifest(manifest)


def download_renipress(force: bool = False) -> Path:
    cfg = load_config()
    url = cfg["fuentes"]["renipress_url"]
    dest_dir = ROOT / "data" / "raw" / "renipress"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]

    if dest.exists() and not force:
        print(f"[acquisition] RENIPRESS ya existe ({dest.name}), se omite descarga.")
        return dest

    print(f"[acquisition] Descargando RENIPRESS desde {url} ...")
    resp = requests.get(url, headers={**HEADERS, "Referer": RENIPRESS_REFERER}, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"[acquisition] RENIPRESS guardado en {dest} ({len(resp.content) / 1e6:.1f} MB)")

    _record(
        "renipress",
        url=url,
        local_path=dest.relative_to(ROOT).as_posix(),
        size_bytes=len(resp.content),
        publisher="SUSALUD (via datosabiertos.gob.pe)",
    )
    return dest


def download_admin_boundaries(force: bool = False) -> Path:
    cfg = load_config()
    url = cfg["fuentes"]["admin_boundaries_url"]
    dest_dir = ROOT / "data" / "raw" / "boundaries"
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "per_admin_boundaries.geojson.zip"

    downloaded = not zip_path.exists() or force
    if downloaded:
        print(f"[acquisition] Descargando limites administrativos desde {url} ...")
        with requests.get(url, headers=HEADERS, timeout=300, stream=True) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        print(f"[acquisition] Limites guardados en {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"[acquisition] Limites administrativos ya existen ({zip_path.name}), se omite descarga.")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        missing = [n for n in names if not (dest_dir / n).exists()]
        if missing or force:
            zf.extractall(dest_dir)
            print(f"[acquisition] Extraidos {len(names)} archivos en {dest_dir}")

    if downloaded:
        _record(
            "admin_boundaries",
            url=url,
            local_path=zip_path.relative_to(ROOT).as_posix(),
            size_bytes=zip_path.stat().st_size,
            publisher="Instituto Geografico Nacional (IGN), via OCHA/HDX COD-AB",
            levels="departamento (25), provincia (196), distrito (1873)",
        )
    return zip_path


def _query_centros_poblados_dispersos(url: str, departamento: str) -> list[dict]:
    features: list[dict] = []
    offset = 0
    page_size = 2000
    while True:
        params = {
            "where": f"nom_dpto='{departamento}'",
            "outFields": "cod_dpto,nom_dpto,cod_prov,nom_prov,cod_dist,nom_dist,cod_ccpp,nom_ccpp,pob_total,Longitud,Latitud",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        page = resp.json().get("features", [])
        features.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return features


def download_centros_poblados_dispersos(force: bool = False) -> list[Path]:
    cfg = load_config()
    url = cfg["fuentes"]["centros_poblados_dispersos_query_url"]
    dest_dir = ROOT / "data" / "raw" / "centros_poblados"
    dest_dir.mkdir(parents=True, exist_ok=True)

    departamentos = list(cfg["departamentos"].values())
    paths = []
    for dep in departamentos:
        dest = dest_dir / f"centros_poblados_dispersos_{dep.lower()}.geojson"
        if dest.exists() and not force:
            print(f"[acquisition] Centros poblados de {dep} ya existen ({dest.name}), se omite.")
            paths.append(dest)
            continue

        print(f"[acquisition] Consultando centros poblados dispersos de {dep} ...")
        features = _query_centros_poblados_dispersos(url, dep)
        geojson = {"type": "FeatureCollection", "features": features}
        dest.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
        total_pob = sum((f["properties"].get("pob_total") or 0) for f in features)
        print(f"[acquisition] {dep}: {len(features)} centros poblados dispersos, poblacion total {total_pob}")

        _record(
            f"centros_poblados_dispersos_{dep.lower()}",
            url=url,
            local_path=dest.relative_to(ROOT).as_posix(),
            n_features=len(features),
            poblacion_total_dispersa=total_pob,
            publisher="INEI, via geoportal IDEP (ArcGIS REST)",
            limitacion="Solo cubre centros poblados dispersos (rurales); no incluye poblacion urbana concentrada.",
        )
        paths.append(dest)
    return paths


def _query_capitales_distritales(url: str, departamento: str) -> list[dict]:
    features: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        params = {
            "where": f"DEP='{departamento}' AND CATEGORIA='Capital de Distrito'",
            "outFields": "*",
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        page = resp.json().get("features", [])
        features.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return features


def download_capitales_distritales(force: bool = False) -> list[Path]:
    """Puntos 'Capital de Distrito' del gazetteer nacional IGN (usados como ancla del punto de demanda urbano)."""
    cfg = load_config()
    url = cfg["fuentes"]["capitales_distritales_query_url"]
    dest_dir = ROOT / "data" / "raw" / "centros_poblados"
    dest_dir.mkdir(parents=True, exist_ok=True)

    departamentos = list(cfg["departamentos"].values())
    paths = []
    for dep in departamentos:
        dest = dest_dir / f"capitales_distritales_{dep.lower()}.geojson"
        if dest.exists() and not force:
            print(f"[acquisition] Capitales distritales de {dep} ya existen ({dest.name}), se omite.")
            paths.append(dest)
            continue

        print(f"[acquisition] Consultando capitales distritales de {dep} ...")
        features = _query_capitales_distritales(url, dep)
        geojson = {"type": "FeatureCollection", "features": features}
        dest.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
        print(f"[acquisition] {dep}: {len(features)} capitales distritales")

        _record(
            f"capitales_distritales_{dep.lower()}",
            url=url,
            local_path=dest.relative_to(ROOT).as_posix(),
            n_features=len(features),
            publisher="Instituto Geografico Nacional (IGN), via geoportal IDEP (ArcGIS REST)",
        )
        paths.append(dest)
    return paths


def download_poblacion_distrital(force: bool = False) -> Path:
    """Poblacion total proyectada por distrito (INEI), usada para estimar poblacion urbana = total - dispersa."""
    cfg = load_config()
    url = cfg["fuentes"]["poblacion_distrital_url"]
    dest_dir = ROOT / "data" / "raw" / "poblacion"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "poblacion_distrital_proyectada_2018_2026.xlsx"

    if dest.exists() and not force:
        print(f"[acquisition] Poblacion distrital ya existe ({dest.name}), se omite descarga.")
        return dest

    print(f"[acquisition] Descargando poblacion distrital desde {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"[acquisition] Poblacion distrital guardada en {dest} ({len(resp.content) / 1e6:.1f} MB)")

    _record(
        "poblacion_distrital",
        url=url,
        local_path=dest.relative_to(ROOT).as_posix(),
        size_bytes=len(resp.content),
        publisher="INEI - Estimaciones y Proyecciones de Poblacion",
        anio=cfg["fuentes"]["poblacion_distrital_anio"],
    )
    return dest


def download_all(force: bool = False) -> None:
    download_renipress(force=force)
    download_admin_boundaries(force=force)
    download_centros_poblados_dispersos(force=force)
    download_capitales_distritales(force=force)
    download_poblacion_distrital(force=force)
    print("[acquisition] Fase 1a completa. Ver logs/download_manifest.json para el detalle.")


if __name__ == "__main__":
    download_all()
