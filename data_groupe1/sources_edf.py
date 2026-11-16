"""
Accès aux sources de données EDF pour le Groupe 1 (fiche centrale / réacteur).

- get_caracteristiques_centrales() : jeu public « Centrales de production
  nucléaire d'EDF SA » (OpenData EDF), une ligne par tranche.
- get_outages() : indisponibilités (API EDF, token requis), pas encore
  implémentée.
"""

import json
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


def get_outages():
    """Indisponibilités EDF (API avec token). À implémenter quand le token sera fourni."""
    raise NotImplementedError("token EDF requis")
