"""Orchestration d'un cycle d'ingestion.

Enchaîne, source par source et dans l'ordre de priorité : collecte, contrôles
d'anomalies, marquage de fiabilité, écriture idempotente, journal de collecte.

Deux règles gouvernent le comportement d'ensemble :

* **une source qui tombe n'emporte pas les autres.** Chaque source est traitée
  indépendamment ; son échec devient une anomalie et une entrée de journal ;
* **rien n'est écarté en silence.** Une ligne illisible, une cotation suspecte ou
  mise en quarantaine laisse une trace nominative en base, avec la donnée brute
  qui l'a provoquée.

Les cotations en quarantaine **sont écrites** : elles restent consultables pour
investigation, mais la lecture par défaut des dépôts les exclut, de sorte
qu'aucun indicateur ne les rencontre.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from brvm.config.modeles import ConfigSource, Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import GraviteAnomalie, StatutCollecte, StatutFiabilite
from brvm.domain.modeles import Anomalie, Cotation, JournalCollecte
from brvm.ingestion.anomalies import (
    Constat,
    DetecteurAnomalies,
    TypeAnomalie,
    statut_depuis_constats,
)
from brvm.ingestion.base import DataSource, ResultatCollecte
from brvm.ingestion.fabrique import construire_sources_actives
from brvm.ingestion.univers import charger_univers
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import (
    DepotAnomalies,
    DepotCotations,
    DepotInstruments,
    DepotJournalCollectes,
    ResumeEcriture,
)
from brvm.utils.erreurs import ErreurBrvm, ErreurConfiguration
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("ingestion.orchestrateur")


@dataclass(slots=True)
class BilanIngestion:
    """Ce qu'a produit une source sur un cycle, tel qu'affiché à l'exploitant."""

    source: str
    statut: StatutCollecte
    lignes_lues: int = 0
    lignes_rejetees: int = 0
    inserees: int = 0
    inchangees: int = 0
    corrigees: int = 0
    en_quarantaine: int = 0
    suspectes: int = 0
    anomalies: int = 0
    origine: str | None = None
    depuis_cache: bool = False
    message: str | None = None
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ecrites(self) -> int:
        return self.inserees + self.inchangees + self.corrigees

    def resume(self) -> str:
        return (
            f"[{self.source}] {self.statut.value} — {self.lignes_lues} lue(s), "
            f"{self.inserees} insérée(s), {self.corrigees} corrigée(s), "
            f"{self.inchangees} inchangée(s), {self.lignes_rejetees} rejetée(s), "
            f"{self.en_quarantaine} en quarantaine, {self.suspectes} suspecte(s)"
        )


def _identifiant_anomalie(
    source: str, type_anomalie: str, ticker: str | None, jour: date | None, message: str
) -> str:
    """Identifiant déterministe : rejouer une collecte ne multiplie pas les anomalies."""
    graine = "|".join(
        [source, type_anomalie, ticker or "", jour.isoformat() if jour else "", message]
    )
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:32]


class Orchestrateur:
    """Exécute un cycle d'ingestion complet sur toutes les sources actives."""

    def __init__(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        sources: Sequence[DataSource] | None = None,
    ) -> None:
        self.configuration = configuration
        self.base = base
        self.calendrier = calendrier
        self.sources = (
            list(sources) if sources is not None else construire_sources_actives(configuration)
        )
        self.depot_cotations = DepotCotations(base)
        self.depot_anomalies = DepotAnomalies(base)
        self.depot_journal = DepotJournalCollectes(base)
        self.depot_instruments = DepotInstruments(base)

    # --------------------------------------------------------------------- API

    def synchroniser_univers(self) -> int:
        """Recopie le référentiel de valeurs déclaré dans la base.

        Une valeur retirée du fichier n'est pas supprimée de la base : des
        cotations et des transactions peuvent la référencer, et effacer son
        libellé rendrait un historique illisible. Marquez-la `actif: false`
        plutôt que de l'ôter.

        Returns:
            Le nombre de valeurs écrites, ou 0 si le fichier est absent — ce
            n'est pas une erreur : on peut collecter avant d'avoir saisi la cote.
        """
        try:
            instruments = charger_univers(self.configuration.marche.fichier_univers)
        except ErreurBrvm as exc:
            _journal.warning(
                "Référentiel des valeurs illisible : la base n'est pas mise à jour",
                extra={"detail": str(exc)},
            )
            return 0
        for instrument in instruments:
            self.depot_instruments.enregistrer(instrument)
        _journal.info("Référentiel synchronisé", extra={"valeurs": len(instruments)})
        return len(instruments)

    def executer(
        self, jour: date | None = None, maintenant: datetime | None = None
    ) -> list[BilanIngestion]:
        """Lance une collecte sur chaque source active et renvoie un bilan par source.

        Args:
            jour: séance visée. ``None`` demande la dernière disponible.
            maintenant: instant de référence des contrôles de fraîcheur. Par défaut
                l'heure courante. À renseigner pour rejouer une collecte historique,
                où l'ancienneté des données est attendue et ne doit pas déclencher
                d'anomalie de péremption.
        """
        # Le référentiel est une donnée de CONFIGURATION : la base en est le
        # reflet, jamais la source. On le remet en phase à chaque cycle, sinon
        # il reste vide et tout ce qui en dépend s'éteint en silence — le
        # criblage ne voit aucun univers, la détection de ticker inconnu ne se
        # déclenche jamais, les concentrations sectorielles n'ont pas de secteur.
        self.synchroniser_univers()

        detecteur = DetecteurAnomalies(
            self.configuration,
            self.calendrier,
            tickers_connus={instrument.ticker for instrument in self.depot_instruments.lister()}
            or None,
        )
        reglages = {source.nom: source for source in self.configuration.sources}
        bilans: list[BilanIngestion] = []
        for source in self.sources:
            reglage = reglages.get(source.nom)
            if reglage is None:
                # Les seuils de contrôle (fraîcheur, tolérances) sont propres à
                # chaque source : sans son bloc de configuration, on ne saurait
                # pas selon quels critères juger ce qu'elle rapporte.
                raise ErreurConfiguration(
                    f"Le connecteur {source.nom!r} ne correspond à aucune source "
                    "déclarée en configuration. Ajoutez son bloc `sources[]`, ou "
                    "corrigez son nom : les seuils de contrôle en dépendent.",
                    source=source.nom,
                    connues=", ".join(sorted(reglages)),
                )
            bilans.append(self._traiter(source, reglage, detecteur, jour, maintenant))
        return bilans

    # ------------------------------------------------------------------ interne

    def _traiter(
        self,
        source: DataSource,
        reglage: ConfigSource,
        detecteur: DetecteurAnomalies,
        jour: date | None,
        maintenant: datetime | None = None,
    ) -> BilanIngestion:
        debut = datetime.now().astimezone()

        if not source.disponible():
            return self._source_indisponible(source, debut)

        resultat = source.collecter(jour)
        bilan = BilanIngestion(
            source=source.nom,
            statut=resultat.statut,
            lignes_lues=len(resultat.lignes),
            origine=resultat.origine,
            depuis_cache=resultat.depuis_cache,
            message=resultat.message,
            avertissements=resultat.avertissements,
        )

        # 1. Lignes que le connecteur n'a pas su transformer en cotation.
        for ligne in resultat.lignes_en_erreur:
            bilan.lignes_rejetees += 1
            self._consigner(
                Constat(
                    TypeAnomalie.LIGNE_ILLISIBLE,
                    GraviteAnomalie.BLOQUANTE,
                    ligne.erreur or "Ligne illisible.",
                    charge_utile=ligne.brut,
                ),
                source.nom,
            )
            bilan.anomalies += 1

        # 2. Contrôles sur les cotations exploitables. La donnée brute reste
        # appariée à sa cotation : une anomalie doit pouvoir citer ce qui l'a causée.
        exploitables = [
            (ligne.brut, ligne.cotation)
            for ligne in resultat.lignes_exploitables
            if ligne.cotation is not None
        ]
        constats_lot = detecteur.examiner_lot([cotation for _, cotation in exploitables])
        marquees: list[Cotation] = []

        for position, (brut, cotation) in enumerate(exploitables):
            constats = detecteur.examiner(cotation, reglage, brut, maintenant) + constats_lot.get(
                position, []
            )
            for constat in constats:
                self._consigner(constat, source.nom)
            bilan.anomalies += len(constats)

            statut = statut_depuis_constats(constats)
            if statut is StatutFiabilite.QUARANTAINE:
                bilan.en_quarantaine += 1
            elif statut is StatutFiabilite.SUSPECTE:
                bilan.suspectes += 1
            marquees.append(cotation.model_copy(update={"statut_fiabilite": statut}))

        # 3. Écriture idempotente, puis journal.
        if marquees:
            resume = self.depot_cotations.enregistrer_lot(
                marquees, motif=f"collecte {source.nom} du {debut.date().isoformat()}"
            )
            self._reporter(bilan, resume)

        self._journaliser(bilan, resultat, debut)
        _journal.info(
            "Cycle d'ingestion terminé",
            extra={
                "source": bilan.source,
                "statut": bilan.statut.value,
                "lues": bilan.lignes_lues,
                "ecrites": bilan.ecrites,
                "quarantaine": bilan.en_quarantaine,
            },
        )
        return bilan

    def _source_indisponible(self, source: DataSource, debut: datetime) -> BilanIngestion:
        message = (
            f"Source {source.nom} indisponible : ni fichier lisible, ni collecte autorisée. "
            "Le cycle continue sur les autres sources."
        )
        self._consigner(
            Constat(
                TypeAnomalie.LIGNE_ILLISIBLE,
                GraviteAnomalie.AVERTISSEMENT,
                message,
                charge_utile={"source": source.nom},
            ),
            source.nom,
            type_force="source_indisponible",
        )
        bilan = BilanIngestion(
            source=source.nom, statut=StatutCollecte.ECHEC, message=message, anomalies=1
        )
        self.depot_journal.enregistrer(
            JournalCollecte(
                identifiant=str(uuid.uuid4()),
                source=source.nom,
                debut=debut,
                fin=datetime.now().astimezone(),
                statut=StatutCollecte.ECHEC,
                message=message,
            )
        )
        _journal.warning("Source indisponible", extra={"source": source.nom})
        return bilan

    def _consigner(self, constat: Constat, source: str, type_force: str | None = None) -> None:
        type_anomalie = type_force or constat.type_anomalie.value
        self.depot_anomalies.enregistrer(
            Anomalie(
                identifiant=_identifiant_anomalie(
                    source, type_anomalie, constat.ticker, constat.date_seance, constat.message
                ),
                source=source,
                type_anomalie=type_anomalie,
                gravite=constat.gravite,
                message=constat.message,
                ticker=constat.ticker,
                date_seance=constat.date_seance,
                charge_utile=_serialisable(constat.charge_utile),
                detectee_le=datetime.now().astimezone(),
            )
        )

    @staticmethod
    def _reporter(bilan: BilanIngestion, resume: ResumeEcriture) -> None:
        bilan.inserees = resume.inserees
        bilan.inchangees = resume.inchangees
        bilan.corrigees = resume.corrigees

    def _journaliser(
        self, bilan: BilanIngestion, resultat: ResultatCollecte, debut: datetime
    ) -> None:
        self.depot_journal.enregistrer(
            JournalCollecte(
                identifiant=str(uuid.uuid4()),
                source=bilan.source,
                debut=debut,
                fin=datetime.now().astimezone(),
                statut=bilan.statut,
                nb_lignes_lues=bilan.lignes_lues,
                nb_lignes_ecrites=bilan.ecrites,
                nb_anomalies=bilan.anomalies,
                message=resultat.message,
            )
        )


def _serialisable(charge: dict[str, Any]) -> dict[str, Any]:
    """Rend la charge utile stockable en JSON sans perdre d'information."""
    return {
        cle: valeur if isinstance(valeur, (str, int, float, bool, type(None))) else str(valeur)
        for cle, valeur in charge.items()
    }
