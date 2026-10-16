# Note méthodologique : analyse quantitative de SOLIBRA (SLBC), 01/01/2023 – 15/10/2026

## 1. Données
- **Cours et volumes** : `SOLIBRA_SLBC_2023_2026_ANALYSE.csv` (721 observations, du 02/01/2023 au 14/10/2026), importé du dépôt public `harzat/brvm-data-public` (commit ed5e3e3). Source secondaire unique ; origine déclarée par le dépôt : BRVM, SikaFinance, RicheBourse, sans traçabilité ligne à ligne.
- **Indice** : `Indice_BRVMC.csv` du même dépôt (BRVM Composite, sikafinance). Définition et composition non vérifiées.
- **Calendrier** : aucun calendrier officiel. La continuité quotidienne n'est donc pas démontrée.
- **Événements** : extraits du dépôt (suspension avis 054 du 02/04/2024, levée avis 227 du 11/09/2024, fractionnement avis 242 du 27/09/2024, dividendes). Les PDF des avis n'ont pas été ouverts.

## 2. Statut des cours
- `Close` est publié **non ajusté**. Le fractionnement 10 pour 1 du 30/09/2024 n'apparaît pas dans la série (9 500 FCFA le 26/09, 10 975 le 30/09).
- La base des cours est donc **indéterminée**. Aucun ajustement n'est appliqué. Tout rendement, performance, drawdown ou comparaison qui traverse le 30/09/2024 est **bloqué** (1 rendement), de même que tout rendement traversant la suspension (1 rendement).
- Les volumes avant et après le fractionnement sont des unités différentes : ils sont analysés par régime, sans comparaison directe.

## 3. Traitement des rendements
- Deux observations successives ne sont pas assimilées à deux séances successives. Chaque paire est classée :
  - **ouvrés consécutifs (continuité non démontrée)** : aucun jour ouvré civil entre les deux dates (637 rendements). C'est l'échantillon principal `R_Q`.
  - **jours ouvrés absents** : au moins un jour ouvré civil sans observation entre les deux dates (81). Ces rendements sont séparés et utilisés seulement en robustesse.
  - **bloqué** : traverse le fractionnement ou la suspension (2).
- Rendement simple `C_t/C_{t-1} - 1` et logarithmique `ln(C_t/C_{t-1})`.
- 573 rendements de `R_Q` ne touchent pas une séance à volume nul ; 64 en touchent une (volume 0 documenté par `Volume FCFA = 0`).

## 4. Statistiques et volatilité
- Asymétrie ajustée (Fisher-Pearson, `bias=False`) ; kurtosis d'excès ajustée (`fisher=True, bias=False`), nulle pour la loi normale.
- Volatilité **à la fréquence observée**. Aucune annualisation : la règle `σ√N` exige un nombre de séances par an documenté, absent ici. Pas d'hypothèse de 252 séances.
- Volatilité glissante sur 20 et 60 rendements admissibles, calculée séparément dans chaque segment.

## 5. VaR et Expected Shortfall
- Pertes positives, `L = −r` (rendement simple) ; niveaux 95 % et 99 %.
- Quantile empirique de méthode `inverted_cdf` ; ES = moyenne des `L ≥ VaR`. Nombre d'observations dans la queue donné.
- IC par **bootstrap à blocs mobiles** (longueur 5 ; 2 000 répliques ; graine fixe) : la dépendance temporelle est prise en compte. Ce bootstrap ne corrige pas les données manquantes ni les erreurs de la source.
- Queue < 30 observations : estimation signalée comme instable (VaR 99 % sur 7 observations).
- VaR à un jour, non étendue à plusieurs jours.

## 6. Diagnostics
- Jarque-Bera et Shapiro-Wilk (normalité) ; Ljung-Box (retards 5 et 10) sur rendements et carrés ; ARCH-LM (5 retards) ; ADF (AIC) et KPSS (retards automatiques) sur niveaux de log-cours et sur rendements.
- Tests par segment (S1, S3). Les p-valeurs KPSS sont bornées par l'implémentation (0,01 à 0,10).
- Une dizaine de tests sont présentés sans correction de multiplicité ; les retards sont fixés a priori.

## 7. Comparaison à l'indice
- Appariement : rendements dont la même paire de dates consécutives existe dans les deux séries sans jour ouvré absent (637 appariés).
- Pearson, Spearman ; régression MCO `r_SOLIBRA = α + β r_indice`, erreurs standards **HAC** de Newey-West, `maxlags = floor(4(n/100)^(2/9)) = 6`.
- La constante n'est pas qualifiée d'alpha CAPM (pas de taux sans risque).
- Limite : la composition de l'indice n'est pas vérifiée ; un lien mécanique est possible si SOLIBRA en est une composante.

## 8. Dividendes et rendement total
- Dividendes 2024 (détachement 25/07/2025) et 2025 (détachement 29/07/2026), montants bruts et nets transcrits du dépôt.
- Rendement total **indicatif** du 02/01/2025 au 14/10/2026 : base de prix non ajustée mais sans événement de capital documenté dans la fenêtre ; dividendes non vérifiés sur PDF.
- Le dividende 2023 (paiement antérieur au détachement) n'est pas utilisé.

## 9. Sharpe
- **Non calculé** : aucun taux sans risque documenté dans les fichiers joints. Aucun taux n'a été remplacé par zéro.

## 10. Robustesse
- Variantes : quotidiens admissibles, tous non bloqués, lacunes seules, sans séance à volume nul, sans 1 % extrêmes (pour mesurer leur influence, non pour les retirer des résultats principaux), S1 seul, S3 seul, 2025 seul, 2026 partiel.

## 11. Limites
- Source secondaire unique, non validée contre les bulletins officiels (inaccessibles depuis l'environnement d'exécution).
- Calendrier officiel absent : aucune couverture de séances démontrée ; 149 jours ouvrés civils sans ligne (dont 57 retirés en amont par le dépôt, 92 non expliqués) et 115 jours en suspension.
- Fractionnement 2024 non confirmé dans les cours ; les performances et drawdowns sont donc par segment.
- Volume FCFA non vérifié ; aucune conclusion de liquidité.
- Les conclusions portent sur les données publiées par cette source, pas sur les cotations officielles de la BRVM.

## 12. Reproduction
`ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026.ipynb` ou `python3 analyse_quantitative_solibra.py` dans ce dossier, avec `BASE_SOLIBRA_SLBC_2023_2026.zip` dans le dossier courant ou le dossier parent. Versions : voir `resultats/versions.txt`.
