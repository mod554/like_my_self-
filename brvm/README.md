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
| 3 — Ingestion | Interface `DataSource`, connecteur fichier opérationnel, connecteurs web et API JSON à schéma déclaré, référentiel d'univers, politique réseau, anomalies et quarantaine | ✅ livrée |
| 4 — Analyse technique | SMA, EMA, RSI, MACD, Bollinger, ATR, OBV, momentum, extrêmes glissants, score de confiance liquidité, signaux | ✅ livrée |
| 5 — Portefeuille | PMP et FIFO, moteur de frais, fiscalité, TWR, TRI, simulateur d'ordre | ✅ livrée |
| 6 — Risque et backtest | Limites de concentration, contrainte de liquidité, stops ATR, moteur événementiel walk-forward | ✅ livrée |
| 7 — Exploitation | Ordonnanceur bridé par le calendrier, alertes fichier/courriel/webhook, tableau de bord, export tableur, ligne de commande | ✅ livrée |
| 8 — Interface | Système de design « Cote & Papier », serveur local sans dépendance, interface web hors ligne | ✅ livrée |
| 9 — Analyse de marché | Criblage de toute la cote, classements par horizon déclaré, référentiel fondamental, proposition de répartition et rééquilibrage | ✅ livrée |

---

## Installation

Python 3.11 ou plus.

```bash
cd brvm
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Le cœur du système ne dépend que de pydantic, pandas et PyYAML. Quatre extras
sont **facultatifs**, et leur absence n'empêche jamais de travailler :

| Extra | Ce qu'il ajoute | Ce qui le remplace sans lui |
|---|---|---|
| `tableur` | export Excel (openpyxl) | `exporter --texte`, même information |
| `ordonnanceur` | planificateur APScheduler | `Ordonnanceur.boucle()`, sans dépendance |
| `tableau` | tableau de bord Streamlit | `servir` (interface web, sans dépendance) |
| `dev` | pytest, ruff, mypy | — |

Chaque module concerné dit lequel installer si vous en avez besoin, plutôt que de
lever une erreur d'import.

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

## Collecter des cotations

### Où passent les ordres, où passent les données

Ce sont deux choses différentes, et la configuration les sépare :

- **Les ordres** sont acheminés par une **SGI**, chez qui vous tenez votre
  compte-titres. C'est elle qui vous facture, et c'est **sa grille tarifaire**
  qu'il faut recopier dans `frais.lignes`. Un portail d'information n'exécute
  aucun ordre et ne détermine aucun frais.
- **Les données** peuvent venir d'ailleurs : d'un portail que vous consultez, ou
  d'un export que vous produisez vous-même.

### Le connecteur fichier fonctionne tout de suite

`type: fichier_csv` ne dépend d'aucune source extérieure et fait tourner tout le
reste du système. Créez le modèle, remplissez-le, collectez :

```python
from brvm.ingestion.fichier import SourceFichier

SourceFichier.ecrire_modele(Path("data/cotations_manuelles.csv"))
```

Une cellule vide y signifie « non publié », jamais zéro. Et si vous laissez
`statut_seance` vide avec un volume nul, le statut retenu est `INCONNU` : le
système ne suppose pas qu'il s'agit d'une séance sans transaction.

### Renseigner l'univers suivi

Le référentiel des valeurs est une **donnée de configuration**, pas une déduction
de ce que les sources publient : une source qui cesse de coter une valeur ne doit
pas la faire disparaître du portefeuille, et une source qui en invente une ne doit
pas l'y ajouter.

```bash
cp config/univers.reference-2026-03-30.csv config/univers.csv
```

Ce fichier de référence liste 48 valeurs relevées sur une capture du 30/03/2026.
Sa colonne `pays` a été recoupée avec une seconde source indépendante — les deux
s'accordent sur les 44 valeurs communes, sans divergence. Les écarts d'inventaire
entre les deux relevés sont documentés en tête du fichier, et aucun n'a été comblé
en inventant un intitulé. **Ce n'est pas la cote officielle** : recoupez-la avant
d'en dépendre.

Une ligne mal formée arrête le chargement en nommant son numéro. Un ISIN dont la
clé de contrôle est fausse est refusé — c'est une erreur de saisie, pas une donnée
à propager. Une colonne vide signifie « non renseigné », jamais une chaîne vide.

### Activer une source d'API JSON

`type: api_json` interroge une API **valeur par valeur**, sur une fenêtre de
dates, selon le schéma que vous déclarez dans le bloc `api` : chemin menant à la
liste d'enregistrements, correspondance des champs, corps de la requête, formats
de date. Rien n'est deviné ; sans bloc `api`, la source refuse d'exister.

Deux traits méritent d'être connus avant de s'en servir :

- **Les formats de date d'envoi et de réception sont déclarés séparément**
  (`format_date_requete` et `format_date`), parce qu'une API peut attendre
  `2026-03-30` et répondre `30/03/2026`. Une date qui ne respecte pas le format
  déclaré n'est **jamais** réinterprétée : le format est précisément ce qui
  distingue le 3 février du 2 mars dans `03/02`. La réponse est écartée avec le
  message qui dit quoi corriger, plutôt qu'importée avec une séance décalée.
- **Par défaut, seule la séance visée est retenue** de la fenêtre reçue. Pour un
  rattrapage d'historique, passez `historique: true` le temps d'un cycle : les
  barres anciennes seront alors signalées « périmées » par le contrôle de
  fraîcheur, ce qui est le comportement attendu et non un défaut.

Une valeur injoignable n'interrompt pas la collecte des autres : elle remonte en
avertissement nominatif, et la collecte est marquée `PARTIEL`.

### Activer une source web

Aucun connecteur réseau n'est livré avec des sélecteurs. Aucune URL, aucun
`robots.txt` et aucune structure de page n'ont été vérifiés par l'auteur du code —
l'environnement de développement n'avait pas accès aux sites concernés. Écrire des
sélecteurs sans les avoir vus produirait des cours faux **sans le signaler**, ce
qui est le pire résultat possible pour un outil de suivi de portefeuille.

À la place, vous décrivez la page et le système exécute votre description :

```bash
# 1. La marche à suivre complète
python -m brvm.ingestion.capture --plan

# 2. Capturer la page (robots.txt respecté, identité annoncée)
python -m brvm.ingestion.capture --config config/config.yaml --source sikafinance

# 3. Repérer le tableau des cotations et ses en-têtes
python -m brvm.ingestion.capture --lister-tableaux data/captures/sikafinance-….html
```

Puis reportez dans `sources[].analyseur` le rang du tableau et la correspondance
entre chaque en-tête et un champ du système. Tant que ce bloc est absent, la
source refuse de collecter et rappelle la procédure.

Avant d'activer une source, lisez ses conditions d'utilisation et son
`robots.txt`. Le connecteur revérifie le `robots.txt` à chaque exécution et
s'abstient s'il est illisible, mais la décision d'ensemble vous revient.

**Si la page charge ses cotations en JavaScript**, l'analyseur de tableaux ne
verra rien — et le dira. Aucun contournement n'est fourni : restez sur le fichier
manuel, ou trouvez une réponse de données documentée.

### Ce qui est pré-rempli, et sur quelle preuve

`config/config.sg-capital-2026.yaml` contient deux sources réseau pré-remplies et
**inactives** : la page de cote du site officiel, et une API d'historique. Leurs
adresses, leurs schémas et leurs formats de date ne sont pas devinés — ils sont
relevés dans le code source de paquets R publiés qui les exploitent.

C'est un niveau de preuve intermédiaire, et il est traité comme tel :
[`docs/sources-verifiees.md`](docs/sources-verifiees.md) donne, pour chaque
structure, le fichier exact d'où elle vient, ce qui reste inconnu et pourquoi, et
les deux sources écartées avec leur motif — l'une parce qu'elle ne publie qu'en
HTTP en clair, l'autre parce que ses données sont dans du JavaScript.

### Politique réseau appliquée

| Garde-fou | Comportement |
|---|---|
| `robots.txt` | Consulté avant toute requête. `Crawl-delay` annoncé respecté s'il est plus long que le délai configuré. Un `robots.txt` en erreur serveur **interdit** la collecte : dans le doute, on s'abstient. |
| Temporisation | Délai minimal configurable entre deux requêtes vers le même hôte. |
| Cache | Une réponse encore fraîche évite une requête inutile. |
| Reprises | Recul exponentiel, sur incident transitoire seulement. Un 404 n'est jamais réessayé. |
| Mode dégradé | Toutes les tentatives ayant échoué, une entrée de cache périmée est servie, **explicitement marquée comme telle** et datée. Jamais de valeur fabriquée. |
| Schéma | `https` exclusivement. |

Une source qui tombe n'emporte jamais la collecte des autres : son échec devient
une anomalie et une entrée de journal.

### Ce qui est contrôlé à l'ingestion

Chaque contrôle **signale**, ne corrige jamais. La gravité décide seule du sort de
l'enregistrement : `AVERTISSEMENT` marque la cotation `SUSPECTE` (elle reste
exploitable, l'écran le signale) ; `BLOQUANTE` la met en `QUARANTAINE` — écrite en
base pour investigation, exclue de tous les calculs.

| Contrôle | Gravité |
|---|---|
| Ligne illisible par le connecteur | bloquante |
| Variation au-delà du seuil réglementaire configuré | bloquante (paramétrable) |
| Séance datée dans le futur | bloquante |
| Séance un jour que le calendrier ne reconnaît pas | bloquante |
| Même séance deux fois dans une collecte | bloquante |
| Montant échangé incompatible avec quantité × cours | avertissement |
| Carnet inversé (limite d'achat au-dessus de la limite de vente) | avertissement |
| Donnée plus vieille que l'âge toléré pour la source | avertissement |
| Ticker absent du référentiel | avertissement |
| Séance attendue au calendrier et non reçue | avertissement |

Les identifiants d'anomalie sont déterministes : rejouer une collecte ne les
multiplie pas.

---

## Analyse technique

Les indicateurs usuels ne sont pas transposables tels quels à un marché où une
valeur peut ne pas coter pendant une semaine. Quatre décisions gouvernent cette
couche, et chacune est visible dans la sortie.

### Une séance sans transaction n'est pas une séance à cours inchangé

Chaque barre porte son origine :

| Origine | Signification |
|---|---|
| `COTEE` | une transaction a eu lieu |
| `REPORTEE` | aucune transaction ; le dernier cours traité est reporté, dans la limite configurée |
| `ABSENTE` | aucune transaction et limite de report dépassée — le trou reste un trou |

Une barre reportée n'a **ni ouverture, ni amplitude, ni volume**. Les inventer
égaux à la clôture affirmerait une volatilité nulle, ce qui est une affirmation,
pas une absence d'information.

### Le système refuse de calculer plutôt que de produire un chiffre creux

Si la part de séances réellement cotées dans la fenêtre tombe sous
`indicateurs.ratio_minimum_seances_cotees`, la valeur est remplacée par un refus
motivé :

```
MM20 (SNTS) : non calculé — seulement 7 séance(s) réellement cotée(s)
sur 20 dans la fenêtre, sous le seuil configuré de 60 %
```

Chaque point publié porte, avec sa valeur, le nombre de séances cotées de sa
fenêtre, le taux de report, et l'ancienneté de la dernière transaction.

### Les indicateurs d'amplitude et de volume ne voient que les séances cotées

L'ATR et l'OBV ne consomment que les barres `COTEE`, puis leur résultat est
reporté avec son ancienneté. La raison est concrète : alimenter l'ATR avec des
séances sans transaction ferait tendre la volatilité mesurée vers zéro, et donc
placer des stops **d'autant plus serrés que la valeur est illiquide** — exactement
l'inverse du bon sens. Un test le vérifie.

### Aucun signal n'est exécutable sur la barre qui l'a fait naître

La clôture d'une séance n'est connue qu'une fois la séance terminée. Chaque
`Signal` porte donc deux dates : `date_constat` et `date_execution`, cette
dernière étant la séance suivante du calendrier. Le modèle refuse d'être
construit autrement.

Les calculs eux-mêmes sont testés pour leur **causalité** : tronquer la série
juste après l'indice *i* ne change aucune valeur jusqu'à *i*. C'est cette
propriété qui rend un backtest honnête.

### Score de confiance

Chaque résultat porte un score de liquidité, produit de trois composantes
rapportées séparément :

- **assiduité** — part de séances réellement cotées ;
- **profondeur** — montant quotidien moyen échangé, rapporté à la référence configurée ;
- **étroitesse** — largeur de fourchette achat/vente, rapportée à la référence configurée.

C'est un **produit**, pas une moyenne : une valeur qui cote tous les jours mais
qu'on ne peut acheter qu'avec 20 % d'écart au carnet n'est pas « moyennement
liquide ». Quand la source ne publie pas de fourchette, le score le dit et se
déclare optimiste.

Ces signaux sont des franchissements mécaniques. Leur valeur prédictive n'est
établie par rien, et le score de confiance dit surtout à quel point la donnée
sous-jacente est mince.

---

## Portefeuille, frais réels et fiscalité

### Le coût affiché n'est jamais le coût réel

Le moteur applique votre barème ligne à ligne et rend le décompte tel qu'il
devrait figurer sur l'avis d'opéré :

```
ACHAT 7 × 28 400 XOF
  Montant brut............................................         198 800 XOF
  Commission de courtage SGI (0.8000%)                               1 590 XOF
  TVA sur commissions (18.0000%)                                       286 XOF
  Total des frais.........................................           1 876 XOF
  Montant net.............................................         200 676 XOF
  Prix de revient unitaire                                        28668.00 XOF
  Seuil de rentabilité....................................          28 942 XOF soit +1.91%
```

Trois règles de calcul, vérifiables sur un avis réel :

- **chaque ligne est arrondie, puis les lignes sont sommées.** Arrondir la somme
  donnerait un total différent de celui facturé ;
- **une ligne assise sur le total des commissions ne taxe pas une autre taxe.**
  Pour qu'un forfait échappe à la TVA, donnez-lui un ordre supérieur : c'est
  l'ordre déclaré qui décide de tout ;
- **le minimum de perception s'applique à la ligne, puis au total**, et un
  complément global apparaît comme une ligne nommée — la somme des lignes fait
  toujours le total.

Les **frais récurrents** (droits de garde, tenue de compte) sont modélisés à
part : ils ne se déclenchent pas à l'achat, ils courent tant que la ligne est
détenue. Le système avertit au démarrage si aucun n'est déclaré.

### Le seuil de rentabilité

C'est le chiffre que le simulateur existe pour produire : **le cours à partir
duquel l'opération devient bénéficiaire**, frais d'achat, frais de revente et
impôt compris. Il est cherché par dichotomie, parce que minimums de perception
et paliers d'imposition rendent la fonction de coût discontinue — une formule
fermée cesserait d'être juste dès qu'un barème comporte un palier.

Sur un petit ordre, l'écart surprend : le voir avant de passer l'ordre change
les décisions.

### PMP et FIFO répondent à deux questions différentes

| | PMP | FIFO |
|---|---|---|
| Prix de revient | moyenne pondérée | par lot |
| Cession | une par vente | **une par lot consommé** |
| Durée de détention des titres cédés | **`None`** | connue |

En PMP, après un achat les titres perdent leur identité : la durée de détention
des titres cédés n'existe plus. Le système renvoie `None` plutôt qu'une durée
inventée. **Si votre fiscalité comporte une exonération pour durée de détention,
seule la méthode FIFO permet de la calculer.**

Les deux méthodes donnent le même prix de revient tant qu'aucune vente n'a eu
lieu, et divergent ensuite sur le montant de plus-value réalisée — donc sur
l'impôt.

Les frais réellement facturés, lorsqu'ils figurent sur la transaction,
l'emportent toujours sur ceux que le barème recalculerait : **c'est l'avis
d'opéré qui fait foi, pas le modèle.**

### Plus-value latente : brute et nette

Ce qui resterait si vous vendiez aujourd'hui, c'est le produit *après* frais de
cession et après impôt. Sur une petite ligne, l'écart entre brute et nette
dépasse souvent le gain affiché. Les deux sont calculées et présentées côte à
côte.

### TWR et TRI

Deux chiffres, deux questions :

- **TWR** neutralise les apports et retraits. Il mesure la qualité des choix de
  valeurs, indépendamment du moment où l'argent est entré. C'est ce qui se
  compare à un indice.
- **TRI** tient compte du calendrier des versements. Il mesure ce que *votre*
  argent a rapporté. Sur une stratégie d'investissement progressif, les deux
  divergent nettement.

Aucun n'est annualisé automatiquement : sur une période de moins d'un an,
`annualise()` renvoie `None` plutôt qu'un chiffre spectaculaire et dépourvu de
sens. Le TRI est résolu par dichotomie — elle ne diverge pas et donne un
résultat reproductible — et renvoie `None` avec un motif quand aucun taux
n'existe.

### Fraîcheur affichée

Toute valorisation porte l'horodatage de sa donnée la plus ancienne :

```
Donnée la plus ancienne utilisée : 2026-08-21T15:30:00+00:00 (10080 minutes)
```

Une ligne sans cours **n'est pas comptée pour zéro** : elle est signalée comme
non valorisée, et le total du portefeuille est déclaré incomplet.

---

## Risque

### La corrélation ne se calcule que sur les séances communes

C'est l'adaptation la plus importante de cette couche. Calculée sur des séries à
cours reportés, une corrélation mesure surtout que deux valeurs n'ont pas coté
les mêmes jours : **deux titres immobiles paraissent parfaitement corrélés alors
qu'aucune information ne les relie**. Une diversification bâtie là-dessus est une
illusion, et c'est le genre d'illusion qui coûte cher le jour où le marché bouge.

Le système n'apparie donc que les séances où les **deux** valeurs ont réellement
échangé, et refuse de répondre en dessous d'un nombre configuré de séances
communes. Même logique pour la volatilité : une suite de rendements nuls faute
d'échange n'est pas une faible volatilité.

### Le délai de débouclage

Une position peut être parfaitement dimensionnée en pourcentage du portefeuille
et rester impossible à solder en moins de trois semaines :

```
TEST1 : 250 titres, volume moyen 100/séance, débit tenable 25/séance
        → environ 10.0 séance(s) pour solder la ligne
```

Le débit tenable est la part configurée du volume quotidien moyen — calculé sur
les seules séances cotées, car diviser par des jours où rien ne pouvait
s'échanger fausserait la mesure.

### Les stops ATR, avec leur avertissement

Le niveau est calculé ; son exécutabilité ne l'est pas. Sur une valeur qui ne
cote pas tous les jours, un stop peut n'être franchi qu'à l'ouverture d'une
séance ultérieure, à un cours sensiblement inférieur au seuil. L'avertissement
accompagne **systématiquement** le chiffre, et s'enrichit quand la ligne demande
plusieurs séances pour être soldée :

> Un stop est difficilement exécutable sur une valeur peu liquide […] Considérez
> ce niveau comme un signal de révision, pas comme une protection acquise.

Les contrôles de concentration ne bloquent rien : ils constatent, chiffrent et
expliquent. Une valeur absente du référentiel est signalée, jamais rangée dans
une catégorie inventée.

---

## Backtest

### L'ordre des opérations n'est pas négociable

Sur chaque barre :

1. **exécuter** les intentions décidées à la barre *précédente*, à l'ouverture ;
2. **valoriser** le portefeuille à la clôture ;
3. **décider** pour la barre suivante, sur une vue tronquée à cette barre incluse.

Une intention ne peut donc jamais être exécutée sur la barre qui l'a produite.

Le biais d'anticipation n'est pas évité par discipline mais **par construction** :
une stratégie ne reçoit qu'un `ContexteBarre`, et celui-ci ne contient que des
séries tronquées. Il n'existe aucun chemin par lequel une stratégie pourrait
consulter une barre future, même par erreur. Deux tests le vérifient.

### Hypothèses d'exécution, toutes conservatrices

| Règle | Effet |
|---|---|
| Exécution à l'ouverture de la barre suivante | jamais à la clôture qui a produit le signal |
| Glissement | appliqué en défaveur de l'opérateur, des deux côtés |
| Plafond de volume | un ordre ne consomme qu'une part configurée du volume de la séance ; au-delà, exécution partielle consignée |
| Séance sans transaction | aucune exécution — l'ordre n'aurait pas trouvé de contrepartie |
| Cours d'ouverture non publié | refus par défaut ; le repli sur la clôture de la veille est un choix explicite en configuration |
| Frais | barème réel appliqué à chaque opération simulée |

Supposer qu'un gros ordre passe entièrement sur une valeur peu liquide est la
façon la plus rapide de fabriquer une performance imaginaire.

### La métrique la plus utile n'est pas le rendement

C'est la **part des coûts dans la performance brute**. Une stratégie qui dégage
12 % brut et 4 % net n'est pas une stratégie à 4 % : c'est une stratégie dont les
deux tiers du travail sont allés à l'intermédiaire. Le voir change la fréquence à
laquelle on négocie.

Quand la performance brute est nulle ou négative, le ratio n'est pas calculé — il
n'aurait aucun sens — et un avertissement dit combien de frais ont été payés pour
rien.

### Walk-forward

Optimiser sur tout l'historique puis présenter le résultat comme une performance
est la faute la plus commune de l'analyse technique. Avec assez de paramètres, on
trouve toujours une combinaison qui aurait fonctionné.

Les paramètres sont choisis sur la partie **apprentissage** de chaque fenêtre,
puis appliqués tels quels à la partie **validation**, qui n'a pas servi au choix.
Seuls les résultats de validation comptent, et l'écart entre les deux est
explicitement signalé :

> L'apprentissage promettait 18,40 %, la validation a donné 3,10 %. Seul le second
> chiffre a une valeur ; l'écart mesure ce que l'optimisation avait d'illusoire.

Le système signale aussi quand les paramètres retenus changent d'une fenêtre à
l'autre : un réglage qui suit le bruit plutôt qu'une régularité.

La stratégie d'achat-conservation sert de comparatif. Une stratégie active qui ne
la bat pas **après frais** n'a rien démontré — et sur un marché où chaque
aller-retour coûte deux commissions et deux TVA, c'est un comparatif exigeant.

---

## Exploitation

Une seule commande fait tout ; les autres en sont des morceaux.

```bash
python -m brvm.app.cli verifier   --config config/config.yaml   # que va-t-il faire ?
python -m brvm.app.cli collecter  --config config/config.yaml   # cycle complet
python -m brvm.app.cli etat       --config config/config.yaml   # état, sans réseau
python -m brvm.app.cli exporter   --config config/config.yaml --sortie rapports/
python -m brvm.app.cli ordonnancer --config config/config.yaml --occurrences 5
```

Les codes de sortie distinguent trois situations, pour qu'un cron extérieur
puisse réagir : `0` tout va bien, `1` la commande n'a pas pu s'exécuter, `2` elle
a tourné mais quelque chose s'est mal passé — une source tombée, un canal
d'alerte injoignable, une donnée plus vieille que le seuil déclaré.

### Une seule lecture, servie à toutes les sorties

Le tableau de bord, l'export tableur et les alertes lisent **le même objet**,
composé une fois par `brvm.app.etat.assembler`. Un écran qui recalculerait pour
son compte finirait par afficher un total qui ne correspond à aucun autre, et
personne ne saurait lequel croire.

Cet objet accepte une **borne de connaissance** (`jusqu_a`) : rien de postérieur
n'est lu. Une restitution est donc rejouable à une date passée sans qu'aucun
calcul puisse consulter une séance qui n'existait pas encore.

### L'ordonnanceur ne collecte que les jours de séance

C'est toute la différence avec un cron ordinaire. Deux conditions doivent être
réunies : l'expression cron correspond à l'instant, **et** le calendrier
reconnaît une séance ce jour-là. Un jour férié dans l'un des États de l'Union
ferme la bourse ; lancer une collecte ce jour-là ne rapporterait que la page de
la veille, prise pour celle du jour.

Hors de la période couverte par le calendrier, le système s'abstient plutôt que
de supposer une séance.

> **Convention : `0` = lundi**, comme `date.weekday()` et comme partout ailleurs
> ici — pas `0` = dimanche. Les jours ouvrés s'écrivent donc `0-4`. Écrire `1-5`
> désignerait mardi à samedi et sauterait tous les lundis **sans produire le
> moindre message**. L'expression est analysée au chargement de la configuration,
> et un test vérifie que les fichiers livrés respectent la convention.

APScheduler est facultatif : la politique de déclenchement est écrite sans lui et
`Ordonnanceur.boucle()` suffit à un poste qui reste allumé. `pip install -e
'.[ordonnanceur]'` l'ajoute si vous préférez un vrai planificateur.

### Alertes : des constats, jamais des conseils

Quatre familles, chacune activable séparément :

| Catégorie | Se déclenche quand |
|---|---|
| `ECHEC_SOURCE` | une collecte échoue, est servie depuis le cache, ou rejette des lignes |
| `DONNEE_PERIMEE` | un cours dépasse `alertes.age_donnee_max_minutes`, ou une ligne n'est pas valorisée |
| `SEUIL_RISQUE` | une limite de concentration est dépassée, ou une liquidité n'est pas mesurable |
| `SIGNAL_TECHNIQUE` | un franchissement est constaté — avec sa date d'exécution |

Trois canaux : **fichier** (JSON par ligne, fonctionne sans rien configurer
d'autre), **courriel** (SMTP, tous les paramètres obligatoires) et **webhook**
(`https` exclusivement — une alerte décrit la composition de votre portefeuille).

Le `User-Agent` n'est pas surchargeable par une source ou un canal : l'identité
annoncée doit rester vraie.

Un canal qui tombe n'emporte pas les autres, et une alerte que personne n'a reçue
reste dans le journal du système. Un constat déjà diffusé n'est pas réémis tant
qu'il n'a pas disparu puis réapparu : réémettre chaque jour la même alerte de
concentration finit par la rendre invisible.

Aucune alerte ne dit quoi faire. Celles qui portent un signal technique
répètent, dans leur texte, que le système constate un franchissement, ne prédit
aucun cours et ne promet aucun rendement.

### Le seuil de débouclage est facultatif, et c'est délibéré

Le délai de sortie d'une ligne est toujours calculé et affiché. Il ne déclenche
une alerte que si vous avez renseigné `risque.seances_max_debouclage`. Il n'existe
pas de délai « raisonnable » objectif : cela dépend de votre horizon, et le
système ne choisit pas à votre place.

En revanche, une liquidité **non mesurable** est signalée d'office : ne pas savoir
combien de temps il faut pour sortir n'est pas une bonne nouvelle.

### Tableau de bord et export

```bash
pip install -e '.[tableau]'
streamlit run src/brvm/app/tableau_de_bord.py -- --config config/config.yaml
```

Quatre onglets — portefeuille, signaux, risque, données — et **chacun commence
par le bandeau de fraîcheur**. Quand la donnée dépasse le seuil déclaré, le
bandeau passe en rouge et dit explicitement que les chiffres décrivent cette
date-là, pas aujourd'hui.

L'export tableur produit cinq feuilles (positions, signaux, risque, anomalies,
collectes), chacune portant le même bandeau en tête, et le nom du fichier est
horodaté — un export non daté est ininterprétable trois mois plus tard. Sans
`openpyxl`, `--texte` donne exactement la même information.

Le module Streamlit ne calcule rien : il ne fait qu'afficher l'état qu'on lui
donne. C'est ce qui permet de le vérifier par des tests sans lancer de serveur.

### Aucune performance chiffrée n'est publiée

Ni dans le tableau de bord, ni dans l'export. Le TWR et le TRI sont écrits et
testés (couche 5), mais les alimenter correctement suppose un **historique de
compte espèces** — apports, retraits, produit net des ventes, dividendes
encaissés, frais de garde — que le système n'enregistre pas encore.

Un rendement calculé sur la seule valeur des titres serait faux dès la première
ligne soldée : la sous-période se termine sur un portefeuille de valeur nulle, et
le rendement part à −100 % alors que l'argent est simplement passé en liquidités.
Chaque écran dit pourquoi le chiffre est absent, plutôt que d'en afficher un
plausible et faux.


## Interface web

```bash
python -m brvm.app.cli servir --config config/config.yaml
# → http://127.0.0.1:8731
```

Aucune dépendance : le serveur est en bibliothèque standard, la page est du HTML,
du CSS et du JavaScript natifs. Pas de build, pas de `npm`, pas de CDN. Les trois
polices sont **auto-hébergées** (200 Ko, sous-ensemble latin) : l'interface
fonctionne hors ligne et ne fuit rien vers un tiers.

Le serveur **écoute sur la machine elle-même** par défaut. Cette interface montre
la composition d'un portefeuille et ne demande aucun mot de passe ; l'ouvrir au
réseau se demande explicitement, et le message le dit.

### Le système de design

Direction, tokens, décisions et raisons : [`.interface-design/system.md`](.interface-design/system.md).
Construit avec le skill [`ui-ux-design-pro`](../.claude/skills/ui-ux-design-pro/)
(MIT, `saifyxpro`) et le skill `dataviz`.

Les couleurs viennent d'un lieu, pas d'un nuancier : l'**indigo** des tissus
teints du Sahel pour l'encre, le **papier** chaud d'un avis d'opéré pour les
surfaces, la **latérite** d'Abidjan pour les pertes, la **lagune** Ébrié pour les
gains, le **laiton** patiné des poids akan pour l'attention. Le duo *navy + or*
de toutes les applications de trading est écarté ; les titres sont en **serif**,
comme un bulletin imprimé, quand tous les tableaux de bord sont en sans-serif.

### La signature : la trame de séances

**Aucun chiffre n'apparaît sans la texture du silence derrière lui.** Une marque
par séance attendue : carré plein si la valeur a réellement coté, anneau creux si
le cours a été reporté, point pâle si la séance est absente.

Sur une place liquide, cette trame serait une barre pleine, donc muette. Ici,
elle dit d'un coup d'œil qu'une valeur cote 87 % des séances quand une autre en
cote 17 % — et un cours vu deux fois sur vingt ne vaut pas le même cours vu
dix-huit fois sur vingt.

La forme porte le sens, la couleur ne fait que l'appuyer : la trame reste lisible
sans distinction des couleurs et en contrastes forcés.

### Trois défauts du genre, écartés

| Défaut | Remplacé par |
|---|---|
| Le gros pourcentage vert/rouge en héros | le montant en XOF ; sur un cours reporté, un pourcentage est un mensonge |
| La sparkline lissée dans chaque carte | la trame discrète, qui montre les trous au lieu de les lisser ; sur la courbe, un segment reposant sur un cours reporté est **en pointillé** |
| Le camembert de répartition | des jauges avec la limite marquée — un camembert ne sait pas montrer une limite |

### Ce qui est vérifié, pas estimé

- **Contrastes mesurés sur le rendu réel**, en peignant les pixels. Le premier
  calcul opposait chaque ton à la surface principale ; or les micro-libellés
  s'affichent sur les en-têtes de tableau et sur les surfaces teintées. Deux tons
  ont été assombris. Calculer contre le mauvais fond donne un contrôle qui passe
  et une page qui échoue.
- **Aucune palette catégorielle** n'existe dans ce système : la forme retenue
  pour chaque donnée (jauge, série unique, trame d'états) l'a rendue inutile.
- **Zéro débordement horizontal** à 1440 px comme à 375 px, vérifié au navigateur.
- **Navigation au clavier** : lien d'évitement en premier, anneau de focus visible
  partout, aucun `outline: none` sans remplacement.
- **Aucun style en ligne** dans le document : la politique de sécurité de contenu
  les refuse, ce qui force à nommer chaque intention dans la feuille de style.

La politique de contenu interdit toute ressource distante. Si quelqu'un ajoute un
jour un script de CDN, la page cassera visiblement plutôt que d'exfiltrer
discrètement la composition d'un portefeuille.

---

## Analyse de marché

Les couches précédentes regardent **ce que vous détenez**. Celle-ci regarde
**ce qui existe** : elle lit tout l'univers, mesure chaque valeur, la classe
selon des profils que vous déclarez, et chiffre une répartition possible.

```bash
python -m brvm.app.cli --config config/config.yaml cribler
python -m brvm.app.cli --config config/config.yaml cribler --capital 5000000
python -m brvm.app.cli --config config/config.yaml cribler --capital 5000000 --horizon court_terme
```

L'interface web expose la même chose sous l'onglet **Marché**, avec le détail
critère par critère de chaque valeur.

### Ce que le système ne fait pas

Il ne dit pas quelle action va monter. Rien ici ne le sait, et votre propre
règle — *ne jamais promettre un rendement* — s'applique d'abord à cette couche.

Ce qu'il produit est un **classement mécanique de critères déclarés, sur données
passées**. Le vocabulaire s'y tient partout : on classe, on ne conseille pas.
« Meilleure opportunité » n'apparaît nulle part, ni dans le code ni dans les
sorties.

### La mesure et la pondération sont séparées

`brvm.market.analyse` **mesure** — les mêmes critères pour toutes les valeurs.
`brvm.market.horizons` **pondère** — selon les poids de votre configuration.

La séparation n'est pas cosmétique : sans elle, il serait impossible de savoir
si une valeur monte dans un classement parce qu'elle a changé ou parce que vous
avez changé les poids.

### Un critère non mesurable n'est jamais noté zéro

Zéro veut dire « mauvais ». L'absence veut dire « on ne sait pas ». Les deux ne
se traitent pas pareil : une note nulle pèse dans la moyenne, une absence en
sort le critère et **réduit la couverture**, qui est rapportée avec le score.

Sous la couverture minimale que vous déclarez, le score n'est pas rendu du tout.
Une moyenne sur deux critères parmi huit ne mesure pas la même chose qu'une
moyenne sur huit, et les présenter côte à côte dans un classement serait
trompeur.

### La confiance et la liquidité sont des portes, pas des critères

Elles **multiplient** le score au lieu d'y entrer. Une valeur au momentum
superbe qui cote trois fois par mois n'est pas une demi-occasion : elle n'est
pas jouable, et son score est annulé plutôt que pondéré.

Quand une confiance est jugée insuffisante, le motif nomme la composante qui
borne réellement — assiduité, profondeur ou étroitesse. La confiance est le
**produit** de ces trois facteurs : attribuer d'office une confiance faible à
des trous dans la série enverrait chercher au mauvais endroit une valeur qui
cote toutes les séances mais n'échange presque rien.

### Le long terme exige des fondamentaux, et ne retombe pas sur le prix

Aucun ratio fondamental ne se déduit d'une série de cours. Le référentiel
`config/fondamentaux.csv` est donc **rempli par vous**, depuis les rapports
annuels, avec la source de chaque chiffre — un montant sans provenance n'est pas
auditable.

Tant qu'il est vide, un profil marqué `exige_fondamentaux: true` ne classe rien
et le dit. Il ne se rabat pas sur la tendance des cours : classer un horizon de
plusieurs années sur la seule dynamique des prix serait une fabrication déguisée
en analyse.

Partez de `config/fondamentaux.exemple.csv`, qui documente chaque colonne.

### Les valeurs écartées ne disparaissent pas

Sur cette place, elles sont souvent la majorité. Chacune ressort avec sa raison :
série absente, trop courte, confiance sous le seuil, couverture insuffisante,
comptes non saisis. Un tableau qui les ferait disparaître donnerait de la cote
une image fausse, et laisserait croire à une couverture que le système n'a pas.

### La répartition proposée applique vos limites, et nomme celle qui a mordu

L'allocateur ne choisit rien. Il descend le classement et s'arrête à la première
limite qui mord — liquidité, concentration par ligne, par secteur, par pays,
montant minimal d'une ligne, nombre de lignes. Pour chaque ligne il indique
**laquelle** : c'est cette phrase, plus que le montant, qui rend la proposition
discutable, puisqu'elle montre ce qu'il faudrait changer pour obtenir autre
chose.

Deux natures de limites, qui ne se mesurent pas dans la même unité :

* la **liquidité** borne un nombre de titres. Le marché absorbe une quantité, et
  les frais n'en consomment aucune ;
* la **concentration** et le capital restant bornent un montant, et c'est le
  décaissement réel — frais compris — qui doit tenir dessous. Une limite de 20 %
  appliquée au montant brut rendrait une ligne à 20,3 %.

Quand l'enveloppe investissable n'a pas pu être remplie, les lignes retenues
pèsent plus lourd dans le portefeuille réel que dans l'enveloppe. L'allocateur
le dit, avec la cause et les remèdes : sans cela, il proposerait un portefeuille
que les contrôles de risque signaleraient aussitôt.

### Sans capital, aucune répartition n'est chiffrée

Ni la commande ni l'interface ne supposent votre capital. C'est la seule donnée
de cette couche que le système ne peut pas connaître, et la supposer produirait
une proposition d'apparence exacte et entièrement fausse.

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
│   ├── config.sg-capital-2026.yaml  exemple travaillé, sources réseau inactives
│   ├── jours_feries.exemple.yaml    calendrier UEMOA, à renseigner
│   ├── univers.exemple.csv          univers suivi, à renseigner
│   └── univers.reference-*.csv      48 valeurs relevées, pays recoupé
├── docs/
│   └── sources-verifiees.md         d'où vient chaque structure pré-remplie
├── .interface-design/
│   └── system.md                    direction, tokens, décisions de design
├── src/brvm/
│   ├── config/      schéma de configuration + chargement à messages actionnables
│   ├── domain/      enums, arithmétique XOF, calendrier, cron, modèles, ajustement OST
│   ├── storage/     schéma SQL, connexion/migration, dépôts idempotents
│   ├── ingestion/   DataSource, politique réseau, connecteurs, univers, anomalies, orchestrateur
│   ├── indicators/  série illiquidité-consciente, calculs, confiance, signaux
│   ├── portfolio/   frais, fiscalité, PMP/FIFO, valorisation, performance, simulateur
│   ├── risk/        volatilité, corrélation, drawdown, concentration, liquidité, stops
│   ├── backtest/    moteur événementiel, exécution conservatrice, métriques, walk-forward
│   ├── app/         état unique, alertes, ordonnanceur, export, API JSON, serveur, CLI
│   │   └── web/     interface : HTML, CSS, JS natifs, polices auto-hébergées
│   └── utils/       erreurs, journalisation structurée
└── tests/           810 tests, 94 % de couverture
```

Le stockage passe entièrement par `storage/base.py` et `storage/depots.py` : un
remplacement de SQLite par DuckDB resterait circonscrit à ces deux fichiers.

---

## Limites connues

- **Il n'existe pas de flux temps réel public et gratuit sur cette place.**
  « Temps réel » signifie ici : dernière donnée disponible, horodatée, avec son
  âge en minutes et un statut de fiabilité. Chaque écran affichera l'horodatage
  de la donnée la plus ancienne qu'il utilise.
- **Aucun connecteur réseau n'est activé par défaut.** Les adresses et structures
  pré-remplies dans l'exemple travaillé sont attestées par le code source de
  paquets tiers qui les exploitent, **jamais observées par l'auteur du code** :
  l'environnement de développement n'avait pas accès aux hôtes concernés. Un
  paquet publié peut avoir pris du retard sur une refonte de site. À vous de
  vérifier, en respectant le `robots.txt` et les conditions d'utilisation de la
  source. Voir [`docs/sources-verifiees.md`](docs/sources-verifiees.md).
- **Sur la page de cote officielle, l'en-tête de la colonne du code valeur reste
  inconnu.** La preuve disponible porte sur sa *position*, pas sur son *nom* : le
  code tiers la renomme sans citer son intitulé. Plutôt qu'un libellé plausible,
  la configuration porte une mention « À RENSEIGNER » — la collecte s'arrête sur
  « en-tête introuvable » tant qu'elle n'est pas corrigée.
- **Une page rendue en JavaScript n'est pas exploitable** par l'analyseur de
  tableaux, qui travaille sur le document servi par le serveur. Le connecteur le
  signale au lieu de renvoyer un tableau vide.
- **Les augmentations de capital ne sont pas modélisées** dans l'ajustement : leur
  effet sur le cours dépend du prix de souscription et du ratio, qui ne figurent
  pas toujours dans les sources publiques. Elles sont signalées, pas ignorées en
  silence.
- **Un stop est difficilement exécutable sur une valeur peu liquide.** Les stops
  ATR de la couche risque seront accompagnés d'un avertissement explicite.
- **Le calendrier ne couvre que la période déclarée.** C'est un choix : mieux vaut
  une erreur qu'une réponse fondée sur un calendrier supposé.
- **Aucune performance chiffrée n'est publiée** faute d'historique de compte
  espèces. Voir « Exploitation » ci-dessus : c'est un manque assumé, pas un oubli.
- **L'interface web n'a aucune authentification.** Elle écoute sur la machine
  elle-même par défaut. Ne l'exposez pas au réseau sans placer un contrôle
  d'accès devant.
- **Le tableau de bord et l'export ne rafraîchissent rien tout seuls.** Ils lisent
  la base telle qu'elle est ; c'est l'ordonnanceur ou la commande `collecter` qui
  l'alimente.
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
biais d'anticipation, respect du `robots.txt` et des reculs exponentiels, mode
dégradé sur cache périmé, extraction de tableaux HTML et correspondance de
colonnes déclarée, lecture stricte du référentiel d'univers, appels d'API en
POST avec un cache distinct par corps de requête, refus d'une date qui ne respecte
pas le format déclaré, chaque contrôle d'anomalie avec sa gravité, les valeurs de
référence de chaque indicateur, la causalité de tous les calculs,
l'impossibilité d'exécuter un signal sur la barre qui l'a produit, la porte du
calendrier devant l'ordonnanceur, la tolérance des alertes à un canal en panne,
et la présence du bandeau de fraîcheur sur chaque onglet du tableau de bord.
