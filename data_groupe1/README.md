# data_groupe1 — Fiche centrale / réacteur (Groupe 1, P17)

Ces scripts produisent `src/assets/centrales_infos.json`. Le panneau centrale du site lit ce fichier pour afficher une fiche par centrale et par réacteur.

Trois règles s'appliquent :
- aucune valeur n'est affichée sans sa source ;
- une valeur manquante vaut `null` dans le JSON et s'affiche « Non disponible » sur le site, jamais 0 ni une case vide ;
- on ne touche pas à la courbe de production (Groupe 2).

## Commandes

Depuis la racine du projet, avec Python 3, `pandas` et `requests` :

```bash
python data_groupe1/build_correspondance.py   # → data_groupe1/correspondance_reacteurs.csv
python data_groupe1/build_centrales_infos.py  # → src/assets/centrales_infos.json
```

L'ordre compte : `build_centrales_infos.py` lit la table de correspondance produite par le premier script.

Chaque téléchargement est enregistré dans `data_groupe1/cache/`, qui n'est pas versionné. Si l'API EDF est inaccessible, le script s'arrête avec une erreur et ne modifie pas `centrales_infos.json`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `sources_edf.py` | Accès aux sources. `get_caracteristiques_centrales()` lit l'API publique et gère la pagination et le cache. `get_outages()` n'est pas encore écrite : elle attend le token. |
| `build_correspondance.py` | Rapproche les noms de réacteurs entre `units.json` et l'OpenData EDF, avec une normalisation automatique et un dictionnaire de corrections manuelles. |
| `correspondance_reacteurs.csv` | Table de correspondance, 59 lignes. |
| `build_centrales_infos.py` | Construit le JSON, signale les écarts de puissance et prévoit l'emplacement des indicateurs d'arrêts. |

### Correspondance des noms

Colonnes de `correspondance_reacteurs.csv` :

- `centrale`, `tranche`, `nom_units_json` : noms utilisés par le site, issus de `units.json`.
- `nom_edf_opendata` : champ `tranche` du jeu OpenData EDF. Il est vide pour FESSENHEIM 1 et 2, qui sont absents de ce jeu.
- `unit_name_api_indispo` : rempli provisoirement avec `nom_units_json`, car `units.json` est généré par `convert.py` à partir du champ `unit_name` de l'API indisponibilités. **À vérifier quand on aura le token.**
- `nom_rte_production` : vide, à remplir avec le Groupe 2.

Les corrections manuelles traitent la lettre de site que seule l'OpenData EDF utilise : `CHINON B n`, `CHOOZ B n` et `ST-LAURENT B n`. Tout le reste se rapproche automatiquement : majuscules, accents retirés, tirets remplacés par des espaces, articles du type « (LE) » retirés.

## Format de `src/assets/centrales_infos.json`

Il y a une clé par réacteur, qui reprend exactement le nom de `units.json`. Une clé spéciale `_centrales` regroupe les totaux par centrale.

```json
{
  "GRAVELINES 1": {
    "centrale": "GRAVELINES",
    "puissance_installee_mw": 910,
    "puissance_min_conception_mw": 180,
    "date_mise_en_service": "1980-11-25",
    "reserve_secondaire_max_mw": 40,
    "palier": "REP 900",
    "commune": "Gravelines",
    "departement": "NORD",
    "region": "HAUTS-DE-FRANCE",
    "co2_t_par_an": null,
    "arrets_par_an": null,
    "jours_arret": null,
    "sources": {
      "caracteristiques": "OpenData EDF — Centrales de production nucléaire d'EDF SA (https://opendata.edf.fr/datasets/centrales-de-production-nucleaire-edf), récupéré le AAAA-MM-JJ",
      "indicateurs": null
    }
  },
  "_centrales": {
    "GRAVELINES": {
      "nb_tranches": 6,
      "puissance_installee_mw": 5520,
      "premiere_mise_en_service": "1980-11-25",
      "reserve_secondaire_max_mw": 240,
      "sources": {
        "nb_tranches": "src/assets/units.json",
        "caracteristiques": "Calculé à partir de : OpenData EDF — …"
      }
    }
  }
}
```

### Source de chaque champ

Champs par réacteur :

| Champ JSON | Source | Champ d'origine / calcul |
|---|---|---|
| `centrale` | `src/assets/units.json` | `centrale` |
| `puissance_installee_mw` | OpenData EDF, centrales nucléaires | `puissance_installee` (MW) |
| `puissance_min_conception_mw` | OpenData EDF | `puissance_minimum_de_conception` (MW) |
| `date_mise_en_service` | OpenData EDF | `date_de_mise_en_service_industrielle`, et uniquement elle |
| `reserve_secondaire_max_mw` | OpenData EDF | `_reserves_secondaires-par-tranche.reserve_secondaire_maximale`, en MW supposés (voir questions ouvertes) |
| `palier` | OpenData EDF | Tiré de `sous_filiere` : « Réacteur à eau pressurisée (REP) 900 » devient « REP 900 » |
| `commune`, `departement`, `region` | OpenData EDF | Mêmes noms de champs |
| `co2_t_par_an` | À définir | `null` pour l'instant |
| `arrets_par_an`, `jours_arret` | API indisponibilités EDF (token requis) | `null` pour l'instant ; emplacement prévu dans `calculer_indicateurs()` |

Champs de `_centrales` :

| Champ | Calcul |
|---|---|
| `nb_tranches` | Nombre de réacteurs de la centrale dans `units.json` |
| `puissance_installee_mw`, `reserve_secondaire_max_mw` | Somme sur les tranches, à condition que toutes soient connues. Sinon `null`, sans total partiel. |
| `premiere_mise_en_service` | Date la plus ancienne des tranches, à condition que toutes soient connues. Sinon `null`. |

### Valeurs `null` connues (état au 2026-11-16)

- **FESSENHEIM 1 et 2 :** tous les champs sont `null` sauf `centrale`, car ils sont absents du jeu EDF (centrale arrêtée). Côté `_centrales`, FESSENHEIM n'a que `nb_tranches = 2`.
- **FLAMANVILLE 3 :** `puissance_min_conception_mw` et `reserve_secondaire_max_mw` sont `null`, car le jeu EDF ne les renseigne pas. Par conséquent, `_centrales.FLAMANVILLE.reserve_secondaire_max_mw` est aussi `null`.
- **Tous les réacteurs :** `co2_t_par_an`, `arrets_par_an` et `jours_arret` sont `null`.

### Écarts de puissance détectés

La puissance installée EDF diffère du nominal de `units.json` pour 10 réacteurs. Le script les liste à chaque exécution. La fiche affiche la valeur OpenData EDF, puisque c'est la source citée.

| Réacteur | OpenData EDF | units.json |
|---|---|---|
| BLAYAIS 2, BLAYAIS 3 | 942 | 910 |
| DAMPIERRE 2, DAMPIERRE 3 | 922 | 890 |
| GRAVELINES 4 | 942 | 910 |
| GRAVELINES 6 | 938 | 910 |
| TRICASTIN 2, TRICASTIN 4 | 947 | 915 |
| TRICASTIN 3 | 944 | 915 |
| FLAMANVILLE 3 | 1600 | 1620 |

## Questions ouvertes

1. **Unité de la réserve secondaire.** Le jeu EDF ne précise pas l'unité de `reserve_secondaire_maximale`. On suppose des MW, d'où le nom `reserve_secondaire_max_mw`. Il faut le confirmer dans la documentation du jeu ou auprès d'EDF avant de l'afficher avec une unité.
2. **Token EDF pour les indicateurs d'arrêts.** Le jeu « Indisponibilités des moyens de production de EDF SA » (`4wsb2p5ghkbutlyrnqjmgazo`) renvoie une erreur 403 sans token. Avec le token, il faudra :
   - écrire `get_outages()` ;
   - vérifier la présence du champ `outage_type` et définir ce qu'on compte comme un « arrêt » ;
   - vérifier que `unit_name_api_indispo` correspond bien aux noms de l'API.
3. **CO2 par an :** la source reste à définir.
4. **Écarts de puissance :** il faut choisir la valeur de référence pour le site entre OpenData EDF et le nominal de l'API indisponibilités.
