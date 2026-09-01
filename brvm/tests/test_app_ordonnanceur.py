"""Ordonnancement : analyse cron, porte du calendrier, exécution.

La règle « seulement les jours de séance » est ce qui distingue cet ordonnanceur
d'un cron ordinaire. Elle est vérifiée ici sans attendre une seule seconde
réelle.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from brvm.app.ordonnanceur import (
    Declenchement,
    Ordonnanceur,
    PolitiqueOrdonnancement,
    seances_a_venir,
)
from brvm.config.modeles import ConfigOrdonnanceur, Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.planification import Cron
from brvm.utils.erreurs import ErreurConfiguration

ABIDJAN = ZoneInfo("Africa/Abidjan")


def reglage(**extras: object) -> ConfigOrdonnanceur:
    parametres: dict[str, object] = {
        "actif": True,
        "cron_collecte": "30 15 * * 0-4",
        "fuseau_horaire": "Africa/Abidjan",
    }
    parametres.update(extras)
    return ConfigOrdonnanceur(**parametres)  # type: ignore[arg-type]


def politique(calendrier: CalendrierSeances, **extras: object) -> PolitiqueOrdonnancement:
    return PolitiqueOrdonnancement(reglage(**extras), calendrier)


class TestAnalyseCron:
    def test_champs_simples(self) -> None:
        cron = Cron.analyser("30 15 * * 0-4")
        assert cron.minutes == frozenset({30})
        assert cron.heures == frozenset({15})
        assert cron.jours_de_semaine == frozenset({0, 1, 2, 3, 4})
        assert len(cron.jours_du_mois) == 31

    def test_listes_plages_et_pas(self) -> None:
        cron = Cron.analyser("0,30 9-11 1,15 */3 *")
        assert cron.minutes == frozenset({0, 30})
        assert cron.heures == frozenset({9, 10, 11})
        assert cron.jours_du_mois == frozenset({1, 15})
        assert cron.mois == frozenset({1, 4, 7, 10})

    def test_lundi_vaut_zero(self) -> None:
        """Convention unique dans tout le projet : 0 = lundi, comme `weekday()`."""
        cron = Cron.analyser("0 12 * * 0")
        assert cron.correspond(datetime(2026, 3, 2, 12, 0))  # un lundi
        assert not cron.correspond(datetime(2026, 3, 1, 12, 0))  # un dimanche

    @pytest.mark.parametrize(
        "expression, fragment",
        [
            ("30 15 * *", "au lieu de 5"),
            ("30 15 * * * *", "au lieu de 5"),
            ("99 15 * * *", "hors bornes"),
            ("30 25 * * *", "hors bornes"),
            ("abc 15 * * *", "illisible"),
            ("30 15 * * 5-1", "Plage inversée"),
            ("30/0 15 * * *", "Pas illisible"),
            ("30 15 * * ,", "vide"),
        ],
    )
    def test_expressions_refusees(self, expression: str, fragment: str) -> None:
        """Une expression fautive est nommée, jamais interprétée au mieux."""
        with pytest.raises(ErreurConfiguration, match=fragment):
            Cron.analyser(expression)


class TestPorteDuCalendrier:
    def test_un_jour_de_seance_declenche(self, calendrier: CalendrierSeances) -> None:
        verdict = politique(calendrier).evaluer(datetime(2026, 3, 2, 15, 30, tzinfo=ABIDJAN))
        assert verdict.declenche is True
        assert verdict.seance == date(2026, 3, 2)

    def test_un_jour_ferie_ne_declenche_pas(self, calendrier: CalendrierSeances) -> None:
        """C'est toute la différence avec un cron ordinaire : le cron correspond,
        mais la bourse est fermée."""
        ferie = next(
            jour
            for jour in (date(2026, 1, 1) + timedelta(days=n) for n in range(365))
            if jour.weekday() < 5 and not calendrier.est_jour_de_seance(jour)
        )
        instant = datetime(ferie.year, ferie.month, ferie.day, 15, 30, tzinfo=ABIDJAN)
        verdict = politique(calendrier).evaluer(instant)
        assert verdict.declenche is False
        assert "pas un jour de séance" in verdict.motif

    def test_hors_couverture_le_systeme_sabstient(self, calendrier: CalendrierSeances) -> None:
        """Hors période couverte, aucune supposition : on ne collecte pas."""
        verdict = politique(calendrier).evaluer(datetime(2019, 3, 4, 15, 30, tzinfo=ABIDJAN))
        assert verdict.declenche is False
        assert "Calendrier indéterminé" in verdict.motif

    def test_hors_heure_ne_declenche_pas(self, calendrier: CalendrierSeances) -> None:
        verdict = politique(calendrier).evaluer(datetime(2026, 3, 2, 9, 0, tzinfo=ABIDJAN))
        assert verdict.declenche is False
        assert "Hors des heures" in verdict.motif

    def test_ordonnanceur_inactif_ne_declenche_jamais(self, calendrier: CalendrierSeances) -> None:
        verdict = politique(calendrier, actif=False).evaluer(
            datetime(2026, 3, 2, 15, 30, tzinfo=ABIDJAN)
        )
        assert verdict.declenche is False
        assert "désactivé" in verdict.motif

    def test_instant_ramene_au_fuseau_declare(self, calendrier: CalendrierSeances) -> None:
        """Une machine en UTC et un cron pensé en heure d'Abidjan doivent tomber
        sur la même séance. Abidjan étant à UTC+0, on le vérifie sur un fuseau
        décalé pour que le test ait un sens."""
        decale = politique(calendrier, fuseau_horaire="Europe/Paris", cron_collecte="30 16 * * 0-4")
        # 15h30 UTC = 16h30 à Paris en mars (heure d'été).
        verdict = decale.evaluer(datetime(2026, 3, 2, 15, 30, tzinfo=UTC))
        assert verdict.declenche is True
        assert verdict.seance == date(2026, 3, 2)

    def test_fuseau_inconnu_refuse(self, calendrier: CalendrierSeances) -> None:
        with pytest.raises(ErreurConfiguration, match="Fuseau horaire inconnu"):
            politique(calendrier, fuseau_horaire="Mars/Olympus_Mons")


class TestProchaineOccurrence:
    def test_prochaine_saute_les_jours_fermes(self, calendrier: CalendrierSeances) -> None:
        depuis = datetime(2026, 3, 6, 16, 0, tzinfo=ABIDJAN)  # vendredi après clôture
        prochaine = politique(calendrier).prochaine(depuis)
        assert prochaine is not None
        assert prochaine.weekday() < 5
        assert prochaine.date() > date(2026, 3, 6)

    def test_prochaines_sont_toutes_des_seances(self, calendrier: CalendrierSeances) -> None:
        prevues = seances_a_venir(
            politique(calendrier), datetime(2026, 3, 2, 0, 0, tzinfo=ABIDJAN), combien=10
        )
        assert len(prevues) == 10
        assert all(calendrier.est_jour_de_seance(instant.date()) for instant in prevues)
        assert all(instant.hour == 15 and instant.minute == 30 for instant in prevues)

    def test_horizon_epuise_rend_none(self, calendrier: CalendrierSeances) -> None:
        """Passé la couverture du calendrier, plus rien n'est planifiable."""
        assert (
            politique(calendrier).prochaine(
                datetime(2026, 12, 31, 23, 0, tzinfo=ABIDJAN), horizon_minutes=60
            )
            is None
        )


class TestExecution:
    def test_execute_laction_le_jour_de_seance(
        self, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        vues: list[date] = []
        ordonnanceur = Ordonnanceur(
            configuration.model_copy(update={"ordonnanceur": reglage()}),
            calendrier,
            action=vues.append,
        )
        verdict = ordonnanceur.executer_si_du(datetime(2026, 3, 2, 15, 30, tzinfo=ABIDJAN))
        assert verdict.declenche is True
        assert vues == [date(2026, 3, 2)]

    def test_naction_rien_hors_seance(
        self, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        vues: list[date] = []
        ordonnanceur = Ordonnanceur(
            configuration.model_copy(update={"ordonnanceur": reglage()}),
            calendrier,
            action=vues.append,
        )
        ordonnanceur.executer_si_du(datetime(2026, 3, 7, 15, 30, tzinfo=ABIDJAN))  # samedi
        assert vues == []

    def test_boucle_enchaine_les_seances_sans_attendre(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        dormeur: Callable[[float], None],
    ) -> None:
        vues: list[date] = []
        ordonnanceur = Ordonnanceur(
            configuration.model_copy(update={"ordonnanceur": reglage()}),
            calendrier,
            action=vues.append,
        )
        resultats = ordonnanceur.boucle(
            datetime(2026, 3, 2, 0, 0, tzinfo=ABIDJAN), occurrences=3, dormir=dormeur
        )
        assert len(resultats) == 3
        assert all(isinstance(verdict, Declenchement) for verdict in resultats)
        assert len(vues) == 3
        assert vues == sorted(vues)
        assert all(calendrier.est_jour_de_seance(jour) for jour in vues)
