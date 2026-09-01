# Sources de données : ce qui est attesté, et par qui

Ce document existe pour une raison simple : le dépôt s'interdit d'inventer une
URL, une structure de page ou un schéma d'API. Tout ce qui est pré-rempli dans
`config/config.sg-capital-2026.yaml` doit donc pouvoir être remonté à une preuve
nommée, et tout ce qui ne l'est pas doit rester vide.

## Les trois niveaux de preuve employés ici

| Niveau | Ce que ça veut dire | Ce que le dépôt en fait |
|---|---|---|
| **Observé** | Quelqu'un a regardé la chose elle-même et l'a consignée. | Pré-rempli, avec la date de l'observation. |
| **Attesté par un tiers** | Un logiciel publié et maintenu exploite cette structure en production, et son code source la montre. | Pré-rempli, `actif: false`, avec la référence exacte du fichier source. |
| **Supposé** | Plausible, cohérent, non vérifié. | **Jamais écrit.** Le champ reste vide et la configuration échoue en le nommant. |

Aucune structure de ce document n'est au niveau « observé » par l'auteur du code :
l'environnement de développement n'avait pas accès aux hôtes concernés (le
mandataire sortant refusait la connexion). C'est précisément pourquoi les sources
réseau sont livrées **inactives**. Le niveau « attesté » fait gagner la saisie ; il
ne remplace pas votre vérification.

## Origine des attestations

Deux paquets R publiés, fournis par l'utilisateur, qui interrogent la BRVM :

- **`BRVM`** — Koffi Frederic SESSIE, Olabiyi Aurel Geoffroy ODJO (CRAN).
  Deux versions du dépôt ont été examinées, l'une plus récente que l'autre.

Ce ne sont ni des documents officiels de l'entreprise de marché, ni des
spécifications d'API. Ce sont des programmes qui fonctionnaient au moment où ils
ont été publiés. Un site peut avoir été refondu depuis.

---

## 1. API d'historique — `sikafinance.com`

**Attesté par** `R/brvm-get-data.R` et `R/create-all-markets.R`.
**Câblé** dans la source `sikafinance_historique` (`type: api_json`, inactive).

```
POST https://www.sikafinance.com/api/general/GetHistos
Content-Type: application/json

{"ticker": "SNTS.sn", "datedeb": "2026-01-01", "datefin": "2026-03-30", "xperiod": "0"}
```

Réponse : `{"lst": [{"Date": "30/03/2026", "Open": …, "High": …, "Low": …, "Close": …, "Volume": …}, …]}`

Points relevés dans le code, non déduits :

- **Deux formats de date différents.** Envoyé en `aaaa-mm-jj`, reçu en
  `jj/mm/aaaa`. C'est la raison d'être des deux champs `format_date` et
  `format_date_requete` : confondre les deux ne produit pas une erreur mais une
  séance décalée. Le connecteur refuse toute date non conforme au format déclaré
  plutôt que de la réinterpréter — `03/02` n'est jamais « rattrapé » en 2 mars.
- **`xperiod`** : `0` quotidien, `7` hebdomadaire, `30` mensuel, `91`
  trimestriel, `365` annuel. Seul le quotidien nous concerne.
- **Fenêtre de 89 jours.** Le paquet découpe l'historique en tranches de 89
  jours. C'est la seule profondeur attestée ; `fenetre_jours: 89` la reprend.
- **Suffixe pays du ticker.** L'identifiant attendu est `CODE.pp` en minuscules
  (`SNTS.sn`), pris dans la liste déroulante `dpShares` de la page d'accueil.
  D'où `gabarit_ticker: "{ticker}.{pays_bas}"` et la colonne `pays` d'`univers.csv`.
  Si un suffixe ne correspond pas, la valeur remonte en avertissement « n'a pas pu
  être collectée » — jamais en cours faux.
- **En-tête `Referer` par valeur.** Le paquet l'envoie ; il est reproduit parce
  qu'un auteur l'a constaté nécessaire, pas par précaution décorative. Le
  `User-Agent`, lui, n'est pas surchargeable : l'identité annoncée doit rester vraie.
- **Temporisation.** Le paquet attend ~0,11 s entre deux appels. La politique
  réseau du dépôt applique `ingestion.delai_entre_requetes_s` et, s'il est plus
  long, le `Crawl-delay` du `robots.txt`.

⚠️ C'est aussi la plateforme sur laquelle vous passez vos ordres. Une collecte
trop insistante n'est pas un risque technique, c'est un risque de compte. Lisez
les conditions d'utilisation avant d'activer.

## 2. Page de cote — site officiel de l'entreprise de marché

**Attesté par** `R/brvm-ticker.R`, `R/brvm-bysetor.R`, `R/brvm-top-flop.R`.
**Câblé** dans la source `brvm_officiel` (`type: web`, inactive).

```
GET https://www.brvm.org/en/cours-actions/0/status/200
```

Le paquet prend le **4e tableau** de la page (numérotation R à partir de 1 →
`index_tableau: 3` ici, à partir de 0) et travaille sur ces colonnes :

| Position | En-tête | Champ du système |
|---|---|---|
| 1 | *inconnu* | `ticker` |
| 2 | *inconnu* | — (raison sociale) |
| 3 | `Volume` | `volume_titres` |
| 4 | `Previous price` | `cours_precedent` |
| 5 | `Opening price` | `ouverture` |
| 6 | `Closing price` | `cloture` |
| 7 | `Change (%)` | — (recalculable) |

**Les deux premiers en-têtes sont marqués « inconnu » et le resteront ici.** Le
code R les renomme sans jamais citer leur intitulé d'origine : la preuve porte sur
leur *position*, pas sur leur *nom*. Écrire « Ticker » ou « Symbole » à leur place
serait une supposition déguisée en donnée. La configuration porte donc, à cette
ligne, un intitulé qui commence par « À RENSEIGNER » : la configuration se charge,
mais la collecte s'arrête sur « en-tête introuvable » tant que vous n'avez pas
relevé le vrai libellé :

```bash
python -m brvm.ingestion.capture --config config/config.yaml --source brvm_officiel
python -m brvm.ingestion.capture --lister-tableaux <fichier capturé>
```

Autres pages du même site, attestées au même niveau, **non câblées** faute d'un
besoin immédiat :

| Page | Tableau | Contenu |
|---|---|---|
| `/en/indices/status/200` | 4e | Indices |
| `/en/capitalisations/0/status/200` | — | Capitalisations |
| `/en/volumes/0/status/200` | — | Volumes échangés |
| `/en/summary` | 1er | Activité de la séance |

## 3. Rattachement pays des valeurs

**Attesté par** `R/brvm-company-country.R`.
**Utilisé** pour recouper `config/univers.reference-2026-03-30.csv`.

Sur les 44 valeurs présentes à la fois dans cette liste et dans la capture
utilisateur du 30/03/2026, **les deux sources s'accordent sur les 44 pays**, sans
une divergence. Deux relevés indépendants qui concordent ne valent pas une source
officielle, mais valent mieux qu'un seul.

Les écarts d'inventaire sont documentés en tête du fichier CSV et aucun n'a été
comblé en silence — en particulier `TTRC`, présent dans le paquet R mais que ses
propres auteurs ont mis en commentaire, n'est pas ajouté : son intitulé n'est
attesté nulle part et il faudrait l'inventer.

## 4. Sources écartées, et pourquoi

### `abourse.com` — bulletin de cote quotidien

**Attesté par** `R/brvm-boc.R` : `POST http://www.abourse.com/histoActionsJour.html`,
formulaire `{date, submit: "Valider"}`, réponse en tableau de 18 colonnes.

**Non câblé.** L'adresse est en **HTTP en clair**. Le client du dépôt n'accepte
que `https` et refuse explicitement le reste : sur un flux en clair, la requête et
la réponse sont lisibles et modifiables par tout intermédiaire, et un cours modifié
en transit entrerait en base sans que rien ne le signale. La règle n'a pas été
assouplie pour gagner une source : si ce site publie un jour en `https`, le
connecteur `api_json` ou `web` le prendra sans modification de code.

### `richbourse.com` — historiques et secteurs

**Attesté par** le paquet R : `https://www.richbourse.com/common/mouvements/technique/{TICKER}/status/200`
(séries OHLC et volumes intégrées dans des tableaux JavaScript de la page, avec
une temporisation d'1 s), et `https://www.richbourse.com/common/apprendre/liste-societes`
(+ `?page=2`, `?page=3`) pour les secteurs.

**Non câblé.** Les données y sont dans du JavaScript, pas dans un tableau HTML ni
dans une réponse JSON. Les extraire demanderait un analyseur d'expressions
régulières sur du code source de page — le genre d'analyseur qui casse en silence
à la première refonte. Si vous en avez besoin, l'extension propre est un nouvel
analyseur déclaré dans `brvm.ingestion.analyseurs`, pas un contournement.

---

## Ce qu'il vous reste à faire

1. Lire les conditions d'utilisation et le `robots.txt` de chaque source que vous
   comptez activer.
2. Ouvrir la page ou appeler l'API une fois, à la main, et comparer à ce document.
3. Corriger ce qui a changé, remplir l'en-tête manquant de la page de cote, puis
   passer `actif: true`.
4. Recouper les premiers cours collectés avec votre relevé de compte avant de
   fonder une décision dessus.

Le système est conçu pour qu'une erreur à ces étapes se voie : en-tête introuvable,
date non conforme, cours décimal, séance hors calendrier, variation hors seuil —
chacun de ces cas arrête la ligne concernée et laisse une anomalie nominative,
plutôt que de produire un chiffre plausible et faux.
