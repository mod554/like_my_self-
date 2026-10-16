# Base SOLIBRA (SLBC.CI) et BRVM Composite, 01/01/2025 – 09/10/2026

## État au 16/10/2026 : aucune donnée de marché récupérée

Cette version ne contient **aucun cours, volume ni niveau d'indice**. Les fichiers de séries sont livrés avec leur en-tête et zéro ligne. Ce n'est pas un défaut de mise en forme : rien n'a pu être obtenu ni vérifié.

Deux raisons, toutes deux journalisées :

1. **Aucun fichier joint n'était présent** dans l'environnement d'exécution : ni CSV SOLIBRA ou indice, ni notebook. Les répertoires de dépôt et l'historique git ont été inspectés. L'audit des fichiers fournis (inventaire, doublons, cotations des 07/08 et 25/08/2026, onze observations du 04 au 18/09/2026) n'a donc pas pu être réalisé. Voir `JOURNAL_AUDIT.csv`, entrées D0001 à D0004 et D0008.
2. **Toutes les sources ont été refusées par la politique réseau** de l'environnement. Au total, 38 requêtes par fenêtres de trois mois au plus ont été envoyées à brvm.org, ilboursa.com et sikafinance.com. Chacune a échoué avec `Tunnel connection failed: 403 Forbidden`. L'outil de lecture web a aussi échoué (`ENOTFOUND`). Le détail figure dans `preuves/COLLECTE_TENTATIVES.csv`.

Aucune valeur n'a été substituée à ces absences.

## Contenu

| Fichier | Rôle | État |
|---|---|---|
| `SOLIBRA_SLBC_2025_2026_BRUT.csv` | Toutes les observations récupérées, avec leur provenance et leur statut de contrôle | 0 ligne |
| `SOLIBRA_SLBC_2025_2026_QUOTIDIEN.csv` | Série validée, format strict `Date,Close,Volume` | 0 ligne |
| `BRVM_COMPOSITE_2025_2026.csv` | Série validée, format strict `Date,Close` | 0 ligne |
| `SOLIBRA_DIVIDENDES_2025_2026.csv` | Dividendes documentés | 2 lignes, **aucune vérifiée** |
| `PROVENANCE_SOLIBRA.csv`, `PROVENANCE_BRVM_COMPOSITE.csv` | Provenance par observation | 0 ligne |
| `JOURNAL_AUDIT.csv` | Constats, ajouts, corrections et exclusions | 8 constats |
| `CALENDRIER_ET_COUVERTURE.csv` | Un jour calendaire par ligne, avec le statut officiel et la disponibilité | 647 jours, 0 séance établie |
| `preuves/COLLECTE_TENTATIVES.csv` | Journal de chaque requête : URL, période, horodatage, statut HTTP, SHA-256, erreur | 38 tentatives |
| `preuves/brut/` | Octets bruts reçus (originaux, jamais modifiés) | vide |
| `saisies/` | Saisies manuelles tirées des bulletins officiels (en-têtes seuls) | vides |
| `collecte_sources.py` | Collecte et archivage horodaté avec SHA-256 | exécuté |
| `construire_livrables.py` | Construction déterministe des livrables à partir des preuves | exécuté |
| `audit_et_chargement_colab.py` | Lecture et contrôles (section 7), y compris l'intégrité du ZIP | exécuté |

## Définitions et unités

- `Date` : date de séance, au format AAAA-MM-JJ.
- `Close` : cours de clôture SLBC en FCFA par action, ou niveau de clôture de l'indice en points. Le point est le séparateur décimal.
- `Volume` : nombre entier d'actions échangées.
- `Montant_negocie` : il est rempli uniquement par lecture directe d'un bulletin. Il n'est **jamais** calculé comme Close × Volume.
- Statuts de séance (`CALENDRIER_ET_COUVERTURE.csv`) : `SEANCE`, `SEANCE_EXCEPTIONNELLE`, `FERMETURE` et `NON ÉTABLI`. `NON ÉTABLI` signifie qu'aucun bulletin ou avis n'a été lu. La colonne `lundi_vendredi` est fournie à titre indicatif ; elle ne sert **pas** à établir le calendrier.
- Statuts de disponibilité d'une série : `DISPONIBLE`, `SÉANCE SANS TRANSACTION`, `TITRE SUSPENDU`, `JOUR SANS SÉANCE`, `EXCLU (motif)` et `NON RÉCUPÉRÉ`.

## Méthode

Elle est mise en œuvre dans `construire_livrables.py`.

1. **Collecte.** Chaque réponse est enregistrée telle quelle dans `preuves/brut/`, avec son URL, la période demandée, l'horodatage UTC et son SHA-256.
2. **Lecture des fournisseurs.**
   - Sika Finance (JSON) : le script échoue explicitement si la structure attendue (`lst`, `Date`, `Close`) est absente.
   - Ilboursa : le fichier n'est lu que s'il s'agit d'un CSV aux colonnes reconnues. Sinon, il est consigné dans le journal comme anomalie.
3. **Bulletins officiels BRVM.** Ce sont des PDF. Leur lecture est manuelle et tracée : les valeurs sont saisies dans `saisies/*.csv`, avec le numéro du bulletin et la page.
4. **Validation d'une observation.** Elle entre dans la série validée si toutes ces conditions sont réunies :
   - la date est dans la période ;
   - la date est une séance établie par un bulletin ;
   - le cours est strictement positif ;
   - le volume est un entier non négatif (pour SLBC) ;
   - aucune contradiction entre sources n'est restée non résolue.
5. **Contradictions entre sources.** Les deux valeurs sont conservées dans les données brutes et la date est exclue de la série validée. Elle n'y revient que si une décision documentée est inscrite dans `saisies/decisions_contradictions.csv`. Cette décision est reportée dans le journal d'audit comme « correction », avec sa référence.
6. **Interdits.** Aucune interpolation, aucun report du cours précédent, aucun volume inconnu remplacé par zéro et aucun rendement nul imputé à une absence de cotation.
7. **Événements sur titres.** Aucun réajustement de cours n'est fait. La période commence après le fractionnement annoncé de 2024. Le traitement appliqué par chaque fournisseur reste à vérifier une fois les données obtenues.

## Dividendes

`SOLIBRA_DIVIDENDES_2025_2026.csv` contient :

- **Exercice 2024 (non vérifié).** Les chiffres viennent d'un résumé de moteur de recherche citant deux articles de presse (AllAfrica, Financial Afrik) que l'outil n'a pas pu ouvrir :
  - montant brut : 1 220 FCFA par action ;
  - détachement : 25/07/2025 ;
  - paiement : 29/07/2025 ;
  - montant total : 20,082 milliards de FCFA pour 16 460 840 actions.

  Ces éléments ne valent pas preuve : ils doivent être confirmés par l'avis BRVM. Le montant net n'est pas renseigné, car il n'a pas été calculé.
- **Exercice 2025 : NON RÉCUPÉRÉ.**

Aucun rendement total ne doit être calculé à partir de ce fichier en l'état.

## Reproduire avec accès réseau (Colab, poste personnel)

```bash
python3 collecte_sources.py          # remplit preuves/brut et le journal
# lire les bulletins PDF récupérés -> compléter saisies/*.csv (numéro de bulletin, page)
python3 construire_livrables.py      # régénère A, B, C, E, F, G, H
python3 audit_et_chargement_colab.py .
```

Points **non vérifiés**, faute d'accès :

- l'API Sika Finance (`POST /api/general/GetHistos`, ticker `BRVMC` pour le Composite) ;
- les paramètres de période de l'URL Ilboursa ;
- la structure des pages de bulletins de brvm.org.

Le collecteur conserve la réponse brute quoi qu'il arrive. Le constructeur refuse les formats non reconnus au lieu de deviner.

## Limites

- La base est vide de données de marché : elle n'est **ni exhaustive ni vérifiée**. Elle constitue seulement une infrastructure de collecte et d'audit testée.
- Le notebook mentionné n'était pas disponible. Ses noms de fichiers et colonnes attendus n'ont donc pas pu être contrôlés. Les livrables suivent les formats imposés par l'énoncé.
- La logique de validation a été testée sur un jeu fictif isolé, hors livrables et non archivé. Ce test a vérifié l'exclusion d'une contradiction, l'exclusion d'un cours négatif, la jointure externe et la couverture. Il ne prouve rien sur des données réelles.

## Usages possibles en l'état

Aucun usage quantitatif n'est possible, car il n'y a aucune observation. Le détail par usage figure dans la conclusion du rapport d'exécution. Aucune conclusion d'investissement n'est formulée.
