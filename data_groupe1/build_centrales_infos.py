"""
Génère src/assets/centrales_infos.json : fiche d'informations par réacteur
et agrégats par centrale, pour le panneau centrale (Groupe 1).

Entrées :
  - data_groupe1/correspondance_reacteurs.csv (build_correspondance.py)
  - src/assets/units.json (liste des réacteurs affichés sur la carte)
  - OpenData EDF « Centrales de production nucléaire d'EDF SA » (API publique)
  - [plus tard] indisponibilités EDF (token requis) pour les indicateurs d'arrêts

Règles :
  - aucune valeur sans source ; valeur inconnue = null (jamais 0, jamais inventée) ;
  - si l'API des caractéristiques est inaccessible : arrêt, fichier non écrasé.

Lancement (depuis la racine du projet) :
  python data_groupe1/build_correspondance.py
  python data_groupe1/build_centrales_infos.py
"""

import csv
import json
import math
import os
import re
import sys
from pathlib import Path

from sources_edf import (
    CARACTERISTIQUES_PAGE,
    CARACTERISTIQUES_TITRE,
    SourceIndisponible,
    get_caracteristiques_centrales,
    get_outages,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UNITS_JSON = ROOT / "src" / "assets" / "units.json"
CORRESPONDANCE_CSV = HERE / "correspondance_reacteurs.csv"
OUT_JSON = ROOT / "src" / "assets" / "centrales_infos.json"

COL_RESERVE = "_reserves_secondaires-par-tranche.reserve_secondaire_maximale"


# ─── Utilitaires ──────────────────────────────────────────────────────────────

def propre(v):
    """NaN/None/'' -> None ; float entier -> int ; sinon valeur inchangée."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return int(v) if v.is_integer() else v
    if isinstance(v, str) and not v.strip():
        return None
    if hasattr(v, "item"):  # types numpy
        return propre(v.item())
    return v


def palier(sous_filiere):
    """'Réacteur à eau pressurisée (REP) 1300' -> 'REP 1300'. None si absent."""
    sous_filiere = propre(sous_filiere)
    if sous_filiere is None:
        return None
    m = re.search(r"\(REP\)\s*(\d+)", str(sous_filiere))
    return f"REP {m.group(1)}" if m else str(sous_filiere)


def date_iso(v):
    v = propre(v)
    if v is None:
        return None
    v = str(v)[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def somme_ou_null(valeurs):
    """Somme si toutes les valeurs sont connues, sinon None (pas de total partiel)."""
    return None if any(v is None for v in valeurs) or not valeurs else sum(valeurs)


def min_ou_null(valeurs):
    return None if any(v is None for v in valeurs) or not valeurs else min(valeurs)


def lire_correspondance():
    if not CORRESPONDANCE_CSV.exists():
        raise FileNotFoundError(
            f"{CORRESPONDANCE_CSV.relative_to(ROOT)} introuvable : "
            "lancer d'abord python data_groupe1/build_correspondance.py"
        )
    with open(CORRESPONDANCE_CSV, encoding="utf-8", newline="") as f:
        return {row["nom_units_json"]: row for row in csv.DictReader(f)}


# ─── Indicateurs d'arrêts (emplacement prévu) ─────────────────────────────────

def calculer_indicateurs(noms_reacteurs):
    """
    Renvoie {nom_units_json: {"arrets_par_an": ..., "jours_arret": ..., "source": ...}}.

    À implémenter quand get_outages() sera disponible (token EDF) :
      - filtrer les indisponibilités par réacteur (colonne unit_name_api_indispo) ;
      - définir précisément « arrêt » (outage_type, puissance disponible = 0 ?) ;
      - agréger par année civile.
    Tant que la source n'est pas disponible : avertissement et dictionnaire vide.
    """
    try:
        outages = get_outages()
    except NotImplementedError as exc:
        print(f"AVERTISSEMENT : indicateurs d'arrêts non calculés ({exc}). "
              "arrets_par_an et jours_arret restent null.")
        return {}
    raise NotImplementedError("Calcul des indicateurs à écrire avec les données d'indisponibilité.")  # pragma: no cover


# ─── Construction ─────────────────────────────────────────────────────────────

def construire():
    with open(UNITS_JSON, encoding="utf-8") as f:
        units = json.load(f)
    corresp = lire_correspondance()

    edf = get_caracteristiques_centrales()  # lève SourceIndisponible si KO
    recupere_le = edf["date_recuperation"].iloc[0]
    edf_par_tranche = {row["tranche"]: row for row in edf.to_dict(orient="records")}
    source_carac = (
        f"{CARACTERISTIQUES_TITRE} ({CARACTERISTIQUES_PAGE}), récupéré le {recupere_le}"
    )

    indicateurs = calculer_indicateurs([u["unit"] for u in units])

    reacteurs = {}
    ecarts = []
    for u in units:
        nom = u["unit"]
        ligne = corresp.get(nom)
        if ligne is None:
            raise ValueError(f"{nom} absent de correspondance_reacteurs.csv : relancer build_correspondance.py")
        rec = edf_par_tranche.get(ligne["nom_edf_opendata"]) if ligne["nom_edf_opendata"] else None

        if rec is not None:
            fiche = {
                "centrale": u["centrale"],
                "puissance_installee_mw": propre(rec.get("puissance_installee")),
                "puissance_min_conception_mw": propre(rec.get("puissance_minimum_de_conception")),
                "date_mise_en_service": date_iso(rec.get("date_de_mise_en_service_industrielle")),
                "reserve_secondaire_max_mw": propre(rec.get(COL_RESERVE)),
                "palier": palier(rec.get("sous_filiere")),
                "commune": propre(rec.get("commune")),
                "departement": propre(rec.get("departement")),
                "region": propre(rec.get("region")),
            }
            p_edf, p_units = fiche["puissance_installee_mw"], propre(u.get("nominal"))
            if p_edf is not None and p_units is not None and p_edf != p_units:
                ecarts.append((nom, p_edf, p_units))
        else:
            # Pas d'équivalent OpenData EDF (ex. Fessenheim) : rien d'inventé.
            fiche = {k: None for k in (
                "puissance_installee_mw", "puissance_min_conception_mw",
                "date_mise_en_service", "reserve_secondaire_max_mw",
                "palier", "commune", "departement", "region",
            )}
            fiche = {"centrale": u["centrale"], **fiche}

        ind = indicateurs.get(nom, {})
        fiche.update({
            "co2_t_par_an": None,  # source à définir
            "arrets_par_an": ind.get("arrets_par_an"),
            "jours_arret": ind.get("jours_arret"),
            "sources": {
                "caracteristiques": source_carac if rec is not None else None,
                "indicateurs": ind.get("source"),
            },
        })
        reacteurs[nom] = fiche

    # Agrégats par centrale (clé = nom de centrale de units.json)
    centrales = {}
    for nom_c in sorted({f["centrale"] for f in reacteurs.values()}):
        fiches = [f for f in reacteurs.values() if f["centrale"] == nom_c]
        connues = all(f["sources"]["caracteristiques"] for f in fiches)
        centrales[nom_c] = {
            "nb_tranches": len(fiches),
            "puissance_installee_mw": somme_ou_null([f["puissance_installee_mw"] for f in fiches]),
            "premiere_mise_en_service": min_ou_null([f["date_mise_en_service"] for f in fiches]),
            "reserve_secondaire_max_mw": somme_ou_null([f["reserve_secondaire_max_mw"] for f in fiches]),
            "sources": {
                "nb_tranches": "src/assets/units.json",
                "caracteristiques": (f"Calculé à partir de : {source_carac}" if connues else None),
            },
        }

    return {**reacteurs, "_centrales": centrales}, ecarts


def main() -> int:
    try:
        data, ecarts = construire()
    except SourceIndisponible as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        print(f"{OUT_JSON.relative_to(ROOT)} n'a pas été modifié.", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        print(f"{OUT_JSON.relative_to(ROOT)} n'a pas été modifié.", file=sys.stderr)
        return 1

    # Écriture atomique : fichier temporaire puis remplacement.
    tmp = OUT_JSON.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, OUT_JSON)

    nb = len(data) - 1
    sans = [k for k, v in data.items() if k != "_centrales" and v["sources"]["caracteristiques"] is None]
    print(f"Écrit : {OUT_JSON.relative_to(ROOT)} ({nb} réacteurs, {len(data['_centrales'])} centrales)")
    print(f"Réacteurs sans caractéristiques EDF : {sans or 'aucun'}")
    if ecarts:
        print(f"Écarts puissance installée EDF vs nominal units.json ({len(ecarts)}) :")
        for nom, p_edf, p_units in ecarts:
            print(f"  {nom:<16} EDF {p_edf:>5} MW | units.json {p_units:>5} MW | écart {p_edf - p_units:+g}")
    else:
        print("Aucun écart de puissance installée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
