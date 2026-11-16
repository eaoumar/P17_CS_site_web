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
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sources_edf import (
    CARACTERISTIQUES_PAGE,
    CARACTERISTIQUES_TITRE,
    SourceIndisponible,
    get_caracteristiques_centrales,
    get_outages,
)

# ─── Paramètres des indicateurs d'arrêts ──────────────────────────────────────
PARIS = ZoneInfo("Europe/Paris")
# Premières publications le 2014-12-16 : 2015 est la première année complète.
ANNEE_DEBUT = 2015
# Un arrêt est une indisponibilité TOTALE (puissance disponible = 0 MW).
# Les réductions partielles de puissance ne sont pas comptées.
SEUIL_ARRET_MW = 0.0
# Une fin d'indisponibilité au-delà de cette année = mise à l'arrêt définitive
# (ex. Fessenheim : fin publiée au 2099-12-31). Le calcul s'arrête à son début.
ANNEE_FIN_DEFINITIVE = 2090

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UNITS_JSON = ROOT / "src" / "assets" / "units.json"
CORRESPONDANCE_CSV = HERE / "correspondance_reacteurs.csv"
# Réacteurs arrêtés absents de l'OpenData EDF : valeurs saisies à la main, sourcées.
REACTEURS_ARRETES_JSON = HERE / "sources" / "reacteurs_arretes.json"
CHAMPS_CARAC = (
    "puissance_installee_mw", "puissance_min_conception_mw", "date_mise_en_service",
    "reserve_secondaire_max_mw", "palier", "commune", "departement", "region",
)
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

def fusionner(intervalles):
    """Union d'intervalles [(debut, fin)] : chevauchements et contacts fusionnés."""
    res = []
    for d, f in sorted(intervalles):
        if res and d <= res[-1][1]:
            res[-1][1] = max(res[-1][1], f)
        else:
            res.append([d, f])
    return [(d, f) for d, f in res]


def soustraire(a, b):
    """a privé de b (deux listes déjà fusionnées)."""
    res = []
    for d, f in a:
        morceaux = [(d, f)]
        for bd, bf in b:
            suivants = []
            for md, mf in morceaux:
                if bf <= md or bd >= mf:
                    suivants.append((md, mf))
                    continue
                if md < bd:
                    suivants.append((md, bd))
                if bf < mf:
                    suivants.append((bf, mf))
            morceaux = suivants
        res.extend(morceaux)
    return res


def debut_annee(annee):
    """1er janvier 00:00 heure de Paris, en UTC."""
    return datetime(annee, 1, 1, tzinfo=PARIS).astimezone(timezone.utc)


def annee_paris(dt):
    return dt.astimezone(PARIS).year


def jours_dans(intervalles, d0, f0):
    """Nombre de jours des intervalles compris dans [d0, f0[."""
    s = sum(max(0.0, (min(f, f0) - max(d, d0)).total_seconds()) for d, f in intervalles)
    return s / 86400


def calculer_indicateurs(corresp):
    """
    corresp : {nom_units_json: unit_name de l'API indisponibilités}.

    Renvoie (indicateurs, meta) avec, par réacteur (clé = nom units.json) :
      arrets_par_an  : {"2024": n}  nombre d'arrêts (fusionnés) touchant l'année ;
      jours_arret    : {"2024": {"planned": j, "fortuitous": j, "total": j}} ;
      planifie_futur : [{"type", "debut", "fin", "jours"}] arrêts à venir ;
      source         : texte de source.
    Si la source n'est pas disponible : avertissement, ({}, None).

    Méthode :
      - arrêt = indisponibilité totale (available_capacity_mw = 0) ;
      - passé = jusqu'à maintenant ; la partie future va dans planifie_futur ;
      - chevauchements d'un même réacteur fusionnés (pas de double compte) ;
      - si planned et fortuitous se chevauchent, les jours comptent en planned
        (planned + fortuitous = total) ;
      - découpage par année civile au 1er janvier 00:00 heure de Paris ;
      - années publiées pour un réacteur : de max(2015, année de sa 1re
        indisponibilité) jusqu'à maintenant ou sa mise à l'arrêt définitive.
        Hors de cette plage : pas de valeur (affiché « Non disponible »).
    """
    try:
        df, meta = get_outages()
    except (NotImplementedError, SourceIndisponible) as exc:
        print(f"AVERTISSEMENT : indicateurs d'arrêts non calculés ({exc}). "
              "arrets_par_an et jours_arret restent null.")
        return {}, None

    maintenant = datetime.now(timezone.utc)
    source = (f"Calcul P17 à partir des indisponibilités EDF ({meta['libelle']} — {meta['url']}), "
              f"récupéré le {meta['recupere_le']}")

    noms_api = set(df["unit_name"]) if len(df) else set()
    resultat = {}
    for nom_units, nom_api in corresp.items():
        if not nom_api or nom_api not in noms_api:
            continue
        evs = df[df["unit_name"] == nom_api]
        arrets = evs[evs["available_capacity_mw"] <= SEUIL_ARRET_MW]

        # Mise à l'arrêt définitive
        definitifs = arrets[arrets["end"].map(lambda e: e.year >= ANNEE_FIN_DEFINITIVE)]
        fin_cov = maintenant
        arret_definitif = None
        if len(definitifs):
            arret_definitif = definitifs["begin"].min()
            fin_cov = min(fin_cov, arret_definitif)
            arrets = arrets[arrets["end"].map(lambda e: e.year < ANNEE_FIN_DEFINITIVE)]

        annee_1 = max(ANNEE_DEBUT, annee_paris(evs["begin"].min()))
        debut_cov = debut_annee(annee_1)
        annee_n = annee_paris(fin_cov)

        def passe(type_=None):
            sel = arrets if type_ is None else arrets[arrets["outage_type"] == type_]
            return fusionner([(max(b, debut_cov), min(e, fin_cov)) for b, e in zip(sel["begin"], sel["end"])
                              if min(e, fin_cov) > max(b, debut_cov)])

        tot, pla = passe(), passe("planned")
        fort = soustraire(passe("fortuitous"), pla)

        arrets_par_an, jours_arret = {}, {}
        for annee in range(annee_1, annee_n + 1):
            d0, f0 = debut_annee(annee), debut_annee(annee + 1)
            j_tot = jours_dans(tot, d0, f0)
            j_pla, j_fort = jours_dans(pla, d0, f0), jours_dans(fort, d0, f0)
            if abs(j_pla + j_fort - j_tot) > 1e-6:
                raise AssertionError(f"{nom_units} {annee} : planned + fortuitous != total")
            arrets_par_an[str(annee)] = sum(1 for d, f in tot if d < f0 and f > d0)
            jours_arret[str(annee)] = {
                "planned": round(j_pla, 1), "fortuitous": round(j_fort, 1), "total": round(j_tot, 1)}

        # Arrêts futurs (après maintenant), hors arrêt définitif
        futur = []
        if arret_definitif is None:
            def fut(type_):
                sel = arrets[arrets["outage_type"] == type_]
                return fusionner([(max(b, maintenant), e) for b, e in zip(sel["begin"], sel["end"]) if e > maintenant])
            p_fut = fut("planned")
            for type_, ints in (("planned", p_fut), ("fortuitous", soustraire(fut("fortuitous"), p_fut))):
                for d, f in ints:
                    futur.append({
                        "type": type_,
                        "debut": d.astimezone(PARIS).date().isoformat(),
                        "fin": f.astimezone(PARIS).date().isoformat(),
                        "jours": round((f - d).total_seconds() / 86400, 1),
                    })
            futur.sort(key=lambda x: x["debut"])

        resultat[nom_units] = {
            "arrets_par_an": arrets_par_an,
            "jours_arret": jours_arret,
            "planifie_futur": futur,
            "arret_definitif": arret_definitif.astimezone(PARIS).date().isoformat() if arret_definitif else None,
            "source": source,
        }

    meta_out = {
        "source": source,
        "calcule_le": maintenant.astimezone(PARIS).isoformat(timespec="minutes"),
        "derniere_publication_api": meta.get("derniere_publication"),
        "dedup": meta["dedup"],
        "nb_evenements": meta["nb_retenus"],
    }
    return resultat, meta_out


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

    indicateurs, meta_ind = calculer_indicateurs(
        {nom: ligne["unit_name_api_indispo"] for nom, ligne in corresp.items()})

    # Réacteurs arrêtés (fichier versionné, saisi à la main)
    with open(REACTEURS_ARRETES_JSON, encoding="utf-8") as f:
        arretes = json.load(f)
    sources_arretes = arretes.get("_sources", {})

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
            src_carac = source_carac
        else:
            # Pas d'équivalent OpenData EDF : rien d'inventé. On ne complète qu'à
            # partir du fichier des réacteurs arrêtés (valeurs sourcées).
            fiche = {"centrale": u["centrale"], **{k: None for k in CHAMPS_CARAC}}
            src_carac = None
            manuel = arretes.get(nom)
            if manuel:
                for k in CHAMPS_CARAC:
                    if fiche[k] is None and manuel.get(k) is not None:  # jamais d'écrasement
                        fiche[k] = manuel[k]
                src_carac = sources_arretes.get("caracteristiques")

        # Statut : arrêt définitif uniquement depuis le fichier sourcé (décret).
        manuel = arretes.get(nom) or {}
        date_arret = manuel.get("date_arret_definitif")
        ind = indicateurs.get(nom, {})
        if date_arret and ind.get("arret_definitif") and ind["arret_definitif"] != date_arret:
            print(f"AVERTISSEMENT : {nom} arrêt définitif {date_arret} (fichier) "
                  f"≠ {ind['arret_definitif']} (indisponibilités EDF)")

        fiche.update({
            "statut": "arrêté définitivement" if date_arret else "en service",
            "date_arret_definitif": date_arret,
            "co2_t_par_an": None,  # source à définir
            "arrets_par_an": ind.get("arrets_par_an"),
            "jours_arret": ind.get("jours_arret"),
            "planifie_futur": ind.get("planifie_futur"),
            "sources": {
                "caracteristiques": src_carac,
                "arret_definitif": sources_arretes.get("arret_definitif") if date_arret else None,
                "indicateurs": ind.get("source"),
            },
        })
        reacteurs[nom] = fiche

    # Agrégats par centrale (clé = nom de centrale de units.json)
    centrales = {}
    for nom_c in sorted({f["centrale"] for f in reacteurs.values()}):
        fiches = [f for f in reacteurs.values() if f["centrale"] == nom_c]
        srcs = [f["sources"]["caracteristiques"] for f in fiches]
        connues = all(srcs)
        # Source des agrégats = la ou les sources réellement utilisées par les tranches.
        src_c = " ; ".join(dict.fromkeys(srcs)) if connues else None
        centrales[nom_c] = {
            "nb_tranches": len(fiches),
            "puissance_installee_mw": somme_ou_null([f["puissance_installee_mw"] for f in fiches]),
            "premiere_mise_en_service": min_ou_null([f["date_mise_en_service"] for f in fiches]),
            "reserve_secondaire_max_mw": somme_ou_null([f["reserve_secondaire_max_mw"] for f in fiches]),
            "sources": {
                "nb_tranches": "src/assets/units.json",
                "caracteristiques": (f"Calculé à partir de : {src_c}" if connues else None),
            },
        }

    sortie = {**reacteurs, "_centrales": centrales}
    # Métadonnées lues par le site (année partielle, date de génération).
    sortie["_meta"] = {
        "derniere_publication": meta_ind.get("derniere_publication_api") if meta_ind else None,
        "genere_le": datetime.now(PARIS).isoformat(timespec="minutes"),
    }
    if meta_ind:
        sortie["_meta_indicateurs"] = {
            **meta_ind,
            "definitions": {
                "arret": "Indisponibilité totale (puissance disponible = 0 MW) ; réductions partielles exclues.",
                "arrets_par_an": "Nombre d'arrêts (chevauchements fusionnés) ayant au moins une partie dans l'année.",
                "jours_arret": "Jours d'arrêt dans l'année (découpage au 1er janvier, heure de Paris). "
                               "Si planned et fortuitous se chevauchent, les jours comptent en planned.",
                "planifie_futur": "Arrêts publiés dont la partie future commence après calcule_le.",
                "annees": f"De max({ANNEE_DEBUT}, 1re indisponibilité du réacteur) à l'année de calcule_le "
                          "ou de l'arrêt définitif. L'année en cours est partielle.",
            },
        }
    return sortie, ecarts


def main() -> int:
    try:
        data, ecarts = construire()
    except SourceIndisponible as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        print(f"{OUT_JSON.relative_to(ROOT)} n'a pas été modifié.", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, AssertionError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        print(f"{OUT_JSON.relative_to(ROOT)} n'a pas été modifié.", file=sys.stderr)
        return 1

    reacteurs = {k: v for k, v in data.items() if not k.startswith("_")}

    # Contrôle : aucun total annuel ne dépasse la durée de l'année (365 ou 366 j).
    depassements = []
    for nom, f in reacteurs.items():
        for annee, j in (f.get("jours_arret") or {}).items():
            a = int(annee)
            duree = (debut_annee(a + 1) - debut_annee(a)).total_seconds() / 86400
            if j["total"] > round(duree, 1):
                depassements.append((nom, annee, j["total"], duree))
    if depassements:
        print(f"ERREUR : totaux annuels supérieurs à la durée de l'année : {depassements}", file=sys.stderr)
        print(f"{OUT_JSON.relative_to(ROOT)} n'a pas été modifié.", file=sys.stderr)
        return 1

    # Écriture atomique : fichier temporaire puis remplacement.
    tmp = OUT_JSON.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, OUT_JSON)

    sans = [k for k, v in reacteurs.items() if v["sources"]["caracteristiques"] is None]
    avec_ind = sum(1 for v in reacteurs.values() if v.get("jours_arret"))
    max_tot = max(((j["total"], n, a) for n, v in reacteurs.items()
                   for a, j in (v.get("jours_arret") or {}).items()), default=None)
    print(f"Écrit : {OUT_JSON.relative_to(ROOT)} ({len(reacteurs)} réacteurs, {len(data['_centrales'])} centrales)")
    print(f"Indicateurs d'arrêts : {avec_ind}/{len(reacteurs)} réacteurs ; "
          f"total annuel max = {max_tot} ; aucun dépassement de 365/366 j.")
    if data.get("_meta_indicateurs"):
        m = data["_meta_indicateurs"]
        print(f"Dernière publication API : {m['derniere_publication_api']} ; calculé le {m['calcule_le']} ; "
              f"{m['nb_evenements']} événements ({m['dedup']}).")
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
