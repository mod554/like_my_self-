# SOLIBRA (SLBC.CI), du 01/01/2023 au 15/10/2026

## État au 16/10/2026 : aucune observation obtenue

Le fichier `SOLIBRA_SLBC_2023_2026_ANALYSE.csv` ne contient que son en-tête, `Date,Close,Volume`, et **zéro ligne**. Il ne s'agit pas d'un historique : aucun cours ni aucun volume n'a pu être récupéré ou vérifié. Deux raisons :

- **Aucun fichier joint** (CSV, archive ou notebook) n'était présent dans l'environnement d'exécution. Voir `JOURNAL_CORRECTIONS_EXCLUSIONS.csv`, entrée D0001.
- **Collecte bloquée par la politique réseau.** La collecte a été lancée sur les 16 intervalles trimestriels, de 2023-01-01→2023-03-31 à 2026-10-01→2026-10-15. Sur 46 requêtes vers sikafinance.com, ilboursa.com et brvm.org, toutes ont échoué avec `Tunnel connection failed: 403 Forbidden`. Le détail est dans `COUVERTURE_PAR_INTERVALLE.csv` et `preuves/COLLECTE_TENTATIVES.csv`.

## Fichiers

| Fichier | Contenu actuel |
|---|---|
| `SOLIBRA_SLBC_2023_2026_BRUT.csv` | Observations sources et provenance : 0 ligne |
| `SOLIBRA_SLBC_2023_2026_ANALYSE.csv` | Exactement `Date,Close,Volume` : 0 ligne |
| `PROVENANCE_SOLIBRA_2023_2026.csv` | Provenance par observation : 0 ligne |
| `JOURNAL_CORRECTIONS_EXCLUSIONS.csv` | 5 constats documentaires, aucune correction ni exclusion de valeur |
| `CALENDRIER_COUVERTURE_2023_2026.csv` | 1 384 jours calendaires, tous au statut `NON ÉTABLI` / `NON RÉCUPÉRÉ` |
| `COUVERTURE_PAR_INTERVALLE.csv` | Par intervalle : tentatives, sources, échecs, lignes récupérées, retenues et exclues |
| `EVENEMENTS_SOLIBRA_2024_PISTES.csv` | Suspension, reprise et fractionnement de 2024, d'après la presse : **non vérifiés** |
| `METADONNEES_SERIE.json` | Base d'ajustement de `Close`, événements confirmés, règles appliquées |
| `preuves/` | Journal de collecte ; `brut/` est vide (aucun octet reçu) |
| `saisies/` | Gabarits de saisie à remplir depuis les bulletins et avis officiels (vides) |
| `collecte_sources.py`, `construire_livrables.py` | Collecte et construction reproductibles |
| `colab/` | Notebook et script d'analyse, avec leurs tests |

## Traitement des cours

- **`Close` dans ANALYSE est NON ajusté du fractionnement.** Il s'agit du cours de clôture tel que coté, en FCFA par action. L'information est aussi enregistrée dans `METADONNEES_SERIE.json` (`close_ajuste_fractionnement: "NON"`).
- **Série ajustée.** Le fichier séparé `SOLIBRA_SLBC_2023_2026_AJUSTE_FRACTIONNEMENT.csv` n'est produit que si le fractionnement est saisi comme `CONFIRMÉ PAR AVIS OFFICIEL` dans `saisies/evenements_officiels.csv`. La transformation, documentée dans les métadonnées, est la suivante : pour les dates antérieures à la date d'effet, `Close / ratio` et `Volume × ratio`. **Ce fichier n'existe pas actuellement.**
- **Base d'ajustement des fournisseurs.** Chaque fournisseur (Sika, Ilboursa) doit être déclaré dans `saisies/base_ajustement_sources.csv` (`NON`, `OUI` ou `INCONNU`, avec la preuve). Avant la date du fractionnement, seules les sources déclarées `NON` sont retenues. On ne mélange donc jamais une base ajustée et une base non ajustée. Cette base ne peut être établie qu'en comparant un cours antérieur au 30/09/2024 avec le bulletin officiel du même jour, ce qui n'a pas été possible ici.

## Traitement des volumes

- Le volume est le nombre entier d'actions échangées, tel que publié. Il n'est jamais remplacé par zéro s'il est inconnu.
- Un volume nul n'est accepté que si un bulletin documente une séance sans transaction. Sinon, l'observation est exclue et le motif est journalisé.
- Les séances sans transaction et les suspensions figurent dans le calendrier avec leur statut propre. Elles ne sont pas confondues avec des données manquantes et n'ajoutent aucune ligne à ANALYSE.

## Règles de rétention d'une observation (`construire_livrables.py`)

Une observation est retenue si toutes les conditions suivantes sont réunies :

- la date est valide et comprise dans la période ;
- un bulletin officiel l'établit comme séance (`EXIGER_CALENDRIER_OFFICIEL=True`) ;
- ce n'est ni une fermeture ni un jour de suspension officielle ;
- le cours est strictement positif et le volume est un entier positif ;
- la base d'ajustement est compatible ;
- aucune contradiction entre sources n'est restée non résolue.

Un fichier fourni (`fournis/`) est comparé aux autres sources, mais ne suffit jamais seul. Aucune interpolation, aucun report du cours précédent, aucune ligne de complément.

## Événements de 2024 : pistes non vérifiées

Les informations ci-dessous proviennent de résumés de recherche web citant la presse. Les avis BRVM n'ont pas pu être récupérés :

- suspension le 02/04/2024 ;
- AGE le 11/09/2024 (nominal ramené de 2 500 à 250 FCFA) ;
- reprise de la négociation le 12/09/2024 ;
- fractionnement de 10 pour 1 appliqué à la séance du 30/09/2024 (16 460 840 actions).

D'après ces sources, la reprise (12/09) et le fractionnement (30/09) seraient deux dates distinctes. Rien de tout cela n'est appliqué tant qu'un avis officiel n'est pas saisi.

## Reproduire avec accès réseau

```bash
python3 collecte_sources.py          # remplit preuves/brut et le journal
# copier d'anciens CSV éventuels dans fournis/ (comparaison uniquement)
# remplir saisies/*.csv depuis les bulletins et avis BRVM (numéro, page)
python3 construire_livrables.py
python3 colab/analyse_solibra_colab.py BASE_SOLIBRA_SLBC_2023_2026.zip
```

## Limites

- La base est vide : elle n'est ni exhaustive ni vérifiée.
- L'API Sika, les paramètres de date d'Ilboursa et la structure des pages BRVM n'ont pas pu être testés.
- La logique de construction a été testée sur un petit jeu **synthétique** isolé, hors livrables. Ce test a vérifié l'exclusion d'une contradiction, la règle « fichier fourni non probant », la règle de base d'ajustement, la production de la série ajustée sur avis confirmé et le statut « séance sans transaction ». Il ne prouve rien sur des données réelles.
