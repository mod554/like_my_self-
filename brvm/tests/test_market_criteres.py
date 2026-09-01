"""Notation et composition : ce qui est absent ne vaut pas zéro."""

from __future__ import annotations

from decimal import Decimal

from brvm.market.criteres import (
    Critere,
    Score,
    composer,
    note_centree,
    note_croissante,
    note_decroissante,
)


def mesure(nom: str, note: str) -> Critere:
    return Critere(nom=nom, libelle=nom, valeur=Decimal(note), note=Decimal(note))


class TestNotation:
    def test_note_croissante_borne_aux_deux_bouts(self) -> None:
        assert note_croissante(Decimal("-1"), Decimal(0), Decimal(1)) == Decimal(0)
        assert note_croissante(Decimal("0.5"), Decimal(0), Decimal(1)) == Decimal("0.5")
        assert note_croissante(Decimal("9"), Decimal(0), Decimal(1)) == Decimal(1)

    def test_note_croissante_sature_au_plafond(self) -> None:
        """Un momentum de +80 % ne vaut pas quatre fois un momentum de +20 % :
        il signale surtout un cours peu formé."""
        assert note_croissante(Decimal("0.8"), Decimal(0), Decimal("0.2")) == Decimal(1)

    def test_note_decroissante_est_l_inverse(self) -> None:
        for valeur in ("0", "0.3", "0.7", "1"):
            croissante = note_croissante(Decimal(valeur), Decimal(0), Decimal(1))
            decroissante = note_decroissante(Decimal(valeur), Decimal(0), Decimal(1))
            assert croissante + decroissante == Decimal(1)

    def test_note_centree_penalise_les_deux_extremes(self) -> None:
        """Un RSI à 20 comme à 80 s'éloigne autant du régime."""
        cible, tolerance = Decimal(50), Decimal(30)
        assert note_centree(cible, cible, tolerance) == Decimal(1)
        assert note_centree(Decimal(20), cible, tolerance) == note_centree(
            Decimal(80), cible, tolerance
        )
        assert note_centree(Decimal(5), cible, tolerance) == Decimal(0)

    def test_bornes_inversees_ne_produisent_pas_de_note(self) -> None:
        assert note_croissante(Decimal(5), Decimal(10), Decimal(1)) == Decimal(0)


class TestComposition:
    def test_moyenne_ponderee_des_criteres_mesures(self) -> None:
        score = composer(
            [(mesure("a", "1"), Decimal(3)), (mesure("b", "0"), Decimal(1))],
        )
        assert score.valeur == Decimal("0.75")
        assert score.couverture == Decimal(1)

    def test_un_critere_absent_sort_de_la_moyenne_sans_valoir_zero(self) -> None:
        """Zéro voudrait dire « mauvais » ; l'absence veut dire « on ne sait pas »."""
        avec_zero = composer(
            [(mesure("a", "1"), Decimal(1)), (mesure("b", "0"), Decimal(1))],
        )
        avec_absent = composer(
            [
                (mesure("a", "1"), Decimal(1)),
                (Critere.absent("b", "b", "non mesuré"), Decimal(1)),
            ],
            couverture_minimale=Decimal("0.5"),
        )
        assert avec_zero.valeur == Decimal("0.5")
        assert avec_absent.valeur == Decimal(1)
        assert avec_absent.couverture == Decimal("0.5")

    def test_couverture_insuffisante_refuse_le_score(self) -> None:
        score = composer(
            [
                (mesure("a", "1"), Decimal(1)),
                (Critere.absent("b", "b", "non mesuré"), Decimal(3)),
            ],
            couverture_minimale=Decimal("0.6"),
        )
        assert not score.classable
        assert "couverture insuffisante" in (score.motif_absent or "")
        assert "b" in (score.motif_absent or "")

    def test_une_porte_multiplie_le_score(self) -> None:
        score = composer(
            [(mesure("a", "1"), Decimal(1))],
            portes=[mesure("confiance", "0.5")],
        )
        assert score.valeur == Decimal("0.5")

    def test_une_porte_non_mesurable_annule_le_classement(self) -> None:
        """Une valeur au momentum superbe qui n'échange rien n'est pas une
        demi-occasion : elle n'est pas jouable du tout."""
        score = composer(
            [(mesure("a", "1"), Decimal(1))],
            portes=[Critere.absent("liquidite", "Capacité d'accueil", "rien n'échange")],
        )
        assert not score.classable
        assert "rien n'échange" in (score.motif_absent or "")

    def test_une_porte_basse_est_signalee(self) -> None:
        score = composer(
            [(mesure("a", "1"), Decimal(1))],
            portes=[mesure("confiance", "0.1")],
        )
        assert score.classable
        assert any("écrase le score" in a for a in score.avertissements)

    def test_couverture_partielle_est_signalee(self) -> None:
        score = composer(
            [
                (mesure("a", "1"), Decimal(1)),
                (Critere.absent("b", "b", "absent"), Decimal(1)),
            ],
            couverture_minimale=Decimal("0.5"),
        )
        assert any("ne se comparent pas" in a for a in score.avertissements)

    def test_sans_critere_pondere_aucun_score(self) -> None:
        assert not composer([]).classable

    def test_le_score_reste_borne(self) -> None:
        score = composer([(mesure("a", "1"), Decimal(1))], portes=[mesure("p", "1")])
        assert Decimal(0) <= (score.valeur or Decimal(0)) <= Decimal(1)

    def test_le_score_expose_ce_qui_manque(self) -> None:
        score = composer(
            [
                (mesure("a", "1"), Decimal(1)),
                (Critere.absent("b", "b", "absent"), Decimal(1)),
            ],
            couverture_minimale=Decimal("0.5"),
        )
        assert [c.nom for c in score.manquants()] == ["b"]
        assert [c.nom for c in score.mesurables()] == ["a"]


class TestScoreVide:
    def test_un_score_sans_valeur_n_est_pas_classable(self) -> None:
        assert not Score(valeur=None).classable
