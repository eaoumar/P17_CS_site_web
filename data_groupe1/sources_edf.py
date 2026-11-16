"""
Accès aux sources de données EDF pour le Groupe 1 (fiche centrale / réacteur).

- get_caracteristiques_centrales() : jeu public « Centrales de production
  nucléaire d'EDF SA » (OpenData EDF), une ligne par tranche.
- get_outages() : indisponibilités (API EDF, token requis), pas encore
  implémentée.
"""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"

CARACTERISTIQUES_DATASET = "centrales-de-production-nucleaire-edf"
CARACTERISTIQUES_URL = (
    "https://opendata.edf.fr/data-fair/api/v1/datasets/"
    f"{CARACTERISTIQUES_DATASET}/lines"
)
CARACTERISTIQUES_PAGE = f"https://opendata.edf.fr/datasets/{CARACTERISTIQUES_DATASET}"
CARACTERISTIQUES_TITRE = "OpenData EDF — Centrales de production nucléaire d'EDF SA"

PAGE_SIZE = 10000
TIMEOUT_S = 60


class SourceIndisponible(RuntimeError):
    """La source distante n'a pas pu être lue."""


def get_caracteristiques_centrales() -> pd.DataFrame:
    """
    Télécharge toutes les tranches du jeu public EDF, en suivant la
    pagination data-fair (champ "next"), et met la réponse brute en cache
    dans data_groupe1/cache/.

    Renvoie un DataFrame (une ligne par tranche) avec une colonne
    "date_recuperation" (AAAA-MM-JJ). Lève SourceIndisponible si l'API ne
    répond pas correctement : aucun repli silencieux sur le cache.
    """
    results = []
    url = CARACTERISTIQUES_URL
    params = {"size": PAGE_SIZE}
    total = None

    try:
        while url:
            resp = requests.get(url, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            payload = resp.json()
            total = payload.get("total", total)
            results.extend(payload.get("results", []))
            url = payload.get("next")  # URL complète de la page suivante
            params = None              # déjà incluse dans "next"
    except (requests.RequestException, ValueError) as exc:
        raise SourceIndisponible(
            f"API OpenData EDF inaccessible ({CARACTERISTIQUES_URL}) : {exc}"
        ) from exc

    if not results:
        raise SourceIndisponible("API OpenData EDF : réponse vide (0 tranche).")
    if total is not None and len(results) != total:
        raise SourceIndisponible(
            f"API OpenData EDF : {len(results)} lignes reçues pour total={total}."
        )

    recupere_le = date.today().isoformat()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"caracteristiques_centrales_{recupere_le}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": CARACTERISTIQUES_URL,
                "recupere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "total": total,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    df = pd.DataFrame(results)
    df["date_recuperation"] = recupere_le
    return df


# ─── Indisponibilités EDF ─────────────────────────────────────────────────────

ROOT = HERE.parent
OUTAGES_CSV = ROOT / "donnees_edf.csv"
OUTAGES_DATASET_ID = "4wsb2p5ghkbutlyrnqjmgazo"
OUTAGES_TITRE = "OpenData EDF — Indisponibilités des moyens de production de EDF SA"
OUTAGES_PAGE = "https://opendata.edf.fr/datasets/indisponibilites-des-moyens-de-production-edf-sa"

# Correspondance colonnes CSV (format lu par convert.load_outages) -> noms API.
CSV_VERS_API = {
    "outage_begin_dt (UTC)": "outage_begin_dt_utc",
    "outage_end_dt (UTC)": "outage_end_dt_utc",
    "available capacity (MW)": "available_capacity_mw",
    "nominal capacity (MW)": "nominal_capacity_mw",
}


def _convert_module():
    """Importe convert.py (racine du projet) sans exécuter son main()."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import convert  # noqa: E402
    return convert


def _base_id(publication_id: str) -> str:
    """
    '-EDF-...-00010073_002' -> '-EDF-...-00010073'.
    Dans l'API, le suffixe _NNN est le numéro de version : sans le retirer,
    chaque version a un publication_id différent et aucune n'est dédoublonnée.
    """
    import re
    return re.sub(r"_\d{3}$", "", publication_id)


def get_outages(dedup: str = "base_id"):
    """
    Indisponibilités nucléaires EDF filtrées, une ligne par événement.

    Source : API (fetch_outages_raw de convert.py) si un token existe,
    sinon donnees_edf.csv à la racine s'il est présent, sinon erreur claire.

    Filtrage identique à convert.py :
      - dernière version par publication ;
      - statuts EXCLUDED_STATUSES ou contenant « annul » exclus ;
      - unit_name vide, dates invalides ou fin <= début exclus ;
      - (API) nominal_capacity_mw nul exclu.
    dedup="base_id" (défaut) : publication = publication_id sans suffixe _NNN.
    dedup="publication_id"   : clé brute, exactement comme convert.py.

    Renvoie (DataFrame, meta) avec meta = {source, libelle, url, recupere_le,
    nb_bruts, nb_retenus, dedup}. Colonnes : unit_name, begin, end (datetime UTC),
    available_capacity_mw, nominal_capacity_mw, outage_type, outage_status,
    outage_cause, publication_id, version.
    """
    if dedup not in ("base_id", "publication_id"):
        raise ValueError("dedup doit valoir 'base_id' ou 'publication_id'")
    convert = _convert_module()

    cwd = os.getcwd()
    os.chdir(ROOT)  # get_api_token lit api_config.json dans le répertoire courant
    try:
        token = convert.get_api_token()
    finally:
        os.chdir(cwd)

    recupere_le = date.today().isoformat()
    if token:
        try:
            records = convert.fetch_outages_raw(token)
        except Exception as exc:
            raise SourceIndisponible(f"API indisponibilités EDF inaccessible : {exc}") from exc
        source, libelle = "api", f"{OUTAGES_TITRE}, API"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_DIR / f"indisponibilites_brutes_{recupere_le}.json", "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
    elif OUTAGES_CSV.exists():
        import csv
        with open(OUTAGES_CSV, encoding="utf-8-sig", newline="") as f:
            records = [{CSV_VERS_API.get(k, k): v for k, v in row.items()} for row in csv.DictReader(f)]
        if records and "outage_type" not in records[0]:
            raise SourceIndisponible(f"{OUTAGES_CSV.name} n'a pas de colonne outage_type.")
        source, libelle = "csv", f"{OUTAGES_TITRE}, fichier {OUTAGES_CSV.name}"
        recupere_le = date.fromtimestamp(OUTAGES_CSV.stat().st_mtime).isoformat()
    else:
        raise SourceIndisponible(
            "Aucune source d'indisponibilités : ni token EDF (api_config.json ou "
            f"EDF_API_TOKEN) ni fichier {OUTAGES_CSV.name}."
        )

    # Dernière version par publication
    best = {}
    for r in records:
        pub = str(r.get("publication_id", "")).strip()
        if not pub:
            continue
        cle = _base_id(pub) if dedup == "base_id" else pub
        try:
            ver = int(r.get("version") or 0)
        except (ValueError, TypeError):
            ver = 0
        if ver > best.get(cle, (-1, None))[0]:
            best[cle] = (ver, r)

    def num(v):
        try:
            return float(v or 0)
        except (ValueError, TypeError):
            return 0.0

    lignes = []
    for ver, r in best.values():
        status = str(r.get("outage_status", "")).strip()
        if status in convert.EXCLUDED_STATUSES or "annul" in status.lower():
            continue
        unit = str(r.get("unit_name", "")).strip()
        if not unit:
            continue
        begin = convert.parse_dt(str(r.get("outage_begin_dt_utc", "")))
        end = convert.parse_dt(str(r.get("outage_end_dt_utc", "")))
        if not begin or not end or end <= begin:
            continue
        nominal = num(r.get("nominal_capacity_mw"))
        if source == "api" and nominal == 0:
            continue
        lignes.append({
            "unit_name": unit,
            "begin": begin,
            "end": end,
            "available_capacity_mw": num(r.get("available_capacity_mw")),
            "nominal_capacity_mw": nominal,
            "outage_type": str(r.get("outage_type", "")).strip(),
            "outage_status": status,
            "outage_cause": str(r.get("outage_cause", "")).strip(),
            "publication_id": str(r.get("publication_id", "")).strip(),
            "version": ver,
        })

    meta = {
        "source": source,
        "libelle": libelle,
        "url": OUTAGES_PAGE,
        "recupere_le": recupere_le,
        "nb_bruts": len(records),
        "nb_retenus": len(lignes),
        "dedup": dedup,
        # Date de la publication la plus récente : au-delà, les arrêts fortuits
        # ne sont pas connus.
        "derniere_publication": max(
            (str(r.get("publication_dt_utc") or "")[:10] for r in records), default=None) or None,
    }
    return pd.DataFrame(lignes), meta
