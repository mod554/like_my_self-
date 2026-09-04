"""Criblage : lire toute la cote, l'analyser, la classer.

C'est le point d'entrée de la couche. Il fait pour l'univers entier ce que
:mod:`brvm.app.etat` fait pour les seules lignes détenues — et la distinction
compte : le portefeuille se lit sur ce que vous possédez, le criblage sur ce qui
existe.

Une valeur dont la série est trop courte, trop trouée, ou absente de la base
n'est pas silencieusement omise : elle ressort avec la raison. Sur cette place,
les valeurs écartées sont souvent la majorité, et savoir laquelle manque de
données vaut mieux que de la voir disparaître d'un tableau.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.modeles import Cotation, Instrument
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import construire_serie
from brvm.market.analyse import AnalyseValeur, analyser
from brvm.market.fondamentaux import Fondamentaux, charger_fondamentaux
from brvm.market.horizons import Classement, classer_tous, resume_couverture
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotInstruments, DepotOperationsSurTitres
from brvm.utils.erreurs import ErreurValidation
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("market.criblage")

#: Profondeur d'historique relue par valeur, en séances.
PROFONDEUR_SEANCES: int = 400


@dataclass(frozen=True, slots=True)
class ValeurEcartee:
    """Une valeur de l'univers que le criblage n'a pas pu analyser."""

    ticker: str
    motif: str


@dataclass(frozen=True, slots=True)
class Criblage:
    """L'état de la cote entière à un instant donné."""

    instant: datetime
    jusqu_a: date
    analyses: tuple[AnalyseValeur, ...] = ()
    classements: Mapping[str, Classement] = field(default_factory=dict)
    ecartees: tuple[ValeurEcartee, ...] = ()
    #: Horodatage de la donnée la plus ancienne employée, comme partout ailleurs.
    horodatage_le_plus_ancien: datetime | None = None
    fondamentaux_renseignes: int = 0
    avertissements: tuple[str, ...] = ()

    @property
    def univers(self) -> int:
        return len(self.analyses) + len(self.ecartees)

    def age_minutes(self) -> Decimal | None:
        if self.horodatage_le_plus_ancien is None:
            return None
        secondes = (self.instant - self.horodatage_le_plus_ancien).total_seconds()
        return Decimal(str(secondes)) / Decimal(60)

    def entete_fraicheur(self) -> str:
        if self.horodatage_le_plus_ancien is None:
            return "Aucune cotation en base : la cote n'est pas analysable."
        age = self.age_minutes()
        return (
            f"Donnée la plus ancienne employée : "
            f"{self.horodatage_le_plus_ancien.isoformat()}"
            + (f" ({age:.0f} minutes)" if age is not None else "")
        )

    def couverture_criteres(self) -> Mapping[str, int]:
        return resume_couverture(self.analyses)


def cribler(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    instant: datetime | None = None,
    jusqu_a: date | None = None,
    tickers: Sequence[str] | None = None,
) -> Criblage:
    """Analyse et classe toute la cote présente en base.

    Args:
        tickers: restreint le criblage. Par défaut, tout l'univers du référentiel.
        jusqu_a: borne de connaissance. Rien de postérieur n'est lu, ce qui rend
            un criblage rejouable à une date passée sans qu'aucun calcul ne
            consulte une séance qui n'existait pas encore.
    """
    maintenant = instant or datetime.now(UTC)
    borne = jusqu_a or maintenant.date()

    instruments = {
        instrument.ticker: instrument
        for instrument in DepotInstruments(base).lister(actifs_seulement=True)
    }
    vises = list(tickers) if tickers is not None else sorted(instruments)
    if not vises:
        return Criblage(
            instant=maintenant,
            jusqu_a=borne,
            avertissements=(
                "Le référentiel des valeurs est vide en base. Renseignez "
                "`marche.fichier_univers`, puis lancez `collecter` : le cycle "
                "d'ingestion y recopie l'univers déclaré. Le criblage lit la "
                "base, il ne lit pas le fichier directement.",
            ),
        )

    referentiel = charger_fondamentaux(configuration.analyse.fichier_fondamentaux)
    operations = DepotOperationsSurTitres(base).lister()
    depot = DepotCotations(base)

    analyses: list[AnalyseValeur] = []
    ecartees: list[ValeurEcartee] = []
    horodatages: list[datetime] = []
    avertissements: list[str] = []

    for ticker in vises:
        cotations = [
            cotation for cotation in depot.lire(ticker, fin=borne) if cotation.date_seance <= borne
        ]
        if not cotations:
            ecartees.append(ValeurEcartee(ticker, "aucune cotation en base pour cette valeur"))
            continue

        analyse = _analyser_valeur(
            ticker=ticker,
            cotations=cotations[-PROFONDEUR_SEANCES:],
            operations=operations,
            configuration=configuration,
            calendrier=calendrier,
            borne=borne,
            instrument=instruments.get(ticker),
            exercices=referentiel.get(ticker, []),
        )
        if isinstance(analyse, ValeurEcartee):
            ecartees.append(analyse)
            continue

        analyses.append(analyse)
        derniere = max(cotations, key=lambda c: (c.date_seance, c.horodatage_donnee))
        horodatages.append(derniere.horodatage_donnee)

    classements = classer_tous(analyses, configuration)

    renseignes = sum(1 for analyse in analyses if analyse.exercice is not None)
    if analyses and renseignes == 0:
        avertissements.append(
            "Aucune donnée fondamentale saisie sur l'ensemble de la cote. Tout "
            "classement de long terme s'abstiendra : renseignez "
            f"{configuration.analyse.fichier_fondamentaux} depuis les rapports annuels."
        )
    elif analyses and renseignes < len(analyses):
        avertissements.append(
            f"Fondamentaux saisis pour {renseignes} valeur(s) sur {len(analyses)} "
            "analysées. Les autres n'entreront dans aucun classement fondamental."
        )
    if ecartees:
        avertissements.append(
            f"{len(ecartees)} valeur(s) de l'univers n'ont pas pu être analysées. "
            "Le détail figure dans « valeurs écartées »."
        )

    _journal.info(
        "Criblage terminé",
        extra={
            "univers": len(vises),
            "analysees": len(analyses),
            "ecartees": len(ecartees),
            "fondamentaux": renseignes,
        },
    )

    return Criblage(
        instant=maintenant,
        jusqu_a=borne,
        analyses=tuple(analyses),
        classements=classements,
        ecartees=tuple(ecartees),
        horodatage_le_plus_ancien=min(horodatages) if horodatages else None,
        fondamentaux_renseignes=renseignes,
        avertissements=tuple(avertissements),
    )


def _analyser_valeur(
    ticker: str,
    cotations: Sequence[Cotation],
    operations: Sequence[object],
    configuration: Configuration,
    calendrier: CalendrierSeances,
    borne: date,
    instrument: Instrument | None,
    exercices: Sequence[Fondamentaux],
) -> AnalyseValeur | ValeurEcartee:
    try:
        serie = construire_serie(
            cotations,
            calendrier,
            configuration,
            operations=operations,  # type: ignore[arg-type]
            jusqu_a=borne,
        )
    except ErreurValidation as exc:
        return ValeurEcartee(ticker, f"série inexploitable — {exc}")

    indicateurs = Indicateurs(serie, configuration)
    return analyser(
        ticker=ticker,
        serie=serie,
        indicateurs=indicateurs,
        configuration=configuration,
        instrument=instrument,
        exercices=exercices,
        annee_courante=borne.year,
    )
