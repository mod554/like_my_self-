-- =============================================================================
--  Schéma de persistance — version 1
-- =============================================================================
--  Conventions :
--    * dates de séance et dates d'opération : TEXT au format AAAA-MM-JJ ;
--    * horodatages : TEXT ISO 8601 avec fuseau explicite, stockés en UTC ;
--    * montants et cours : INTEGER, en XOF, sans décimale ;
--    * taux et facteurs : TEXT, pour éviter toute perte en virgule flottante ;
--    * booléens : INTEGER 0/1.
--
--  Les séries brutes et ajustées ne sont pas deux tables : la table `cotations`
--  contient la série NON AJUSTÉE, seule donnée observée. La série ajustée est
--  recalculée à partir des opérations sur titres (voir brvm.domain.ajustement),
--  parce qu'un facteur figé devient faux dès qu'une opération est corrigée.
-- =============================================================================

CREATE TABLE IF NOT EXISTS version_schema (
    version      INTEGER NOT NULL PRIMARY KEY,
    applique_le  TEXT    NOT NULL
);

-- -----------------------------------------------------------------------------
--  Référentiel
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS instruments (
    ticker        TEXT    NOT NULL PRIMARY KEY,
    nom           TEXT    NOT NULL,
    isin          TEXT,
    pays          TEXT    NOT NULL,
    secteur       TEXT,
    compartiment  TEXT,
    devise        TEXT    NOT NULL DEFAULT 'XOF',
    actif         INTEGER NOT NULL DEFAULT 1,
    nombre_titres INTEGER,
    date_maj      TEXT
);

CREATE INDEX IF NOT EXISTS idx_instruments_secteur ON instruments (secteur);
CREATE INDEX IF NOT EXISTS idx_instruments_pays    ON instruments (pays);

-- -----------------------------------------------------------------------------
--  Cotations — série NON AJUSTÉE
-- -----------------------------------------------------------------------------
--  Clé d'idempotence : ticker + date de séance + source. Une même séance peut
--  donc être servie par plusieurs sources ; l'arbitrage se fait à la lecture, par
--  priorité de source, et non en écrasant une source par une autre.
--
--  Aucune clé étrangère vers `instruments` : une source peut publier un ticker
--  encore absent du référentiel. Le bloquer ferait perdre la donnée ; on l'écrit
--  et un contrôle d'intégrité signale les orphelins.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cotations (
    ticker                  TEXT    NOT NULL,
    date_seance             TEXT    NOT NULL,
    source                  TEXT    NOT NULL,
    statut_seance           TEXT    NOT NULL,
    ouverture               INTEGER,
    plus_haut               INTEGER,
    plus_bas                INTEGER,
    cloture                 INTEGER,
    cours_precedent         INTEGER,
    volume_titres           INTEGER NOT NULL DEFAULT 0,
    volume_xof              INTEGER,
    nb_transactions         INTEGER,
    meilleure_limite_achat  INTEGER,
    meilleure_limite_vente  INTEGER,
    horodatage_donnee       TEXT    NOT NULL,
    horodatage_collecte     TEXT    NOT NULL,
    statut_fiabilite        TEXT    NOT NULL,
    revision                INTEGER NOT NULL DEFAULT 1,
    commentaire             TEXT,
    empreinte               TEXT    NOT NULL,
    PRIMARY KEY (ticker, date_seance, source)
);

CREATE INDEX IF NOT EXISTS idx_cotations_date   ON cotations (date_seance);
CREATE INDEX IF NOT EXISTS idx_cotations_ticker ON cotations (ticker, date_seance);

-- -----------------------------------------------------------------------------
--  Historisation des corrections de cote
-- -----------------------------------------------------------------------------
--  Une correction ne remplace pas l'ancienne valeur : celle-ci est archivée ici
--  avant écrasement. C'est ce qui permet de rejouer une analyse telle qu'elle
--  était calculable à une date passée.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cotations_revisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                  TEXT    NOT NULL,
    date_seance             TEXT    NOT NULL,
    source                  TEXT    NOT NULL,
    revision                INTEGER NOT NULL,
    statut_seance           TEXT    NOT NULL,
    ouverture               INTEGER,
    plus_haut               INTEGER,
    plus_bas                INTEGER,
    cloture                 INTEGER,
    cours_precedent         INTEGER,
    volume_titres           INTEGER NOT NULL DEFAULT 0,
    volume_xof              INTEGER,
    nb_transactions         INTEGER,
    meilleure_limite_achat  INTEGER,
    meilleure_limite_vente  INTEGER,
    horodatage_donnee       TEXT    NOT NULL,
    horodatage_collecte     TEXT    NOT NULL,
    statut_fiabilite        TEXT    NOT NULL,
    commentaire             TEXT,
    empreinte               TEXT    NOT NULL,
    remplacee_le            TEXT    NOT NULL,
    motif                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_revisions_cle
    ON cotations_revisions (ticker, date_seance, source, revision);

-- -----------------------------------------------------------------------------
--  Opérations sur titres
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_sur_titres (
    identifiant             TEXT    NOT NULL PRIMARY KEY,
    ticker                  TEXT    NOT NULL,
    type_ost                TEXT    NOT NULL,
    date_ex                 TEXT    NOT NULL,
    date_paiement           TEXT,
    montant_brut_par_action INTEGER,
    ratio_numerateur        INTEGER,
    ratio_denominateur      INTEGER,
    source                  TEXT    NOT NULL,
    commentaire             TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ost_unicite
    ON operations_sur_titres (ticker, type_ost, date_ex, source);
CREATE INDEX IF NOT EXISTS idx_ost_ticker ON operations_sur_titres (ticker, date_ex);

-- -----------------------------------------------------------------------------
--  Portefeuille
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    identifiant     TEXT    NOT NULL PRIMARY KEY,
    ticker          TEXT    NOT NULL,
    date_operation  TEXT    NOT NULL,
    date_reglement  TEXT,
    sens            TEXT    NOT NULL,
    quantite        INTEGER NOT NULL,
    cours_unitaire  INTEGER NOT NULL,
    reference_sgi   TEXT,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_ticker
    ON transactions (ticker, date_operation);

-- Décompte de frais ligne à ligne : c'est la traçabilité de l'avis d'opéré.
CREATE TABLE IF NOT EXISTS frais_transaction (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT    NOT NULL REFERENCES transactions (identifiant) ON DELETE CASCADE,
    ordre          INTEGER NOT NULL,
    libelle        TEXT    NOT NULL,
    base_calcul    TEXT    NOT NULL,
    taux           TEXT,
    assiette       INTEGER NOT NULL,
    montant        INTEGER NOT NULL,
    UNIQUE (transaction_id, ordre)
);

CREATE TABLE IF NOT EXISTS flux_especes (
    identifiant     TEXT    NOT NULL PRIMARY KEY,
    date_flux       TEXT    NOT NULL,
    type_flux       TEXT    NOT NULL,
    ticker          TEXT,
    montant_brut    INTEGER NOT NULL,
    retenue_fiscale INTEGER NOT NULL DEFAULT 0,
    frais           INTEGER NOT NULL DEFAULT 0,
    source          TEXT    NOT NULL,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_flux_date ON flux_especes (date_flux);

-- -----------------------------------------------------------------------------
--  Qualité de donnée et exploitation
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies (
    identifiant   TEXT    NOT NULL PRIMARY KEY,
    source        TEXT    NOT NULL,
    type_anomalie TEXT    NOT NULL,
    gravite       TEXT    NOT NULL,
    message       TEXT    NOT NULL,
    ticker        TEXT,
    date_seance   TEXT,
    charge_utile  TEXT    NOT NULL DEFAULT '{}',
    detectee_le   TEXT    NOT NULL,
    resolue       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_anomalies_ouvertes ON anomalies (resolue, gravite);
CREATE INDEX IF NOT EXISTS idx_anomalies_cle      ON anomalies (ticker, date_seance);

CREATE TABLE IF NOT EXISTS journal_collectes (
    identifiant      TEXT    NOT NULL PRIMARY KEY,
    source           TEXT    NOT NULL,
    debut            TEXT    NOT NULL,
    fin              TEXT,
    statut           TEXT    NOT NULL,
    nb_lignes_lues   INTEGER NOT NULL DEFAULT 0,
    nb_lignes_ecrites INTEGER NOT NULL DEFAULT 0,
    nb_anomalies     INTEGER NOT NULL DEFAULT 0,
    message          TEXT
);

CREATE INDEX IF NOT EXISTS idx_collectes_source ON journal_collectes (source, debut);

-- Paramètres d'exécution : dernière collecte réussie, empreinte de configuration
-- appliquée, etc. Ce n'est pas un doublon du fichier de configuration.
CREATE TABLE IF NOT EXISTS parametres (
    cle    TEXT NOT NULL PRIMARY KEY,
    valeur TEXT NOT NULL,
    maj    TEXT NOT NULL
);
