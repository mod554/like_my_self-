"""Dépôts : lecture et écriture des entités du domaine.

Deux principes gouvernent ce module.

**Idempotence.** Rejouer une collecte ne doit rien changer. La clé
``ticker + date de séance + source`` identifie un enregistrement ; une seconde
écriture au contenu identique ne crée ni doublon, ni révision.

**Traçabilité des corrections.** Lorsque le contenu de marché change pour une clé
déjà connue — la source a corrigé un cours —, l'ancienne version est archivée
dans ``cotations_revisions`` avant écrasement, et le numéro de révision est
incrémenté. Aucune valeur observée n'est perdue.

Les données relues repassent par les modèles pydantic : la validation joue dans
les deux sens, pas seulement à l'entrée.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from brvm.domain.enums import (
    BaseFrais,
    GraviteAnomalie,
    SensOperation,
    StatutCollecte,
    StatutFiabilite,
    StatutSeance,
    TypeFluxEspece,
    TypeOst,
)
from brvm.domain.modeles import (
    Anomalie,
    Cotation,
    FluxEspece,
    Instrument,
    JournalCollecte,
    LigneFrais,
    OperationSurTitre,
    Transaction,
)
from brvm.storage.base import BaseDonnees
from brvm.utils.erreurs import ErreurStockage


class EtatEcriture(StrEnum):
    """Issue de l'écriture d'une cotation."""

    #: Clé inconnue jusqu'ici.
    INSEREE = "INSEREE"
    #: Clé connue, contenu de marché identique : seules les métadonnées de
    #: collecte sont rafraîchies.
    INCHANGEE = "INCHANGEE"
    #: Clé connue, contenu de marché différent : l'ancienne version est archivée.
    CORRIGEE = "CORRIGEE"


@dataclass(frozen=True, slots=True)
class ResultatEcriture:
    etat: EtatEcriture
    revision: int


@dataclass(slots=True)
class ResumeEcriture:
    """Bilan d'une écriture par lot, à consigner dans le journal de collecte."""

    inserees: int = 0
    inchangees: int = 0
    corrigees: int = 0
    cles_corrigees: list[tuple[str, date, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.inserees + self.inchangees + self.corrigees

    def enregistrer(self, cle: tuple[str, date, str], resultat: ResultatEcriture) -> None:
        match resultat.etat:
            case EtatEcriture.INSEREE:
                self.inserees += 1
            case EtatEcriture.INCHANGEE:
                self.inchangees += 1
            case EtatEcriture.CORRIGEE:
                self.corrigees += 1
                self.cles_corrigees.append(cle)


# ------------------------------------------------------------------- conversions


def _jour(valeur: str | None) -> date | None:
    return None if valeur is None else date.fromisoformat(valeur)


def _horodatage(valeur: str) -> datetime:
    horodatage = datetime.fromisoformat(valeur)
    if horodatage.tzinfo is None:
        raise ErreurStockage(
            "Horodatage stocké sans fuseau : base corrompue ou écrite hors du système.",
            valeur=valeur,
        )
    return horodatage


def _texte(valeur: Decimal | None) -> str | None:
    return None if valeur is None else str(valeur)


def _decimal(valeur: str | None) -> Decimal | None:
    return None if valeur is None else Decimal(valeur)


class _Depot:
    """Base commune : détient la connexion."""

    def __init__(self, base: BaseDonnees) -> None:
        self.base = base

    @property
    def connexion(self) -> sqlite3.Connection:
        return self.base.connexion


# ------------------------------------------------------------------- instruments


class DepotInstruments(_Depot):
    def enregistrer(self, instrument: Instrument) -> None:
        self.connexion.execute(
            """
            INSERT INTO instruments
                (ticker, nom, isin, pays, secteur, compartiment, devise, actif,
                 nombre_titres, date_maj)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
                nom = excluded.nom,
                isin = excluded.isin,
                pays = excluded.pays,
                secteur = excluded.secteur,
                compartiment = excluded.compartiment,
                devise = excluded.devise,
                actif = excluded.actif,
                nombre_titres = excluded.nombre_titres,
                date_maj = excluded.date_maj
            """,
            (
                instrument.ticker,
                instrument.nom,
                instrument.isin,
                instrument.pays.value,
                instrument.secteur,
                instrument.compartiment,
                instrument.devise.value,
                int(instrument.actif),
                instrument.nombre_titres,
                instrument.date_maj.isoformat() if instrument.date_maj else None,
            ),
        )

    def enregistrer_lot(self, instruments: Iterable[Instrument]) -> int:
        compteur = 0
        with self.base.transaction():
            for instrument in instruments:
                self.enregistrer(instrument)
                compteur += 1
        return compteur

    def obtenir(self, ticker: str) -> Instrument | None:
        ligne = self.connexion.execute(
            "SELECT * FROM instruments WHERE ticker = ?", (ticker,)
        ).fetchone()
        return None if ligne is None else self._depuis_ligne(ligne)

    def lister(self, actifs_seulement: bool = False) -> list[Instrument]:
        requete = "SELECT * FROM instruments"
        if actifs_seulement:
            requete += " WHERE actif = 1"
        requete += " ORDER BY ticker"
        return [self._depuis_ligne(ligne) for ligne in self.connexion.execute(requete)]

    @staticmethod
    def _depuis_ligne(ligne: sqlite3.Row) -> Instrument:
        return Instrument(
            ticker=ligne["ticker"],
            nom=ligne["nom"],
            isin=ligne["isin"],
            pays=ligne["pays"],
            secteur=ligne["secteur"],
            compartiment=ligne["compartiment"],
            devise=ligne["devise"],
            actif=bool(ligne["actif"]),
            nombre_titres=ligne["nombre_titres"],
            date_maj=_horodatage(ligne["date_maj"]) if ligne["date_maj"] else None,
        )


# --------------------------------------------------------------------- cotations


class DepotCotations(_Depot):
    """Écriture idempotente et historisation des corrections de cote."""

    def enregistrer(self, cotation: Cotation, motif: str | None = None) -> ResultatEcriture:
        connexion = self.connexion
        ticker, jour, source = cotation.cle
        empreinte = cotation.empreinte()

        with self.base.transaction():
            existante = connexion.execute(
                """
                SELECT * FROM cotations
                 WHERE ticker = ? AND date_seance = ? AND source = ?
                """,
                (ticker, jour.isoformat(), source),
            ).fetchone()

            if existante is None:
                connexion.execute(
                    """
                    INSERT INTO cotations
                        (ticker, date_seance, source, statut_seance, ouverture, plus_haut,
                         plus_bas, cloture, cours_precedent, volume_titres, volume_xof,
                         nb_transactions, meilleure_limite_achat, meilleure_limite_vente,
                         horodatage_donnee, horodatage_collecte, statut_fiabilite, revision,
                         commentaire, empreinte)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticker,
                        jour.isoformat(),
                        source,
                        cotation.statut_seance.value,
                        cotation.ouverture,
                        cotation.plus_haut,
                        cotation.plus_bas,
                        cotation.cloture,
                        cotation.cours_precedent,
                        cotation.volume_titres,
                        cotation.volume_xof,
                        cotation.nb_transactions,
                        cotation.meilleure_limite_achat,
                        cotation.meilleure_limite_vente,
                        cotation.horodatage_donnee.isoformat(),
                        cotation.horodatage_collecte.isoformat(),
                        cotation.statut_fiabilite.value,
                        1,
                        cotation.commentaire,
                        empreinte,
                    ),
                )
                return ResultatEcriture(EtatEcriture.INSEREE, 1)

            revision_actuelle = int(existante["revision"])

            if existante["empreinte"] == empreinte:
                # Même donnée de marché. On ne crée pas de révision : on retient
                # seulement l'horodatage le plus récent, qui atteste que la donnée a
                # été reconfirmée à la source, et le statut de fiabilité courant.
                donnee = max(
                    _horodatage(existante["horodatage_donnee"]), cotation.horodatage_donnee
                )
                collecte = max(
                    _horodatage(existante["horodatage_collecte"]),
                    cotation.horodatage_collecte,
                )
                connexion.execute(
                    """
                    UPDATE cotations
                       SET horodatage_donnee = ?, horodatage_collecte = ?, statut_fiabilite = ?
                     WHERE ticker = ? AND date_seance = ? AND source = ?
                    """,
                    (
                        donnee.isoformat(),
                        collecte.isoformat(),
                        cotation.statut_fiabilite.value,
                        ticker,
                        jour.isoformat(),
                        source,
                    ),
                )
                return ResultatEcriture(EtatEcriture.INCHANGEE, revision_actuelle)

            # Contenu de marché différent : la source a corrigé sa cote.
            self._archiver(existante, motif=motif)
            nouvelle_revision = revision_actuelle + 1
            connexion.execute(
                """
                UPDATE cotations
                   SET statut_seance = ?, ouverture = ?, plus_haut = ?, plus_bas = ?,
                       cloture = ?, cours_precedent = ?, volume_titres = ?, volume_xof = ?,
                       nb_transactions = ?, meilleure_limite_achat = ?,
                       meilleure_limite_vente = ?, horodatage_donnee = ?,
                       horodatage_collecte = ?, statut_fiabilite = ?, revision = ?,
                       commentaire = ?, empreinte = ?
                 WHERE ticker = ? AND date_seance = ? AND source = ?
                """,
                (
                    cotation.statut_seance.value,
                    cotation.ouverture,
                    cotation.plus_haut,
                    cotation.plus_bas,
                    cotation.cloture,
                    cotation.cours_precedent,
                    cotation.volume_titres,
                    cotation.volume_xof,
                    cotation.nb_transactions,
                    cotation.meilleure_limite_achat,
                    cotation.meilleure_limite_vente,
                    cotation.horodatage_donnee.isoformat(),
                    cotation.horodatage_collecte.isoformat(),
                    cotation.statut_fiabilite.value,
                    nouvelle_revision,
                    cotation.commentaire,
                    empreinte,
                    ticker,
                    jour.isoformat(),
                    source,
                ),
            )
            return ResultatEcriture(EtatEcriture.CORRIGEE, nouvelle_revision)

    def _archiver(self, ligne: sqlite3.Row, motif: str | None) -> None:
        self.connexion.execute(
            """
            INSERT INTO cotations_revisions
                (ticker, date_seance, source, revision, statut_seance, ouverture, plus_haut,
                 plus_bas, cloture, cours_precedent, volume_titres, volume_xof,
                 nb_transactions, meilleure_limite_achat, meilleure_limite_vente,
                 horodatage_donnee, horodatage_collecte, statut_fiabilite, commentaire,
                 empreinte, remplacee_le, motif)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ligne["ticker"],
                ligne["date_seance"],
                ligne["source"],
                ligne["revision"],
                ligne["statut_seance"],
                ligne["ouverture"],
                ligne["plus_haut"],
                ligne["plus_bas"],
                ligne["cloture"],
                ligne["cours_precedent"],
                ligne["volume_titres"],
                ligne["volume_xof"],
                ligne["nb_transactions"],
                ligne["meilleure_limite_achat"],
                ligne["meilleure_limite_vente"],
                ligne["horodatage_donnee"],
                ligne["horodatage_collecte"],
                ligne["statut_fiabilite"],
                ligne["commentaire"],
                ligne["empreinte"],
                datetime.now().astimezone().isoformat(),
                motif,
            ),
        )

    def enregistrer_lot(
        self, cotations: Iterable[Cotation], motif: str | None = None
    ) -> ResumeEcriture:
        resume = ResumeEcriture()
        with self.base.transaction():
            for cotation in cotations:
                resume.enregistrer(cotation.cle, self.enregistrer(cotation, motif=motif))
        return resume

    def lire(
        self,
        ticker: str,
        debut: date | None = None,
        fin: date | None = None,
        source: str | None = None,
        inclure_quarantaine: bool = False,
    ) -> list[Cotation]:
        """Relit une série, par défaut sans les enregistrements en quarantaine."""
        conditions = ["ticker = ?"]
        parametres: list[Any] = [ticker]
        if debut is not None:
            conditions.append("date_seance >= ?")
            parametres.append(debut.isoformat())
        if fin is not None:
            conditions.append("date_seance <= ?")
            parametres.append(fin.isoformat())
        if source is not None:
            conditions.append("source = ?")
            parametres.append(source)
        if not inclure_quarantaine:
            conditions.append("statut_fiabilite <> ?")
            parametres.append(StatutFiabilite.QUARANTAINE.value)
        requete = (
            "SELECT * FROM cotations WHERE "
            + " AND ".join(conditions)
            + " ORDER BY date_seance, source"
        )
        return [self._depuis_ligne(ligne) for ligne in self.connexion.execute(requete, parametres)]

    def revisions(self, ticker: str, jour: date, source: str) -> list[dict[str, Any]]:
        """Historique des versions antérieures d'une cote, de la plus ancienne à la plus récente."""
        lignes = self.connexion.execute(
            """
            SELECT * FROM cotations_revisions
             WHERE ticker = ? AND date_seance = ? AND source = ?
             ORDER BY revision
            """,
            (ticker, jour.isoformat(), source),
        )
        return [dict(ligne) for ligne in lignes]

    def horodatage_le_plus_ancien(self, tickers: Sequence[str] | None = None) -> datetime | None:
        """Donnée la plus ancienne parmi celles retenues : sert d'indicateur de fraîcheur.

        Chaque écran doit pouvoir afficher l'âge de la donnée la plus périmée qu'il
        utilise ; c'est cette valeur.
        """
        requete = "SELECT MIN(horodatage_donnee) AS h FROM cotations WHERE statut_fiabilite <> ?"
        parametres: list[Any] = [StatutFiabilite.QUARANTAINE.value]
        if tickers:
            marques = ",".join("?" for _ in tickers)
            requete += f" AND ticker IN ({marques})"
            parametres.extend(tickers)
        ligne = self.connexion.execute(requete, parametres).fetchone()
        return None if ligne["h"] is None else _horodatage(ligne["h"])

    def tickers_orphelins(self) -> list[str]:
        """Tickers cotés absents du référentiel : signalés, jamais créés d'office."""
        lignes = self.connexion.execute(
            """
            SELECT DISTINCT c.ticker
              FROM cotations c
         LEFT JOIN instruments i ON i.ticker = c.ticker
             WHERE i.ticker IS NULL
             ORDER BY c.ticker
            """
        )
        return [ligne["ticker"] for ligne in lignes]

    @staticmethod
    def _depuis_ligne(ligne: sqlite3.Row) -> Cotation:
        return Cotation(
            ticker=ligne["ticker"],
            date_seance=date.fromisoformat(ligne["date_seance"]),
            source=ligne["source"],
            statut_seance=StatutSeance(ligne["statut_seance"]),
            ouverture=ligne["ouverture"],
            plus_haut=ligne["plus_haut"],
            plus_bas=ligne["plus_bas"],
            cloture=ligne["cloture"],
            cours_precedent=ligne["cours_precedent"],
            volume_titres=ligne["volume_titres"],
            volume_xof=ligne["volume_xof"],
            nb_transactions=ligne["nb_transactions"],
            meilleure_limite_achat=ligne["meilleure_limite_achat"],
            meilleure_limite_vente=ligne["meilleure_limite_vente"],
            horodatage_donnee=_horodatage(ligne["horodatage_donnee"]),
            horodatage_collecte=_horodatage(ligne["horodatage_collecte"]),
            statut_fiabilite=StatutFiabilite(ligne["statut_fiabilite"]),
            revision=ligne["revision"],
            commentaire=ligne["commentaire"],
        )


# ------------------------------------------------------------ opérations sur titres


class DepotOperationsSurTitres(_Depot):
    def enregistrer(self, operation: OperationSurTitre) -> None:
        self.connexion.execute(
            """
            INSERT INTO operations_sur_titres
                (identifiant, ticker, type_ost, date_ex, date_paiement,
                 montant_brut_par_action, ratio_numerateur, ratio_denominateur, source,
                 commentaire)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (identifiant) DO UPDATE SET
                ticker = excluded.ticker,
                type_ost = excluded.type_ost,
                date_ex = excluded.date_ex,
                date_paiement = excluded.date_paiement,
                montant_brut_par_action = excluded.montant_brut_par_action,
                ratio_numerateur = excluded.ratio_numerateur,
                ratio_denominateur = excluded.ratio_denominateur,
                source = excluded.source,
                commentaire = excluded.commentaire
            """,
            (
                operation.identifiant,
                operation.ticker,
                operation.type_ost.value,
                operation.date_ex.isoformat(),
                operation.date_paiement.isoformat() if operation.date_paiement else None,
                operation.montant_brut_par_action,
                operation.ratio_numerateur,
                operation.ratio_denominateur,
                operation.source,
                operation.commentaire,
            ),
        )

    def lister(
        self, ticker: str | None = None, jusqu_a: date | None = None
    ) -> list[OperationSurTitre]:
        conditions: list[str] = []
        parametres: list[Any] = []
        if ticker is not None:
            conditions.append("ticker = ?")
            parametres.append(ticker)
        if jusqu_a is not None:
            conditions.append("date_ex <= ?")
            parametres.append(jusqu_a.isoformat())
        requete = "SELECT * FROM operations_sur_titres"
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)
        requete += " ORDER BY date_ex, identifiant"
        return [
            OperationSurTitre(
                identifiant=ligne["identifiant"],
                ticker=ligne["ticker"],
                type_ost=TypeOst(ligne["type_ost"]),
                date_ex=date.fromisoformat(ligne["date_ex"]),
                date_paiement=_jour(ligne["date_paiement"]),
                montant_brut_par_action=ligne["montant_brut_par_action"],
                ratio_numerateur=ligne["ratio_numerateur"],
                ratio_denominateur=ligne["ratio_denominateur"],
                source=ligne["source"],
                commentaire=ligne["commentaire"],
            )
            for ligne in self.connexion.execute(requete, parametres)
        ]


# ------------------------------------------------------------------ portefeuille


class DepotTransactions(_Depot):
    def enregistrer(self, transaction: Transaction) -> None:
        with self.base.transaction() as connexion:
            connexion.execute(
                """
                INSERT INTO transactions
                    (identifiant, ticker, date_operation, date_reglement, sens, quantite,
                     cours_unitaire, reference_sgi, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (identifiant) DO UPDATE SET
                    ticker = excluded.ticker,
                    date_operation = excluded.date_operation,
                    date_reglement = excluded.date_reglement,
                    sens = excluded.sens,
                    quantite = excluded.quantite,
                    cours_unitaire = excluded.cours_unitaire,
                    reference_sgi = excluded.reference_sgi,
                    note = excluded.note
                """,
                (
                    transaction.identifiant,
                    transaction.ticker,
                    transaction.date_operation.isoformat(),
                    transaction.date_reglement.isoformat() if transaction.date_reglement else None,
                    transaction.sens.value,
                    transaction.quantite,
                    transaction.cours_unitaire,
                    transaction.reference_sgi,
                    transaction.note,
                ),
            )
            connexion.execute(
                "DELETE FROM frais_transaction WHERE transaction_id = ?",
                (transaction.identifiant,),
            )
            for ordre, ligne in enumerate(transaction.frais, start=1):
                connexion.execute(
                    """
                    INSERT INTO frais_transaction
                        (transaction_id, ordre, libelle, base_calcul, taux, assiette, montant)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction.identifiant,
                        ordre,
                        ligne.libelle,
                        ligne.base_calcul.value,
                        _texte(ligne.taux),
                        ligne.assiette,
                        ligne.montant,
                    ),
                )

    def lister(self, ticker: str | None = None) -> list[Transaction]:
        requete = "SELECT * FROM transactions"
        parametres: list[Any] = []
        if ticker is not None:
            requete += " WHERE ticker = ?"
            parametres.append(ticker)
        requete += " ORDER BY date_operation, identifiant"
        transactions: list[Transaction] = []
        for ligne in self.connexion.execute(requete, parametres).fetchall():
            frais = self.connexion.execute(
                "SELECT * FROM frais_transaction WHERE transaction_id = ? ORDER BY ordre",
                (ligne["identifiant"],),
            )
            transactions.append(
                Transaction(
                    identifiant=ligne["identifiant"],
                    ticker=ligne["ticker"],
                    date_operation=date.fromisoformat(ligne["date_operation"]),
                    date_reglement=_jour(ligne["date_reglement"]),
                    sens=SensOperation(ligne["sens"]),
                    quantite=ligne["quantite"],
                    cours_unitaire=ligne["cours_unitaire"],
                    frais=tuple(
                        LigneFrais(
                            libelle=frais_ligne["libelle"],
                            base_calcul=BaseFrais(frais_ligne["base_calcul"]),
                            taux=_decimal(frais_ligne["taux"]),
                            assiette=frais_ligne["assiette"],
                            montant=frais_ligne["montant"],
                        )
                        for frais_ligne in frais
                    ),
                    reference_sgi=ligne["reference_sgi"],
                    note=ligne["note"],
                )
            )
        return transactions


class DepotFluxEspeces(_Depot):
    def enregistrer(self, flux: FluxEspece) -> None:
        self.connexion.execute(
            """
            INSERT INTO flux_especes
                (identifiant, date_flux, type_flux, ticker, montant_brut, retenue_fiscale,
                 frais, source, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (identifiant) DO UPDATE SET
                date_flux = excluded.date_flux,
                type_flux = excluded.type_flux,
                ticker = excluded.ticker,
                montant_brut = excluded.montant_brut,
                retenue_fiscale = excluded.retenue_fiscale,
                frais = excluded.frais,
                source = excluded.source,
                note = excluded.note
            """,
            (
                flux.identifiant,
                flux.date_flux.isoformat(),
                flux.type_flux.value,
                flux.ticker,
                flux.montant_brut,
                flux.retenue_fiscale,
                flux.frais,
                flux.source,
                flux.note,
            ),
        )

    def lister(self, ticker: str | None = None) -> list[FluxEspece]:
        requete = "SELECT * FROM flux_especes"
        parametres: list[Any] = []
        if ticker is not None:
            requete += " WHERE ticker = ?"
            parametres.append(ticker)
        requete += " ORDER BY date_flux, identifiant"
        return [
            FluxEspece(
                identifiant=ligne["identifiant"],
                date_flux=date.fromisoformat(ligne["date_flux"]),
                type_flux=TypeFluxEspece(ligne["type_flux"]),
                ticker=ligne["ticker"],
                montant_brut=ligne["montant_brut"],
                retenue_fiscale=ligne["retenue_fiscale"],
                frais=ligne["frais"],
                source=ligne["source"],
                note=ligne["note"],
            )
            for ligne in self.connexion.execute(requete, parametres)
        ]


# --------------------------------------------------------- qualité et exploitation


class DepotAnomalies(_Depot):
    def enregistrer(self, anomalie: Anomalie) -> None:
        self.connexion.execute(
            """
            INSERT INTO anomalies
                (identifiant, source, type_anomalie, gravite, message, ticker, date_seance,
                 charge_utile, detectee_le, resolue)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (identifiant) DO UPDATE SET
                gravite = excluded.gravite,
                message = excluded.message,
                charge_utile = excluded.charge_utile,
                resolue = excluded.resolue
            """,
            (
                anomalie.identifiant,
                anomalie.source,
                anomalie.type_anomalie,
                anomalie.gravite.value,
                anomalie.message,
                anomalie.ticker,
                anomalie.date_seance.isoformat() if anomalie.date_seance else None,
                json.dumps(anomalie.charge_utile, ensure_ascii=False, default=str),
                anomalie.detectee_le.isoformat(),
                int(anomalie.resolue),
            ),
        )

    def lister(
        self, ouvertes_seulement: bool = True, gravite: GraviteAnomalie | None = None
    ) -> list[Anomalie]:
        conditions: list[str] = []
        parametres: list[Any] = []
        if ouvertes_seulement:
            conditions.append("resolue = 0")
        if gravite is not None:
            conditions.append("gravite = ?")
            parametres.append(gravite.value)
        requete = "SELECT * FROM anomalies"
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)
        requete += " ORDER BY detectee_le DESC"
        return [
            Anomalie(
                identifiant=ligne["identifiant"],
                source=ligne["source"],
                type_anomalie=ligne["type_anomalie"],
                gravite=GraviteAnomalie(ligne["gravite"]),
                message=ligne["message"],
                ticker=ligne["ticker"],
                date_seance=_jour(ligne["date_seance"]),
                charge_utile=json.loads(ligne["charge_utile"]),
                detectee_le=_horodatage(ligne["detectee_le"]),
                resolue=bool(ligne["resolue"]),
            )
            for ligne in self.connexion.execute(requete, parametres)
        ]

    def marquer_resolue(self, identifiant: str) -> None:
        self.connexion.execute(
            "UPDATE anomalies SET resolue = 1 WHERE identifiant = ?", (identifiant,)
        )


class DepotJournalCollectes(_Depot):
    def enregistrer(self, journal: JournalCollecte) -> None:
        self.connexion.execute(
            """
            INSERT INTO journal_collectes
                (identifiant, source, debut, fin, statut, nb_lignes_lues, nb_lignes_ecrites,
                 nb_anomalies, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (identifiant) DO UPDATE SET
                fin = excluded.fin,
                statut = excluded.statut,
                nb_lignes_lues = excluded.nb_lignes_lues,
                nb_lignes_ecrites = excluded.nb_lignes_ecrites,
                nb_anomalies = excluded.nb_anomalies,
                message = excluded.message
            """,
            (
                journal.identifiant,
                journal.source,
                journal.debut.isoformat(),
                journal.fin.isoformat() if journal.fin else None,
                journal.statut.value,
                journal.nb_lignes_lues,
                journal.nb_lignes_ecrites,
                journal.nb_anomalies,
                journal.message,
            ),
        )

    def derniere(self, source: str) -> JournalCollecte | None:
        ligne = self.connexion.execute(
            "SELECT * FROM journal_collectes WHERE source = ? ORDER BY debut DESC LIMIT 1",
            (source,),
        ).fetchone()
        if ligne is None:
            return None
        return JournalCollecte(
            identifiant=ligne["identifiant"],
            source=ligne["source"],
            debut=_horodatage(ligne["debut"]),
            fin=_horodatage(ligne["fin"]) if ligne["fin"] else None,
            statut=StatutCollecte(ligne["statut"]),
            nb_lignes_lues=ligne["nb_lignes_lues"],
            nb_lignes_ecrites=ligne["nb_lignes_ecrites"],
            nb_anomalies=ligne["nb_anomalies"],
            message=ligne["message"],
        )


class DepotParametres(_Depot):
    def definir(self, cle: str, valeur: str) -> None:
        self.connexion.execute(
            """
            INSERT INTO parametres (cle, valeur, maj) VALUES (?, ?, ?)
            ON CONFLICT (cle) DO UPDATE SET valeur = excluded.valeur, maj = excluded.maj
            """,
            (cle, valeur, datetime.now().astimezone().isoformat()),
        )

    def obtenir(self, cle: str, defaut: str | None = None) -> str | None:
        ligne = self.connexion.execute(
            "SELECT valeur FROM parametres WHERE cle = ?", (cle,)
        ).fetchone()
        return defaut if ligne is None else ligne["valeur"]
