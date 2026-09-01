# Système de design — « Cote & Papier »

Direction retenue pour le suivi de portefeuille BRVM. Ce document fait foi : toute
nouvelle vue s'y conforme, ou le modifie explicitement.

---

## Intent

**Qui est cette personne ?** Un investisseur particulier à Abidjan, qui ouvre
l'écran une fois par jour, après 15h30, quand la séance est close. Il n'arbitre
pas à la milliseconde : il vérifie ce qu'il détient, ce que ça lui a coûté, et si
quelque chose mérite son attention demain matin.

**Que doit-il accomplir ?** Vérifier. Pas « consulter un tableau de bord » :
vérifier que le cours affiché date bien d'aujourd'hui, que sa ligne n'a pas
dépassé une limite, qu'aucune donnée n'est partie en quarantaine.

**Quel effet cela doit-il faire ?** Celui d'un **relevé**, pas d'un terminal de
trading. Un document daté, signé, dont on peut suivre chaque chiffre jusqu'à sa
source. Calme. Aucune urgence fabriquée, aucun clignotement, aucun compteur qui
défile.

---

## Le monde chromatique

Les couleurs viennent d'un lieu, pas d'un nuancier.

| Élément du monde | Rôle dans l'interface |
|---|---|
| **Indigo** des tissus teints du Sahel | l'encre — texte, traits, marques cotées |
| **Papier** d'un avis d'opéré (blanc cassé chaud) | toutes les surfaces |
| **Latérite** des routes d'Abidjan | les pertes |
| **Lagune** Ébrié (vert-bleu éteint) | les gains |
| **Laiton** patiné des poids akan | l'attention — jamais l'alarme |
| **Indigo vif** | le seul accent interactif |

Le duo *navy + or* de toutes les applications de trading est explicitement écarté.

---

## Signature : la trame de séances

**Aucun chiffre n'apparaît sans la texture du silence derrière lui.**

Une marque par séance attendue :

- **séance cotée** — carré plein, encre ;
- **cours reporté** — anneau creux, laiton ;
- **séance absente** — point pâle, gris.

Sur une place liquide, cette trame serait une barre pleine, donc muette. Ici c'est
le qualificatif le plus important de tout l'écran : un cours de 28 400 vu douze
fois sur vingt séances ne vaut pas le même cours vu deux fois sur vingt.

La trame apparaît dans cinq composants : la carte d'une ligne, l'en-tête de valeur,
la ligne du tableau des positions, le bloc de signal, la vignette de liquidité.

---

## Défauts rejetés

| Défaut du genre | Remplacé par |
|---|---|
| Palette navy + or | monde latérite / indigo / papier ci-dessus |
| Gros pourcentage vert-rouge en héros | montant en XOF ; le pourcentage **refuse de s'afficher** sur un cours reporté |
| Sparkline lissée dans chaque carte | trame de séances discrète, qui montre les trous au lieu de les lisser |
| Mode sombre par défaut | papier clair — un relevé est imprimé |
| Camembert de répartition | jauges avec la limite marquée (un ratio contre une limite) |

---

## Tokens

### Couleurs (oklch, contrastes vérifiés sur papier `#FBF9F6`)

```css
--encre:            oklch(0.205 0.035 265);  /* 17.05:1 */
--encre-secondaire: oklch(0.435 0.022 265);  /*  7.58:1 */
--encre-tertiaire:  oklch(0.555 0.016 265);  /*  4.53:1 */
--encre-muette:     oklch(0.655 0.012 265);  /*  3.01:1 — désactivé uniquement */

--papier:           oklch(0.983 0.0045 85);  /* fond d'application */
--papier-leve:      oklch(0.997 0.002 85);   /* cartes */
--papier-creux:     oklch(0.962 0.006 85);   /* champs, en-têtes de tableau */

--lagune:           oklch(0.505 0.095 172);  /*  5.30:1 — gain */
--laterite:         oklch(0.545 0.145 38);   /*  5.02:1 — perte */
--laiton:           oklch(0.555 0.115 82);   /*  4.58:1 — attention, en texte */
--laiton-marque:    oklch(0.660 0.125 82);   /*  3.01:1 — anneau de trame */
--indigo:           oklch(0.455 0.135 268);  /*  7.15:1 — accent interactif */
```

Aucune palette catégorielle n'est définie : **aucune vue n'en a besoin.** La forme
choisie pour chaque donnée (jauge, ligne unique, trame d'états) évite les séries
multiples, donc évite le problème.

### Profondeur — **bordures seules**

Un relevé est plat. Une seule stratégie, tenue partout : pas d'ombre portée sur les
cartes, pas de dégradé. La hiérarchie vient de la teinte de surface et du trait.

```css
--trait-discret:  oklch(0.205 0.035 265 / 0.06);
--trait:          oklch(0.205 0.035 265 / 0.11);
--trait-fort:     oklch(0.205 0.035 265 / 0.18);
--trait-focus:    var(--indigo);
```

### Espacement — base 4px

`4 · 8 · 12 · 16 · 24 · 32 · 48 · 64`. Cartes : 20px. Sections : 32px.

### Rayon — 3px

Presque droit. Un formulaire administratif n'a pas les coins ronds.

```css
--rayon: 3px;  --rayon-large: 5px;  --rayon-plein: 999px;
```

### Typographie

| Rôle | Famille | Raison |
|---|---|---|
| Titres | **Newsreader** (serif variable) | l'allure d'un bulletin imprimé — écarte le sans-serif de tous les tableaux de bord |
| Interface | **Instrument Sans** | fonctionnelle, légèrement étroite, bonne en libellés denses |
| Chiffres | **IBM Plex Mono**, `tabular-nums` | les colonnes de montants s'alignent au chiffre près |

Toutes auto-hébergées, sous-ensemble latin, 200 Ko au total. Aucun appel réseau à
l'exécution : l'interface fonctionne hors ligne.

Micro-libellés : 11px, majuscules, interlettrage `0.08em`, encre tertiaire.

---

## Décisions

- **2026-09-01** — Bordures seules plutôt qu'ombres : le produit est un relevé.
- **2026-09-01** — Serif pour les titres : écarte le défaut du genre et évoque
  l'imprimé officiel.
- **2026-09-01** — Pas de palette catégorielle : la forme retenue pour chaque
  donnée l'a rendue inutile. Vérifié avec le validateur du skill `dataviz`.
- **2026-09-01** — `encre-tertiaire`, `encre-muette` et `laiton` assombris après
  échec au contrôle de contraste. Les valeurs retenues sont les plus **claires**
  qui passent, pour ne pas éteindre la couleur.
- **2026-09-01** — Second assombrissement après mesure **sur le rendu réel**, en
  peignant les pixels plutôt qu'en lisant la chaîne CSS. Le premier calcul
  opposait chaque ton à `--papier` ; or les micro-libellés s'affichent aussi sur
  `--papier-creux` (en-têtes de tableau) et sur les surfaces teintées
  (`--laterite-voile` quand la donnée est périmée). Chaque ton est désormais
  vérifié contre **toutes** les surfaces où il se pose. Calculer contre le mauvais
  fond donne un contrôle qui passe et une page qui échoue.
- **2026-09-01** — Un `h1` invisible nomme la page : le titre visible vit dans le
  rail, et un document sans `h1` n'annonce pas ce qu'il est.
