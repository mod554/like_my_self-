# Terminal de veille agricole & analyse d'investissement

Plateforme web de type « mini-Bloomberg » pour la veille et l'analyse d'investissement sur trois filières agricoles et leurs dérivés : **Maïs**, **Noix de cajou (anacarde)** et **Noix de cola**.

> Interface en français · Devises : USD / EUR / XOF · Données mondiales et africaines

---

## Prérequis

- Node.js ≥ 18
- PostgreSQL ≥ 14
- npm ≥ 9

---

## Installation locale

### 1. Cloner et installer

```bash
git clone <url-du-repo>
cd like_my_self-
npm install
```

### 2. Variables d'environnement

```bash
cp .env.example .env
```

Éditer `.env` et renseigner `DATABASE_URL` avec vos coordonnées PostgreSQL :

```
DATABASE_URL="postgresql://user:password@localhost:5432/terminal_agri?schema=public"
NEXTAUTH_SECRET="une-chaine-aleatoire-longue"
NEXTAUTH_URL="http://localhost:3000"
```

### 3. Base de données — migration et seed

```bash
# Créer les tables
npm run db:migrate

# Peupler avec les données de référence + exemples ⚠️
npm run db:seed
```

> **⚠️ Données d'exemple :** les prix et coûts du seed sont des ordres de grandeur plausibles à titre de démonstration. Ils sont clairement marqués `fiabilite: EXEMPLE` en base. Ne pas les utiliser pour des décisions réelles.

### 4. Lancer l'application

```bash
npm run dev
```

L'interface est disponible sur [http://localhost:3000](http://localhost:3000).

**Compte admin par défaut :**
- Email : `admin@terminal-agri.local`
- Mot de passe : `admin123!` ← **à changer immédiatement en production**

---

## Scripts disponibles

| Commande | Description |
|----------|-------------|
| `npm run dev` | Serveur de développement Next.js |
| `npm run build` | Build de production |
| `npm start` | Démarrage en production |
| `npm test` | Tests unitaires (Vitest) |
| `npm run test:watch` | Tests en mode watch |
| `npm run db:migrate` | Appliquer les migrations Prisma |
| `npm run db:seed` | Peupler la base (filières, marchés, sources, exemples) |
| `npm run db:studio` | Interface Prisma Studio (BD visuelle) |
| `npm run db:reset` | Réinitialiser la BD (⚠️ destructif) |
| `npm run worker` | Démarrer le scheduler de connecteurs |
| `npm run worker:run` | Exécuter un connecteur immédiatement |

---

## Architecture

```
src/
├── app/                    # Next.js App Router (pages + API routes)
├── lib/
│   ├── connectors/         # Connecteurs de données (interface Connector)
│   │   ├── base.ts         # Interface commune
│   │   └── worldbank.ts    # World Bank Pink Sheet (maïs, public)
│   ├── finance.ts          # Moteur VAN / TRI / Payback / Point mort
│   ├── conversions.ts      # Conversions devises (EUR/XOF fixe) et unités
│   └── db.ts               # Client Prisma singleton
├── worker/
│   └── scheduler.ts        # Cron jobs connecteurs
tests/
├── finance.test.ts         # Tests calculs financiers
└── conversions.test.ts     # Tests conversions
prisma/
├── schema.prisma           # Schéma BD complet
└── seed.ts                 # Seed 3 filières
```

---

## Filières couvertes

| Filière | Statut marché | Nature des données |
|---------|--------------|-------------------|
| **Maïs** | Commodity cotée (CME/CBOT, ZC) | Futures + spot mondiaux, données abondantes |
| **Cajou** | Marché actif non coté | Prix indicatifs RCN/amandes, données partielles |
| **Cola** | Marché régional (Afrique de l'Ouest) | Prix marchés régionaux, pas de référence mondiale |

---

## Sources de données

| Source | Filière | Format | Accès | Statut |
|--------|---------|--------|-------|--------|
| World Bank Pink Sheet | Maïs | API JSON | Public, gratuit | Connecteur actif |
| FAO FPMA | Maïs, Cajou | API | Public, gratuit | Phase 3 |
| USDA WASDE | Maïs | CSV | Public, gratuit | Phase 3 |
| RESIMAO | Maïs, Cola | API/Web | Public | Phase 3 |
| Conseil Anacarde CI | Cajou | Manuel | Public | Manuel |
| CME Group (futures) | Maïs | API | **Payant (~1 500 USD/mois)** | Non actif |

---

## Phases de développement

- [x] **Phase 0** — Repo, schéma BD, seeds 3 filières, moteur financier, connecteurs
- [ ] **Phase 1** — Référentiel : CRUD filières/produits/fiches normalisées
- [ ] **Phase 2** — Prix & coûts : saisie, import CSV/Excel, historisation, séries
- [ ] **Phase 3** — Connecteurs : World Bank de bout en bout + traçabilité
- [ ] **Phase 4** — Terminal de marché : watchlists, graphes, heatmap, alertes
- [ ] **Phase 5** — Analyse investissement : moteur complet + tests
- [ ] **Phase 6** — Exports PDF/Excel, comparateur d'opportunités
- [ ] **Phase 7** — Rôles/permissions, doc utilisateur

---

## Principes de qualité des données

- Chaque donnée chiffrée porte **devise + unité + date + source + niveau de fiabilité**
- Niveaux : `OFFICIEL` · `INDICATIF` · `ESTIME` · `EXEMPLE`
- Aucune donnée n'est présentée comme officielle sans source vérifiable
- Pas de ticker fictif : la cola n'a pas de cours mondial (cf. PRD §2)
- Les données d'exemple du seed sont clairement signalées
