# Suivi BRVM — démarrage sur votre machine

Application de bureau, au sens propre : elle tourne **chez vous**, ne dépend
d'aucun service en ligne pour fonctionner, et ne transmet vos chiffres à
personne. L'interface s'ouvre dans votre navigateur, sur `127.0.0.1`.

## Ce dont vous avez besoin

Python 3.11 ou plus. Rien d'autre : le cœur du système ne dépend que de
pydantic, pandas et PyYAML, et l'interface web n'utilise aucune bibliothèque
tierce.

```bash
cd brvm
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e .
```

## Trois fichiers à renseigner

Le système **refuse de démarrer** tant qu'ils ne le sont pas, et le message
d'erreur énumère tout ce qui manque d'un coup. C'est voulu : aucune valeur par
défaut n'est substituée à un paramètre que vous seul connaissez.

```bash
cp config/config.sg-capital-2026.yaml config/config.yaml
cp config/jours_feries.exemple.yaml    config/jours_feries.yaml
cp config/univers.reference-2026-03-30.csv config/univers.csv
```

**1. `config/config.yaml`** — un seul champ empêche le chargement au départ :
`ingestion.agent_utilisateur`. Identifiez-vous auprès des serveurs que vous
interrogez, par exemple `suivi-brvm/1.0 (contact: vous@exemple.org)`.

Puis, avant toute décision engageant de l'argent, vérifiez le **barème de
frais** : le fichier livré porte 0,80 % de courtage et 18 % de TVA, relevés sur
un comparatif du 28/03/2026. Deux points restent à trancher avec votre SGI, et
ils sont commentés dans le fichier :

- le 0,80 % est-il **tout compris**, ou s'y ajoutent commission d'entreprise de
  marché et dépositaire central ?
- quel est le **taux exact des droits de garde** ? Le comparatif donne une
  fourchette de 0,25 % à 0,50 %. Tant qu'ils ne sont pas déclarés, le système
  vous avertit au démarrage que le coût de détention est sous-estimé.

**2. `config/jours_feries.yaml`** — livré **vide, à dessein**. Les jours fériés
varient d'un État de l'UEMOA à l'autre et, pour les fêtes mobiles, d'une année à
l'autre. Une liste pré-remplie serait fausse une année sur deux, et un
calendrier faux fabrique silencieusement des « séances manquantes » qui n'ont
jamais existé.

**3. `config/univers.csv`** — la liste des valeurs suivies. Le fichier de
référence livré vient d'une capture du 30/03/2026 : recoupez-le avec la cote
officielle et vérifiez les radiations et introductions survenues depuis.

## Utilisation courante

```bash
python -m brvm.app.cli --config config/config.yaml verifier     # contrôle la configuration
python -m brvm.app.cli --config config/config.yaml collecter    # récupère les cotations
python -m brvm.app.cli --config config/config.yaml servir       # ouvre l'interface
```

Puis http://127.0.0.1:8731 dans votre navigateur.

Autres commandes :

| Commande | Ce qu'elle fait |
|---|---|
| `etat` | recompose et affiche l'état, sans réseau |
| `cribler --capital 5000000` | classe toute la cote et chiffre une répartition |
| `exporter --sortie rapports/` | écrit le classeur du jour |
| `ordonnancer` | collecte aux heures déclarées |
| `publier --sortie marche.json` | instantané public, sans aucune donnée personnelle |

## Où sont vos données

Tout est dans `data/`, à côté du code : la base SQLite, les journaux, le cache
des requêtes. Rien ne sort de votre machine, hors les requêtes aux sources de
cotations que **vous** avez activées.

L'interface écoute sur `127.0.0.1` — votre machine et personne d'autre. Elle
affiche la composition de votre portefeuille et ne demande aucun mot de passe :
la rendre accessible au réseau (`--hote 0.0.0.0`) se demande explicitement, et
n'est pas recommandé sans authentification devant.

## Sauvegarde

Le dossier `data/` et vos trois fichiers de configuration. Le reste se réinstalle.

## Ce que le système ne fera jamais

Il ne dit pas quelle action va monter, ne promet aucun rendement et ne donne
aucun conseil en investissement. Il classe selon des critères que **vous**
pondérez, sur des données passées, et il refuse de calculer plutôt que de
produire un chiffre qu'il ne peut pas fonder.
