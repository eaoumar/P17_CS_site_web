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
| `sources_edf.py` | Accès aux sources. `get_caracteristiques_centrales()` lit l'API publique et gère la pagination et le cache. `get_outages()` lit les indisponibilités : par l'API avec le token (`fetch_outages_raw` de `convert.py`), sinon par `donnees_edf.csv`, sinon elle s'arrête avec une erreur claire. Elle renvoie les événements filtrés, la source utilisée et la date de récupération. |
| `build_correspondance.py` | Rapproche les noms de réacteurs entre `units.json` et l'OpenData EDF, avec une normalisation automatique et un dictionnaire de corrections manuelles. |
| `correspondance_reacteurs.csv` | Table de correspondance, 59 lignes. |
| `build_centrales_infos.py` | Construit le JSON, signale les écarts de puissance et prévoit l'emplacement des indicateurs d'arrêts. |

### Correspondance des noms

Colonnes de `correspondance_reacteurs.csv` :

- `centrale`, `tranche`, `nom_units_json` : noms utilisés par le site, issus de `units.json`.
- `nom_edf_opendata` : champ `tranche` du jeu OpenData EDF. Il est vide pour FESSENHEIM 1 et 2, qui sont absents de ce jeu.
- `unit_name_api_indispo` : champ `unit_name` de l'API indisponibilités. Vérifié le 2026-11-16 : les 59 noms sont identiques à `nom_units_json`. Le script refait cette vérification à chaque exécution quand le token est disponible.
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
| `arrets_par_an` | API indisponibilités EDF (token) | `{"2024": 3, …}` : nombre d'arrêts ayant au moins une partie dans l'année (voir la méthode plus bas) |
| `jours_arret` | API indisponibilités EDF | `{"2024": {"planned": 80.0, "fortuitous": 1.0, "total": 81.0}, …}` |
| `planifie_futur` | API indisponibilités EDF | Arrêts publiés à venir : `[{"type", "debut", "fin", "jours"}]` |
| `arret_definitif` | API indisponibilités EDF | Date de mise à l'arrêt définitive (Fessenheim), sinon `null` |
| `sources.indicateurs` | | « Calcul P17 à partir des indisponibilités EDF (… — URL), récupéré le AAAA-MM-JJ » |

La clé `_meta_indicateurs` décrit le calcul. Elle contient :
- la date du calcul ;
- la date de la dernière publication de l'API ;
- le mode de dédoublonnage ;
- le nombre d'événements ;
- les définitions des indicateurs.

### Méthode de calcul des indicateurs d'arrêts

1. **Filtrage**, comme dans `convert.py` :
   - on garde la dernière version de chaque publication ;
   - on exclut les statuts `''`, `Inactif` et `DISMISSED`, ainsi que tout statut contenant « annul » ;
   - on exclut aussi les dates invalides et les puissances nominales nulles.
2. **Dédoublonnage des versions :** dans l'API, le `publication_id` se termine par `_NNN`, qui est le numéro de version (`…00010073_001`, `…00010073_002`). `get_outages()` dédoublonne donc sur l'identifiant sans ce suffixe (`dedup="base_id"`, le mode par défaut). Le mode `dedup="publication_id"` reproduit exactement `convert.py`. Résultats au 2026-11-16 :
   - 15 166 enregistrements bruts ;
   - 14 852 événements en mode `publication_id`, comme `convert.py` ;
   - 12 071 événements en mode `base_id`, qui est le mode utilisé.
3. **Arrêt :** une indisponibilité **totale**, c'est-à-dire une puissance disponible de 0 MW. Les réductions partielles ne sont pas comptées. Le seuil se règle avec `SEUIL_ARRET_MW`.
4. **Chevauchements :** les arrêts d'un même réacteur qui se chevauchent ou se touchent sont fusionnés. Quand un arrêt `planned` et un arrêt `fortuitous` se chevauchent, les jours communs sont comptés en `planned`. On a donc toujours `planned + fortuitous = total`.
5. **Découpage par année :** au 1er janvier à 00:00, heure de Paris. Un arrêt à cheval sur deux années compte une fois dans chacune.
6. **Passé et futur :** ce qui précède la date de calcul va dans les années. La suite va dans `planifie_futur`.
7. **Années couvertes :** de 2015 jusqu'à l'année en cours, qui est partielle. Les premières publications datent du 2014-12-16. Un réacteur récent commence à l'année de sa première indisponibilité (FLAMANVILLE 3 : 2024).
8. **Arrêt définitif :** une indisponibilité qui se termine après 2090 est traitée comme une mise à l'arrêt définitive. C'est le cas de Fessenheim, dont la fin est publiée au 2099-12-31. Le calcul s'arrête à cette date, sans arrêt futur ni année ultérieure.
9. **Contrôle :** si un total annuel dépasse la durée de l'année (365 ou 366 jours), le script s'arrête sans écrire le fichier.

Champs de `_centrales` :

| Champ | Calcul |
|---|---|
| `nb_tranches` | Nombre de réacteurs de la centrale dans `units.json` |
| `puissance_installee_mw`, `reserve_secondaire_max_mw` | Somme sur les tranches, à condition que toutes soient connues. Sinon `null`, sans total partiel. |
| `premiere_mise_en_service` | Date la plus ancienne des tranches, à condition que toutes soient connues. Sinon `null`. |

### Valeurs `null` connues (état au 2026-11-16)

- **FESSENHEIM 1 et 2 :** tous les champs sont `null` sauf `centrale`, car ils sont absents du jeu EDF (centrale arrêtée). Côté `_centrales`, FESSENHEIM n'a que `nb_tranches = 2`.
- **FLAMANVILLE 3 :** `puissance_min_conception_mw` et `reserve_secondaire_max_mw` sont `null`, car le jeu EDF ne les renseigne pas. Par conséquent, `_centrales.FLAMANVILLE.reserve_secondaire_max_mw` est aussi `null`.
- **Tous les réacteurs :** `co2_t_par_an` est `null`.
- **Indicateurs d'arrêts :** ils sont calculés pour les 59 réacteurs. Une année hors de la plage couverte par un réacteur n'a pas de valeur, et le site affiche alors « Non disponible ».

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
2. **CO2 par an :** la source reste à définir.
3. **Écarts de puissance :** il faut choisir la valeur de référence pour le site entre OpenData EDF et le nominal de l'API indisponibilités.
4. **Fraîcheur de l'API :** au 2026-11-16, la dernière publication date du 2026-05-07. Les arrêts fortuits survenus depuis ne sont pas connus, donc 2026 est incomplète. À signaler sur le site ou à vérifier avec EDF.
5. **Définition d'un arrêt :** on compte aujourd'hui l'indisponibilité totale uniquement. Faut-il aussi compter les fortes réductions de puissance ?
6. **Versions dans `convert.py` :** `convert.py`, utilisé pour la carte, dédoublonne sur le `publication_id` brut. Il garde donc les anciennes versions des publications, soit 4 179 enregistrements concernés. À corriger en accord avec le Groupe 2, car la carte en dépend.
