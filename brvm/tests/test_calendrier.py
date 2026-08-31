"""Calendrier de séances : jours ouvrés, fériés par pays, couverture déclarée."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from brvm.domain.calendrier import CalendrierSeances, construire_calendrier
from brvm.domain.enums import Pays
from brvm.utils.erreurs import ErreurCalendrier, ErreurConfiguration

# Dates fictives, choisies pour leurs positions dans la semaine :
#   2026-03-02 lundi · 2026-03-06 vendredi · 2026-03-07 samedi · 2026-03-08 dimanche
LUNDI = date(2026, 3, 2)
VENDREDI = date(2026, 3, 6)
SAMEDI = date(2026, 3, 7)
DIMANCHE = date(2026, 3, 8)


def calendrier(
    feries: dict[Pays, list[date]] | None = None,
    fermetures: list[date] | None = None,
    debut: date = date(2026, 1, 1),
    fin: date = date(2026, 12, 31),
) -> CalendrierSeances:
    return construire_calendrier(
        pays_place=Pays.COTE_DIVOIRE,
        couverture_debut=debut,
        couverture_fin=fin,
        feries_par_pays=feries or {},
        fermetures_exceptionnelles=fermetures or [],
    )


class TestJoursDeSeance:
    def test_semaine_ouvree(self) -> None:
        assert calendrier().est_jour_de_seance(LUNDI)
        assert calendrier().est_jour_de_seance(VENDREDI)

    def test_week_end_ferme(self) -> None:
        cal = calendrier()
        assert not cal.est_jour_de_seance(SAMEDI)
        assert not cal.est_jour_de_seance(DIMANCHE)

    def test_ferie_du_pays_de_la_place_ferme_la_bourse(self) -> None:
        cal = calendrier(feries={Pays.COTE_DIVOIRE: [LUNDI]})
        assert not cal.est_jour_de_seance(LUNDI)

    def test_ferie_d_un_autre_pays_ne_ferme_pas_la_bourse(self) -> None:
        """Un férié sénégalais n'interrompt pas la séance : il explique seulement
        qu'une valeur sénégalaise puisse ne pas coter ce jour-là."""
        cal = calendrier(feries={Pays.SENEGAL: [LUNDI]})
        assert cal.est_jour_de_seance(LUNDI)
        assert cal.est_ferie(LUNDI, Pays.SENEGAL)
        assert not cal.est_ferie(LUNDI, Pays.COTE_DIVOIRE)

    def test_fermeture_exceptionnelle(self) -> None:
        cal = calendrier(fermetures=[LUNDI])
        assert not cal.est_jour_de_seance(LUNDI)


class TestParcours:
    def test_prochaine_seance_saute_le_week_end(self) -> None:
        assert calendrier().prochaine_seance(VENDREDI) == date(2026, 3, 9)

    def test_prochaine_seance_inclusive(self) -> None:
        assert calendrier().prochaine_seance(VENDREDI, inclusif=True) == VENDREDI

    def test_seance_precedente_saute_le_week_end(self) -> None:
        assert calendrier().seance_precedente(date(2026, 3, 9)) == VENDREDI

    def test_prochaine_seance_saute_un_ferie(self) -> None:
        cal = calendrier(feries={Pays.COTE_DIVOIRE: [date(2026, 3, 9)]})
        assert cal.prochaine_seance(VENDREDI) == date(2026, 3, 10)

    def test_liste_des_seances_d_une_semaine(self) -> None:
        seances = calendrier().seances(LUNDI, DIMANCHE)
        assert seances == [date(2026, 3, jour) for jour in range(2, 7)]

    def test_nb_seances(self) -> None:
        assert calendrier().nb_seances(LUNDI, DIMANCHE) == 5

    def test_intervalle_inverse_vide(self) -> None:
        assert calendrier().seances(DIMANCHE, LUNDI) == []


class TestCouverture:
    def test_date_hors_couverture_refusee(self) -> None:
        """Le système refuse de dire si un jour non couvert est une séance :
        un « False » non fondé serait indiscernable d'un vrai jour fermé."""
        cal = calendrier(debut=date(2026, 1, 1), fin=date(2026, 6, 30))
        with pytest.raises(ErreurCalendrier) as capture:
            cal.est_jour_de_seance(date(2026, 9, 1))
        assert "ne couvre pas" in str(capture.value)

    def test_message_indique_la_periode_couverte(self) -> None:
        cal = calendrier(debut=date(2026, 1, 1), fin=date(2026, 6, 30))
        with pytest.raises(ErreurCalendrier) as capture:
            cal.seances(date(2025, 12, 1), date(2026, 1, 31))
        message = str(capture.value)
        assert "2026-01-01" in message and "2026-06-30" in message

    def test_couverture_inversee_refusee(self) -> None:
        with pytest.raises(ErreurConfiguration):
            calendrier(debut=date(2026, 12, 31), fin=date(2026, 1, 1))


class TestConfigurationInvalide:
    def test_aucun_jour_ouvre(self) -> None:
        with pytest.raises(ErreurConfiguration):
            construire_calendrier(
                pays_place=Pays.COTE_DIVOIRE,
                couverture_debut=date(2026, 1, 1),
                couverture_fin=date(2026, 12, 31),
                jours_ouvres=[],
            )

    def test_jour_ouvre_hors_intervalle(self) -> None:
        with pytest.raises(ErreurConfiguration):
            construire_calendrier(
                pays_place=Pays.COTE_DIVOIRE,
                couverture_debut=date(2026, 1, 1),
                couverture_fin=date(2026, 12, 31),
                jours_ouvres=[0, 7],
            )

    def test_calendrier_sature_de_feries_signale_plutot_que_de_boucler(self) -> None:
        tous_les_jours = [date(2026, 1, 1) + timedelta(days=n) for n in range(120)]
        cal = calendrier(feries={Pays.COTE_DIVOIRE: tous_les_jours})
        with pytest.raises(ErreurCalendrier) as capture:
            cal.prochaine_seance(date(2026, 1, 1))
        assert "mal renseigné" in str(capture.value)


class TestAvertissements:
    def test_annee_sans_ferie_declare_est_signalee(self) -> None:
        messages = calendrier().avertissements()
        assert len(messages) == 1
        assert "2026" in messages[0]

    def test_aucun_avertissement_si_feries_declares(self) -> None:
        cal = calendrier(feries={Pays.COTE_DIVOIRE: [date(2026, 1, 1)]})
        assert cal.avertissements() == []

    def test_un_avertissement_par_annee_non_couverte(self) -> None:
        cal = calendrier(
            feries={Pays.COTE_DIVOIRE: [date(2026, 1, 1)]},
            debut=date(2025, 1, 1),
            fin=date(2027, 12, 31),
        )
        messages = cal.avertissements()
        assert len(messages) == 2
        assert any("2025" in message for message in messages)
        assert any("2027" in message for message in messages)
