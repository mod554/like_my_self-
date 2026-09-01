"""Fixtures partagées.

Toutes les données de test sont **fictives** et portent des tickers volontairement
improbables (``TEST1``, ``TEST2``…) : aucune valeur réelle de la cote n'apparaît
dans la suite de tests, pour qu'aucun chiffre du dépôt ne puisse être pris pour
une donnée de marché.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from brvm.config.chargement import charger_configuration, construire_calendrier_depuis_config
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import SensOperation, StatutSeance
from brvm.domain.modeles import Cotation, LigneFrais, OperationSurTitre, Transaction
from brvm.indicators.serie import SerieTechnique, construire_serie
from brvm.ingestion.univers import charger_univers
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import MoteurFrais
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotInstruments

DOSSIER_DONNEES = Path(__file__).parent / "donnees"

#: Horodatage de référence des fixtures : une clôture de séance fictive.
HORODATAGE = datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


@pytest.fixture
def dossier_config(tmp_path: Path) -> Path:
    """Copie les fichiers de configuration de test dans un dossier temporaire.

    Les tests n'écrivent jamais dans le dépôt.
    """
    cible = tmp_path / "config"
    shutil.copytree(DOSSIER_DONNEES, cible)
    return cible


@pytest.fixture
def configuration(dossier_config: Path) -> Configuration:
    return charger_configuration(dossier_config / "config_valide.yaml")


@pytest.fixture
def base(tmp_path: Path) -> Iterator[BaseDonnees]:
    with BaseDonnees(tmp_path / "test.sqlite3") as ouverte:
        yield ouverte


@pytest.fixture
def fabrique_cotation() -> Callable[..., Cotation]:
    """Fabrique de cotations de test, aux valeurs par défaut cohérentes."""

    def fabriquer(
        jour: date | str = date(2026, 3, 2),
        cloture: int | None = 1000,
        ticker: str = "TEST1",
        source: str = "fixture",
        statut: StatutSeance = StatutSeance.COTEE,
        volume: int = 100,
        horodatage_donnee: datetime = HORODATAGE,
        horodatage_collecte: datetime = HORODATAGE,
        **extras: object,
    ) -> Cotation:
        parametres: dict[str, object] = {
            "ticker": ticker,
            "date_seance": date.fromisoformat(jour) if isinstance(jour, str) else jour,
            "source": source,
            "statut_seance": statut,
            "cloture": cloture,
            "volume_titres": volume,
            "horodatage_donnee": horodatage_donnee,
            "horodatage_collecte": horodatage_collecte,
        }
        # Les extras peuvent redéfinir un défaut : un test doit pouvoir passer
        # `volume_titres` directement sans que la fabrique le duplique.
        parametres.update(extras)
        return Cotation(**parametres)  # type: ignore[arg-type]

    return fabriquer


# --------------------------------------------------------------------- ingestion


@pytest.fixture
def calendrier(configuration: Configuration) -> CalendrierSeances:
    return construire_calendrier_depuis_config(configuration)


@pytest.fixture
def dormeur() -> Callable[[float], None]:
    """Remplace `time.sleep` : les tests vérifient les reculs sans les subir."""

    def dormir(secondes: float) -> None:
        attentes.append(secondes)

    attentes: list[float] = []
    dormir.attentes = attentes  # type: ignore[attr-defined]
    return dormir


# -------------------------------------------------------------------- technique


@pytest.fixture
def fabrique_serie(
    configuration: Configuration,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
) -> Callable[..., SerieTechnique]:
    """Construit une série technique à partir d'une suite de clôtures.

    ``None`` dans la suite signifie « séance sans transaction » : c'est ainsi que
    l'on reproduit l'illiquidité dans les tests.
    """

    def construire(
        clotures: Sequence[int | None],
        debut: date = date(2026, 3, 2),
        ticker: str = "TEST1",
        amplitude: int = 10,
        volume: int = 100,
        operations: Sequence[OperationSurTitre] = (),
        jusqu_a: date | None = None,
        **extras: object,
    ) -> SerieTechnique:
        seances = calendrier.seances(debut, date(2026, 12, 31))[: len(clotures)]
        cotations: list[Cotation] = []
        for jour, cloture in zip(seances, clotures, strict=False):
            if cloture is None:
                cotations.append(
                    fabrique_cotation(
                        jour=jour,
                        ticker=ticker,
                        cloture=None,
                        statut=StatutSeance.SANS_TRANSACTION,
                        volume=0,
                    )
                )
            else:
                # Les défauts sont posés puis écrasés par les extras : un test
                # doit pouvoir simuler une source qui ne publie pas les montants
                # (`volume_xof=None`) sans que la fabrique le recalcule.
                champs: dict[str, object] = {
                    "jour": jour,
                    "ticker": ticker,
                    "cloture": cloture,
                    "volume": volume,
                    "ouverture": cloture,
                    "plus_haut": cloture + amplitude,
                    "plus_bas": max(1, cloture - amplitude),
                    "volume_xof": cloture * volume,
                }
                champs.update(extras)
                cotations.append(fabrique_cotation(**champs))
        return construire_serie(cotations, calendrier, configuration, operations, jusqu_a=jusqu_a)

    return construire


# ------------------------------------------------------------------ portefeuille


@pytest.fixture
def moteur_frais(configuration: Configuration) -> MoteurFrais:
    return MoteurFrais(configuration)


@pytest.fixture
def moteur_fiscal(configuration: Configuration) -> MoteurFiscal:
    return MoteurFiscal(configuration)


@pytest.fixture
def fabrique_transaction() -> Callable[..., Transaction]:
    """Transaction de test, frais explicites ou absents selon le besoin."""

    def fabriquer(
        identifiant: str,
        ticker: str = "TEST1",
        jour: date = date(2026, 3, 2),
        sens: SensOperation = SensOperation.ACHAT,
        quantite: int = 10,
        cours: int = 1000,
        frais: tuple[LigneFrais, ...] = (),
    ) -> Transaction:
        return Transaction(
            identifiant=identifiant,
            ticker=ticker,
            date_operation=jour,
            sens=sens,
            quantite=quantite,
            cours_unitaire=cours,
            frais=frais,
        )

    return fabriquer


# ------------------------------------------------------------------- marché

#: Repères du banc d'essai « cote » ci-dessous. Une année fictive complète, pour
#: que les fenêtres longues des indicateurs aient de quoi se calculer.
INSTANT_MARCHE = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
DEBUT_MARCHE = date(2026, 1, 5)
FIN_MARCHE = date(2026, 8, 31)


def peupler_cote(
    base: BaseDonnees,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
    ticker: str,
    *,
    une_seance_sur: int = 1,
    depart: int = 1000,
    pas: int = 2,
    debut: date = DEBUT_MARCHE,
    fin: date = FIN_MARCHE,
) -> None:
    """Écrit une série en base, cotée une séance sur ``une_seance_sur``.

    Le volume est calibré pour que le montant échangé approche le volume de
    référence de la configuration de test : en dessous, la profondeur — et donc
    la confiance — s'effondre pour une raison propre au banc et non au code.
    """
    cotations: list[Cotation] = []
    jour = debut
    rang = 0
    while jour <= fin:
        if calendrier.est_jour_de_seance(jour):
            horodatage = datetime(jour.year, jour.month, jour.day, 15, 0, tzinfo=UTC)
            cote = rang % une_seance_sur == 0
            cours = depart + rang * pas
            extras: dict[str, object] = (
                {
                    "ouverture": cours,
                    "plus_haut": cours + 10,
                    "plus_bas": cours - 10,
                    "volume_xof": cours * 5000,
                }
                if cote
                else {}
            )
            cotations.append(
                fabrique_cotation(
                    jour=jour,
                    ticker=ticker,
                    source="fichier_manuel",
                    cloture=cours if cote else None,
                    statut=StatutSeance.COTEE if cote else StatutSeance.SANS_TRANSACTION,
                    volume=5000 if cote else 0,
                    horodatage_donnee=horodatage,
                    horodatage_collecte=horodatage,
                    **extras,
                )
            )
            rang += 1
        jour += timedelta(days=1)
    DepotCotations(base).enregistrer_lot(cotations)


@pytest.fixture
def cote(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
) -> BaseDonnees:
    """Une cote de test : trois valeurs à l'univers, deux avec un historique.

    TEST3 est déclarée inactive, TEST2 ne cote qu'une séance sur six. Les deux
    cas comptent : sur cette place, une valeur peu assidue est la norme, pas
    l'exception.
    """
    DepotInstruments(base).enregistrer_lot(charger_univers(configuration.marche.fichier_univers))
    peupler_cote(base, calendrier, fabrique_cotation, "TEST1")
    peupler_cote(base, calendrier, fabrique_cotation, "TEST2", une_seance_sur=6, pas=-1)
    return base
