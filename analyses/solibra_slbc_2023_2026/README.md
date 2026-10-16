# SOLIBRA (SLBC), 01/01/2023 - 15/10/2026 : historique importé depuis le dépôt public

## Statut

**Série non validée.** Les données proviennent d'une seule compilation publique (`harzat/brvm-data-public`, commit `ed5e3e3`), dont la traçabilité ligne à ligne n'est pas documentée. Les avis officiels de la BRVM n'ont pas pu être ouverts depuis cet environnement. Plusieurs contradictions restent non résolues (voir plus bas). À utiliser pour une exploration, pas comme série de référence.

## Résultat

| Élément | Valeur |
|---|---|
| Lignes du fichier source (2006-2026) | 2 400 |
| Lignes dans la fenêtre 2023-01-01 à 2026-10-15 | 725 |
| Lignes retenues dans `ANALYSE` | **721** |
| dont séances sans transaction (volume 0 établi par `Volume FCFA = 0`) | 47 |
| Lignes exclues | 4 (voir journal) |
| Dates extrêmes de `ANALYSE` | 2023-01-02 → 2026-10-14 |
| Effectif annuel | 2023 : 177 · 2024 : 103 · 2025 : 247 · 2026 : 194 |
| Doublons, valeurs manquantes, cours <= 0, volumes négatifs ou non entiers | 0 |
| Week-ends | 0 |

**Le 15/10/2026 est exclu.** La source publie une clôture de 38 250 FCFA pour 44 titres. La page BRVM « Cours des actions » du même jour, en clôture provisoire, indique 38 490 FCFA pour 238 titres. Les deux sources se contredisent ; la ligne reste dans `BRUT`.

**Couverture.** Sur les 989 jours ouvrés de la période : 721 ont une observation retenue, 3 sont exclus, 57 ont été retirés en amont par le dépôt (fériés fixes, copies de séance), 116 tombent dans la suspension et 92 n'ont aucune ligne dans le CSV. Aucun calendrier officiel n'a été lu : le calendrier de séances est donc **non établi**, et la couverture n'est pas démontrable. Les 92 jours sans ligne ne sont ni comblés ni convertis en rendement nul.

## Fichiers

| Fichier | Contenu |
|---|---|
| `SOLIBRA_SLBC_2023_2026_BRUT.csv` | Les 725 lignes de la fenêtre, avec valeurs d'origine, indicateurs de contrôle et décision |
| `SOLIBRA_SLBC_2023_2026_ANALYSE.csv` | Exactement `Date,Close,Volume` (721 lignes) |
| `PROVENANCE_SOLIBRA_2023_2026.csv` | Provenance de chaque ligne retenue ou exclue : URL, commit, ligne source, SHA-256, date de récupération |
| `JOURNAL_CORRECTIONS_EXCLUSIONS.csv` | 68 entrées : exclusions, contradictions, constats, retraits amont |
| `CALENDRIER_COUVERTURE_2023_2026.csv` | 1 384 jours calendaires, chacun avec son statut |
| `COUVERTURE_PAR_INTERVALLE.csv` | Les 16 intervalles de trois mois demandés |
| `SOLIBRA_DIVIDENDES_2023_2026.csv` | Dividendes 2023, 2024 et 2025, avec référence et anomalie de dates |
| `EVENEMENTS_SOLIBRA_2023_2026.csv` | Événements BRVM de la fenêtre (suspension, levée, fractionnement, dividendes, rapports) |
| `METADONNEES_SERIE.json` | Règles de la série, empreinte, statut |
| `CONTROLES_PANDAS.txt` | Sortie du script `verifier_livrables.py`, relu avec pandas et zipfile |
| `preuves/brut/` | Copie du CSV source (SHA-256 vérifié), extraits JSON du dépôt |
| `importer_depot_brvm_public.py` | Import et contrôles, reproductibles |
| `verifier_livrables.py` | Relecture des livrables |

## Traitement des cours

- **`Close` n'est pas ajusté** du fractionnement. C'est le cours tel que publié par la source, en FCFA par action.
- **Le fractionnement de 2024 n'apparaît pas dans les cours.** L'avis BRVM n°242 (27/09/2024), dont le titre figure dans les événements du dépôt, annonce une division par dix. Le CSV ne montre aucune cassure : 9 500 FCFA le 26/09, 10 975 le 30/09, 15 505 le 08/10. Les cours de référence BRVM du dépôt (8 325 le 03/06/2024, 19 320 le 24/07/2025, 39 500 le 28/07/2026) sont cohérents avec le CSV. Le fractionnement est donc soit absent de la cotation, soit mal documenté. Une série ajustée n'est pas produite : il faudrait d'abord lire l'avis n°242.
- Le même constat vaut pour le fractionnement de 2014 : aucune cassure visible en décembre 2014 (20 500 → 20 000).
- Les cours ne sont corrigés d'aucune incohérence interne (voir journal).

## Traitement des volumes

- `Volume` est le nombre de titres échangés (`Volume Titres`).
- Quand `Volume Titres` est vide et `Volume FCFA = 0`, le volume est fixé à 0 : c'est une séance sans transaction, documentée par la source. C'est le cas de 47 lignes retenues.
- Quand `Volume Titres` est vide et `Volume FCFA > 0`, le volume est **non établi** : la ligne est exclue. Aucun volume n'est estimé à partir du montant. Ce cas ne se présente pas dans la fenêtre.
- `Volume FCFA` est un montant publié, probablement un VWAP. Il n'est pas recalculé comme Close × Volume : pour 113 lignes sur 677, l'écart dépasse 2 %.

## Décisions et contradictions (journal)

| Sujet | Décision | Statut |
|---|---|---|
| 15/10/2026 : CSV 38 250 / 44 titres contre snapshot BRVM 38 490 / 238 | Exclue de `ANALYSE` | Non résolu |
| Vendredi saint 18/04/2025 et 03/04/2026 : séances publiées | Exclues de `ANALYSE` (jour férié probable) | Non résolu |
| 03/06/2024 : ligne publiée pendant la suspension (avis 054 du 02/04 à avis 227 du 11/09) | Exclue | Non résolu |
| Fractionnement 2024 absent des cours | Aucun ajustement, série non ajustée | Non résolu |
| 57 jours retirés en amont par le dépôt (fériés fixes, copies de séance) | Absents du CSV, constat seulement | Résolu (retrait amont) |
| 270 lignes dont la clôture est hors de [plus bas ; plus haut] | Conservées, non corrigées | Non résolu |
| 89 lignes identiques à la séance précédente | Conservées : le dépôt ne retire que les copies d'au moins 20 titres | Non tranché |
| Variation de -12,4 % le 05/03/2026 | Conservée | Non résolu |

## Dividendes SOLIBRA

| Exercice | Brut (FCFA) | Net (FCFA) | Détachement | Paiement | Remarque |
|---|---|---|---|---|---|
| 2023 | non publié dans la source | 2 700 | 12/09/2024 | 14/08/2024 | Paiement antérieur au détachement : signalé par la source, avis n°228-2024 |
| 2024 | 1 220 | 1 073,60 | 25/07/2025 | 29/07/2025 | Avis n°167 |
| 2025 | 2 127 | 1 871,76 | 29/07/2026 | 30/07/2026 | Avis n°208 |

Les montants viennent du dépôt. Les PDF des avis cités ne sont pas ouverts. **Aucun rendement total n'est calculé** : il faut une série de cours cohérente avec les dividendes (point non résolu ci-dessus).

## Limites

- Une seule source secondaire, sans traçabilité ligne à ligne. Ce n'est pas une base officielle.
- Le calendrier de séances n'est pas établi à partir des bulletins officiels.
- Le fractionnement et la suspension ne sont pas confirmés par les avis.
- Sans les avis BRVM ou une seconde source indépendante, la série ne peut pas être dite exhaustive ni vérifiée.

## Données non obtenues

- Les bulletins officiels de la cote et les avis BRVM (`www.brvm.org`) : refusés par le proxy (`403 Forbidden`). Voir `preuves/COLLECTE_TENTATIVES.csv`.
- Ilboursa et Sika Finance : même refus.
- `brvmetrics.vercel.app` : même refus.
- Le notebook et les CSV joints mentionnés dans la demande : toujours absents de l'environnement.

## Reproduire

```bash
git clone https://github.com/harzat/brvm-data-public
cd brvm-data-public && git checkout ed5e3e355d4fdd21b024de59140a19a67e4dccd3 && cd ..
python3 importer_depot_brvm_public.py     # chemin du dépôt dans DEPOT, en tête du script
python3 verifier_livrables.py > CONTROLES_PANDAS.txt
```

Le script `colab/analyse_solibra_colab.py` lit le ZIP de la base. Il ne doit pas être utilisé sur `ANALYSE` tant que les contradictions ci-dessus sont ouvertes, sauf à le préciser dans les résultats.

Les scripts `collecte_sources.py` et `construire_livrables.py` de la version précédente reflètent la collecte bloquée. Ils ne sont plus utilisés pour produire ces livrables.
