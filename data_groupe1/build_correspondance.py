"""
Table de correspondance des noms de réacteurs entre les sources.

Entrées :
  - src/assets/units.json (champ "unit", généré par convert.py) : 59 réacteurs
  - OpenData EDF « Centrales de production nucléaire » (champ "tranche") : 57

Sortie : data_groupe1/correspondance_reacteurs.csv

Lancement (depuis la racine du projet) :
  python data_groupe1/build_correspondance.py
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

from sources_edf import SourceIndisponible, get_caracteristiques_centrales

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UNITS_JSON = ROOT / "src" / "assets" / "units.json"
OUT_CSV = HERE / "correspondance_reacteurs.csv"

COLONNES = [
    "centrale",
    "tranche",
    "nom_units_json",
    "nom_edf_opendata",
    "unit_name_api_indispo",
    "nom_rte_production",
]

# ─── Corrections manuelles ────────────────────────────────────────────────────
# Clé : nom units.json ; valeur : nom exact de la tranche dans l'OpenData EDF.
# Nécessaires car l'OpenData EDF garde la lettre du site ("B") que units.json
# (API indisponibilités) n'utilise pas.
CORRECTIONS_MANUELLES = {
    "CHINON 1": "CHINON B 1",
    "CHINON 2": "CHINON B 2",
    "CHINON 3": "CHINON B 3",
    "CHINON 4": "CHINON B 4",
    "CHOOZ 1": "CHOOZ B 1",
    "CHOOZ 2": "CHOOZ B 2",
    "ST LAURENT 1": "ST-LAURENT B 1",
    "ST LAURENT 2": "ST-LAURENT B 2",
}

# Réacteurs volontairement sans équivalent OpenData EDF (absents du jeu EDF).
SANS_EQUIVALENT_ATTENDU = {"FESSENHEIM 1", "FESSENHEIM 2"}


def normaliser(nom: str) -> str:
    """
    Majuscules, sans accents, tirets remplacés par des espaces, article entre
    parenthèses retiré ("BLAYAIS (LE)" -> "BLAYAIS"), espaces multiples réduits.
    """
    s = unicodedata.normalize("NFKD", str(nom))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"\((LE|LA|LES|L')\)", " ", s)
    s = s.replace("-", " ").replace("'", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def construire_correspondance():
    """Renvoie (lignes, non_rapproches_units, non_rapproches_edf)."""
    with open(UNITS_JSON, encoding="utf-8") as f:
        units = json.load(f)

    edf = get_caracteristiques_centrales()
    noms_edf = list(edf["tranche"])
    index_edf = {}
    for nom in noms_edf:
        cle = normaliser(nom)
        if cle in index_edf:
            raise ValueError(f"Deux tranches EDF ont le même nom normalisé : {cle}")
        index_edf[cle] = nom

    lignes = []
    utilises = set()
    non_rapproches_units = []

    for u in units:
        nom_u = u["unit"]
        if nom_u in CORRECTIONS_MANUELLES:
            cible = CORRECTIONS_MANUELLES[nom_u]
            if cible not in noms_edf:
                raise ValueError(f"Correction manuelle invalide : {cible!r} absent de l'OpenData EDF")
            nom_edf = cible
        else:
            nom_edf = index_edf.get(normaliser(nom_u), "")

        if nom_edf:
            if nom_edf in utilises:
                raise ValueError(f"Tranche EDF rapprochée deux fois : {nom_edf}")
            utilises.add(nom_edf)
        else:
            non_rapproches_units.append(nom_u)

        lignes.append({
            "centrale": u["centrale"],
            "tranche": nom_u,
            "nom_units_json": nom_u,
            "nom_edf_opendata": nom_edf,
            # Provisoire : units.json est construit depuis l'API indisponibilités
            # (champ unit_name) par convert.py. À vérifier avec le token.
            "unit_name_api_indispo": nom_u,
            "nom_rte_production": "",  # à remplir avec le Groupe 2
        })

    non_rapproches_edf = [n for n in noms_edf if n not in utilises]
    return lignes, non_rapproches_units, non_rapproches_edf


def main() -> int:
    try:
        lignes, nr_units, nr_edf = construire_correspondance()
    except SourceIndisponible as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        print("correspondance_reacteurs.csv n'a pas été modifié.", file=sys.stderr)
        return 1

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES)
        w.writeheader()
        w.writerows(lignes)

    print(f"Écrit : {OUT_CSV.relative_to(ROOT)}")
    print(f"Nombre de lignes : {len(lignes)} (attendu : 59)")
    print(f"Non rapprochés côté units.json : {nr_units or 'aucun'}")
    print(f"Non rapprochés côté OpenData EDF : {nr_edf or 'aucun'}")
    print("Cases vides par colonne :")
    for col in COLONNES:
        vides = sum(1 for l in lignes if not l[col])
        print(f"  {col:<24} {vides}")

    ok = True
    if len(lignes) != 59:
        print("ATTENTION : le nombre de lignes n'est pas 59.")
        ok = False
    inattendus = set(nr_units) - SANS_EQUIVALENT_ATTENDU
    if inattendus:
        print(f"ATTENTION : réacteurs non rapprochés inattendus : {sorted(inattendus)}")
        ok = False
    if nr_edf:
        print(f"ATTENTION : tranches EDF sans équivalent dans units.json : {nr_edf}")
        ok = False
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
