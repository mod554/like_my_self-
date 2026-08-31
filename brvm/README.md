# Suivi et analyse technique de portefeuille — BRVM (UEMOA)

Application Python de suivi de portefeuille sur la Bourse Régionale des Valeurs
Mobilières : ingestion des cotations, analyse technique adaptée à un marché peu
liquide, coût de revient réel frais et fiscalité inclus, contrôles de risque et
backtest.

> **Ce que « fiable » veut dire ici.** Le système vise la fiabilité *logicielle* :
> ne jamais inventer une donnée, ne jamais corriger une anomalie en silence,
> refuser de calculer plutôt que de produire un chiffre non fondé, et tracer
> l'origine de chaque valeur affichée. Il ne promet aucune performance de marché
> et ne constitue pas un conseil en investissement.

---

## État d'avancement

Le projet est livré **couche par couche**, chacune testée avant la suivante.

| Couche | Contenu | État |
|---|---|---|
| 1 — Socle | Configuration unique, erreurs, journal structuré, arithmétique XOF, calendrier de séances | ✅ livrée |
| 2 — Modèle de données | Modèles pydantic, schéma SQLite, écriture idempotente, historisation des corrections, ajustement des OST | ✅ livrée |
| 3 — Ingestion | Interface `DataSource`, connecteurs site BRVM / agrégateur / fichier manuel, anomalies et quarantaine | ⏳ à venir |
| 4 — Analyse technique | SMA, EMA, RSI, MACD, Bollinger, ATR, OBV, momentum, extrêmes glissants, score de confiance liquidité | ⏳ à venir |
| 5 — Portefeuille | PMP et FIFO, moteur de frais, fiscalité, TWR, IRR, simulateur d'ordre | ⏳ à venir |
| 6 — Risque et backtest | Limites de concentration, contrainte de liquidité, stops ATR, moteur événementiel walk-forward | ⏳ à venir |
| 7 — Exploitation | Ordonnanceur, alertes, tableau de bord Streamlit, export Excel | ⏳ à venir |

---

## Installation

Python 3.11 ou plus.

```bash
cd brvm
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Vérification :

```bash
pytest              # suite de tests
ruff check src tests   # style et erreurs statiques
mypy                # typage strict
```

---

## Configuration

Toute la configuration tient dans **un seul fichier commenté**. Aucune valeur
magique n'est codée dans les sources.

```bash
cp config/config.exemple.yaml       config/config.yaml
cp config/jours_feries.exemple.yaml config/jours_feries.yaml
cp config/univers.exemple.csv       config/univers.csv
```

Le fichier livré **échoue volontairement au chargement** tant que vous ne l'avez
pas complété. Le message d'erreur énumère tous les champs manquants d'un coup et
indique où trouver l'information :

```
Configuration invalide : config/config.yaml
9 paramètre(s) à corriger.

  • frais.lignes.0 : La ligne 'Commission de courtage SGI' est calculée sur
    MONTANT_BRUT : renseignez son taux d'après la grille tarifaire de votre SGI.
    Aucune valeur par défaut n'est fournie par le système.
      → Recopiez ligne à ligne le barème de votre SGI …
```

### Deux catégories de paramètres

| Marque | Nature | Fourni ? |
|---|---|---|
| `[FAIT]` | Barème de votre SGI, taux de fiscalité, seuil réglementaire de variation, URL d'une source | **Non.** Champ obligatoire, vide dans le fichier livré. |
| `[PRÉFÉRENCE]` | Limites de risque, fenêtres de calcul, niveau de journal | Une valeur de départ est proposée, à ajuster. |

### Renseigner le barème de frais

Recopiez ligne à ligne la grille tarifaire de votre SGI dans `frais.lignes`.
Chaque ligne porte :

- `libelle` — tel qu'il figure sur l'avis d'opéré ;
- `base_calcul` — `MONTANT_BRUT` (quantité × cours), `TOTAL_COMMISSIONS`
  (assiette d'une TVA : somme des lignes d'ordre inférieur) ou `MONTANT_FIXE` ;
- `ordre` — les lignes sont appliquées par ordre croissant. Une TVA doit porter
  un ordre **supérieur** aux commissions qu'elle taxe ; le contraire est refusé ;
- `applicable_a` — `ACHAT`, `VENTE` ou `LES_DEUX` ;
- `taux` — **en fraction** : 0,6 % s'écrit `0.006`. Un taux supérieur à 1 est
  rejeté, car c'est presque toujours une saisie en pourcentage ;
- `minimum_perception` / `maximum_perception` — en XOF, si votre SGI en applique.

`frais.source_bareme` est obligatoire : indiquez le nom de la SGI et la date de
la grille. Un barème sans provenance n'est pas auditable.

Même exigence pour `fiscalite` : `source_reference`, `retenue_dividendes` et
`plus_values_imposables` doivent être renseignés d'après votre situation et votre
pays de résidence fiscale.

### Renseigner le calendrier

`config/jours_feries.yaml` associe un code pays UEMOA à une liste de dates. Il
est livré **vide, à dessein** : les jours fériés varient d'un État à l'autre et,
pour les fêtes mobiles, d'une année à l'autre. Une liste pré-remplie serait
fausse une année sur deux, et un calendrier faux fabrique silencieusement des
« séances manquantes » qui n'ont jamais existé.

Le pays de la place de cotation (`marche.pays_place`) est celui dont les jours
fériés **ferment la bourse**. Les fériés des autres États n'interrompent pas la
séance : ils servent à expliquer une absence de transaction sur les valeurs des
émetteurs concernés. Le système le signale, il ne comble jamais le trou.

Hors de la période `calendrier.couverture_debut` → `couverture_fin`, toute
question posée au calendrier lève une erreur plutôt que de répondre au hasard.

---

## Choix de conception

### Aucune donnée inventée

Le dépôt ne contient **aucun** ticker, nom de société, secteur, taux de
commission, taux d'imposition, jour férié ni URL de source. Ce qui n'a pas été
vérifié n'est pas écrit : à la place, un champ de configuration obligatoire et un
message qui dit où chercher. Un test automatisé
(`test_les_fichiers_exemples_ne_contiennent_aucun_taux`) vérifie que les fichiers
d'exemple restent vides de tout barème.

Les données des tests portent des tickers volontairement improbables (`TEST1`,
`TEST2`…) pour qu'aucun chiffre du dépôt ne puisse être pris pour une donnée de
marché.

### Le XOF est un entier

Le franc CFA ne circule pas en centimes : tout montant est un `int`. Les taux et
prix de revient unitaires sont des `Decimal` — jamais de `float` sur de l'argent.
L'arrondi ne se produit qu'en un point nommé, avec un mode choisi en
configuration (`general.mode_arrondi`).

Sur une facture, **chaque ligne est arrondie puis les lignes sont sommées** ;
arrondir la somme donnerait un total différent. Ce choix est figé par un test.

### Séance sans transaction ≠ cours inchangé

C'est le cœur de l'adaptation à l'illiquidité. Une `Cotation` porte un
`statut_seance` explicite (`COTEE`, `SANS_TRANSACTION`, `SUSPENDUE`, `FERMEE`,
`INCONNU`) et expose `cours_effectivement_traite`, qui ne renvoie une valeur que
s'il y a eu échange. Un cours de référence reconduit est conservé, mais n'alimente
aucun indicateur.

`INCONNU` n'est jamais assimilé à `SANS_TRANSACTION` : ne pas savoir n'est pas
savoir qu'il ne s'est rien passé.

### Écriture idempotente et corrections tracées

La clé d'un enregistrement est `ticker + date de séance + source`. Rejouer une
collecte ne crée ni doublon ni révision : le contenu de marché est comparé par
empreinte, hors métadonnées de collecte.

Quand une source corrige une cote, l'ancienne version est **archivée** dans
`cotations_revisions` avant écrasement et le numéro de révision est incrémenté.
Aucune valeur observée n'est perdue — c'est ce qui permet de rejouer une analyse
telle qu'elle était calculable avant la correction.

La clé inclut la source : deux sources peuvent servir la même séance sans
s'écraser. L'arbitrage se fait à la lecture, par priorité déclarée.

### Séries ajustée et non ajustée

`cotations` contient la série **non ajustée** — la seule donnée observée. La série
ajustée des dividendes et des divisions est **recalculée** à la demande
(`brvm.domain.ajustement`), jamais stockée comme vérité première : un facteur figé
devient faux dès qu'une opération sur titre est corrigée.

L'ajustement est rétroactif : le facteur d'une séance est le produit des facteurs
des opérations détachées **après** elle. Le bord droit de la série ajustée est
donc égal à la série brute.

### Absence de biais d'anticipation

`ajuster_serie(..., jusqu_a=T)` ne prend en compte que les opérations détachées
jusqu'à `T`. Un backtest positionné à la barre *T* obtient exactement la série
qu'un opérateur aurait pu construire ce jour-là. Sans ce paramètre, la série
ajustée d'aujourd'hui incorpore des dividendes futurs et biaiserait tout signal
calculé dessus.

Le facteur d'un dividende est assis sur le dernier cours **réellement traité**
avant le détachement, et non sur un cours reconduit : sur une valeur peu liquide,
la veille du détachement peut n'avoir donné lieu à aucun échange.

### Anomalies : signalées, jamais corrigées

Un dividende supérieur au dernier cours traité, une opération sur titre non
modélisée, un ticker coté absent du référentiel, une année de calendrier sans
férié déclaré : chacun de ces cas produit un avertissement explicite ou une entrée
en quarantaine. Aucun n'est réparé en devinant.

---

## Arborescence

```
brvm/
├── config/
│   ├── config.exemple.yaml          fichier unique commenté, champs obligatoires vides
│   ├── jours_feries.exemple.yaml    calendrier UEMOA, à renseigner
│   └── univers.exemple.csv          univers suivi, à renseigner
├── src/brvm/
│   ├── config/      schéma de configuration + chargement à messages actionnables
│   ├── domain/      enums, arithmétique XOF, calendrier, modèles, ajustement OST
│   ├── storage/     schéma SQL, connexion/migration, dépôts idempotents
│   ├── ingestion/   couche 3 — à venir
│   ├── indicators/  couche 4 — à venir
│   ├── portfolio/   couche 5 — à venir
│   ├── risk/        couche 6 — à venir
│   ├── backtest/    couche 6 — à venir
│   ├── app/         couche 7 — à venir
│   └── utils/       erreurs, journalisation structurée
└── tests/           193 tests, 95 % de couverture
```

Le stockage passe entièrement par `storage/base.py` et `storage/depots.py` : un
remplacement de SQLite par DuckDB resterait circonscrit à ces deux fichiers.

---

## Limites connues

- **Il n'existe pas de flux temps réel public et gratuit sur cette place.**
  « Temps réel » signifie ici : dernière donnée disponible, horodatée, avec son
  âge en minutes et un statut de fiabilité. Chaque écran affichera l'horodatage
  de la donnée la plus ancienne qu'il utilise.
- **Aucun connecteur réseau n'est activé par défaut.** Les URL et les structures
  de page n'ont pas été vérifiées par l'auteur du code ; elles sont à renseigner
  et à contrôler par l'utilisateur, en respectant le `robots.txt` et les
  conditions d'utilisation de la source.
- **Les augmentations de capital ne sont pas modélisées** dans l'ajustement : leur
  effet sur le cours dépend du prix de souscription et du ratio, qui ne figurent
  pas toujours dans les sources publiques. Elles sont signalées, pas ignorées en
  silence.
- **Un stop est difficilement exécutable sur une valeur peu liquide.** Les stops
  ATR de la couche risque seront accompagnés d'un avertissement explicite.
- **Le calendrier ne couvre que la période déclarée.** C'est un choix : mieux vaut
  une erreur qu'une réponse fondée sur un calendrier supposé.
- **La méthode de valorisation par défaut est le PMP**, FIFO étant calculé en
  parallèle pour l'analyse fiscale. Les deux peuvent diverger sur le montant de
  plus-value imposable ; c'est votre régime fiscal qui tranche, pas le logiciel.

---

## Tests

```bash
pytest -q                                   # tout
pytest tests/test_ajustement.py -q          # une couche
pytest --cov=brvm --cov-report=term-missing # couverture
```

La suite couvre en particulier : arrondis et minimum de perception, calendrier et
jours fériés par pays, refus des paramètres non renseignés, validation des
cotations aux frontières, distinction séance sans transaction / cours inchangé,
idempotence et historisation des corrections, ajustement des OST et absence de
biais d'anticipation.
