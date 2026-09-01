"""Criblage de la cote : ce qui n'a pas pu être analysé ressort avec sa raison.

Sur cette place, les valeurs écartées sont souvent la majorité. Les tests d'ici
vérifient surtout qu'aucune ne disparaît silencieusement d'un tableau.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import StatutSeance
from brvm.domain.modeles import Cotation
from brvm.ingestion.univers import charger_univers
from brvm.market.criblage import cribler
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotInstruments

INSTANT = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
DEBUT = date(2026, 1, 5)
FIN = date(2026, 8, 31)


def peupler(
    base: BaseDonnees,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
    ticker: str,
    *,
    une_seance_sur: int = 1,
    depart: int = 1000,
    pas: int = 2,
    debut: date = DEBUT,
    fin: date = FIN,
) -> None:
    """Écrit une série en base, cotée une séance sur ``une_seance_sur``."""
    cotations: list[Cotation] = []
    jour = debut
    rang = 0
    while jour <= fin:
        if calendrier.est_jour_de_seance(jour):
            horodatage = datetime(jour.year, jour.month, jour.day, 15, 0, tzinfo=UTC)
            cote = rang % une_seance_sur == 0
            cours = depart + rang * pas
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
                    **(
                        {
                            "ouverture": cours,
                            "plus_haut": cours + 10,
                            "plus_bas": cours - 10,
                            "volume_xof": cours * 5000,
                        }
                        if cote
                        else {}
                    ),
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
    """Trois valeurs à l'univers, dont une inactive et une jamais cotée."""
    DepotInstruments(base).enregistrer_lot(charger_univers(configuration.marche.fichier_univers))
    peupler(base, calendrier, fabrique_cotation, "TEST1")
    peupler(base, calendrier, fabrique_cotation, "TEST2", une_seance_sur=6, pas=-1)
    return base


class TestUnivers:
    def test_referentiel_vide_ne_crible_rien_et_le_dit(
        self,
        base: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        criblage = cribler(base, configuration, calendrier, instant=INSTANT)
        assert criblage.analyses == ()
        assert any("référentiel des valeurs est vide" in a for a in criblage.avertissements)

    def test_valeur_inactive_n_est_pas_criblee(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """TEST3 est déclarée inactive dans l'univers : elle ne fait plus partie
        de la cote à cribler."""
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        vus = {a.ticker for a in criblage.analyses} | {e.ticker for e in criblage.ecartees}
        assert "TEST3" not in vus

    def test_valeur_sans_cotation_ressort_avec_sa_raison(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        criblage = cribler(
            cote, configuration, calendrier, instant=INSTANT, tickers=["TEST1", "JAMAIS"]
        )
        ecartees = {e.ticker: e.motif for e in criblage.ecartees}
        assert "JAMAIS" in ecartees
        assert "aucune cotation en base" in ecartees["JAMAIS"]
        assert criblage.univers == 2

    def test_restriction_par_tickers_est_respectee(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT, tickers=["TEST1"])
        assert [a.ticker for a in criblage.analyses] == ["TEST1"]


class TestBorneDeConnaissance:
    def test_rien_de_posterieur_a_la_borne_n_est_lu(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Un criblage rejoué à une date passée ne doit consulter aucune séance
        qui n'existait pas encore."""
        borne = date(2026, 4, 30)
        criblage = cribler(
            cote, configuration, calendrier, instant=INSTANT, jusqu_a=borne, tickers=["TEST1"]
        )
        analyse = criblage.analyses[0]
        assert analyse.date_cours is not None
        assert analyse.date_cours <= borne

    def test_le_cours_retenu_avance_avec_la_borne(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        tot = cribler(
            cote,
            configuration,
            calendrier,
            instant=INSTANT,
            jusqu_a=date(2026, 4, 30),
            tickers=["TEST1"],
        )
        tard = cribler(
            cote, configuration, calendrier, instant=INSTANT, jusqu_a=FIN, tickers=["TEST1"]
        )
        assert tot.analyses[0].cours is not None
        assert tard.analyses[0].cours is not None
        assert tard.analyses[0].cours > tot.analyses[0].cours


class TestFraicheur:
    def test_horodatage_le_plus_ancien_est_rapporte(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        assert criblage.horodatage_le_plus_ancien is not None
        assert criblage.age_minutes() is not None
        assert "Donnée la plus ancienne" in criblage.entete_fraicheur()

    def test_sans_cotation_la_fraicheur_le_dit_au_lieu_de_zero(
        self,
        base: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        DepotInstruments(base).enregistrer_lot(
            charger_univers(configuration.marche.fichier_univers)
        )
        criblage = cribler(base, configuration, calendrier, instant=INSTANT)
        assert criblage.age_minutes() is None
        assert "n'est pas analysable" in criblage.entete_fraicheur()


class TestClassements:
    def test_tous_les_profils_declares_sont_produits(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        assert set(criblage.classements) == set(configuration.analyse.horizons)

    def test_valeur_tres_illiquide_est_ecartee_du_court_terme_avec_sa_raison(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """TEST2 ne cote qu'une séance sur six : sa confiance tombe sous le
        seuil, et elle sort du classement plutôt que d'y figurer mal notée."""
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        court = criblage.classements["court_terme"]
        ecartes = {rang.ticker for rang in court.ecartes}
        assert "TEST2" in ecartes
        motif = next(r.score.motif_absent for r in court.ecartes if r.ticker == "TEST2")
        assert motif

    def test_couverture_par_critere_est_disponible(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        couverture = criblage.couverture_criteres()
        assert couverture["momentum"] >= 1
        assert "rendement_dividende" in couverture


class TestFondamentaux:
    def test_referentiel_partiel_est_compte_et_signale(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Le fichier de test renseigne TEST1 et TEST2 : les deux valeurs
        criblées le sont, et le criblage l'annonce."""
        criblage = cribler(cote, configuration, calendrier, instant=INSTANT)
        assert criblage.fondamentaux_renseignes == len(criblage.analyses)

    def test_sans_referentiel_le_long_terme_s_abstient_et_le_dit(
        self,
        cote: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tmp_path: object,
    ) -> None:
        vide = configuration.analyse.fichier_fondamentaux.parent / "fondamentaux_absent.csv"
        sans = configuration.model_copy(
            update={
                "analyse": configuration.analyse.model_copy(update={"fichier_fondamentaux": vide})
            }
        )
        criblage = cribler(cote, sans, calendrier, instant=INSTANT)
        assert criblage.fondamentaux_renseignes == 0
        assert any("Aucune donnée fondamentale saisie" in a for a in criblage.avertissements)
        long_terme = criblage.classements["long_terme"]
        assert long_terme.classes == ()
        assert long_terme.ecartes

    def test_fichier_absent_ne_fait_pas_echouer_le_criblage(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Un référentiel non encore rempli est un état normal du système, pas
        une erreur : le criblage technique continue."""
        vide = configuration.analyse.fichier_fondamentaux.parent / "pas_encore_saisi.csv"
        sans = configuration.model_copy(
            update={
                "analyse": configuration.analyse.model_copy(update={"fichier_fondamentaux": vide})
            }
        )
        criblage = cribler(sans_base := cote, sans, calendrier, instant=INSTANT)
        assert sans_base is cote
        assert criblage.analyses
        assert criblage.classements["court_terme"].classes
