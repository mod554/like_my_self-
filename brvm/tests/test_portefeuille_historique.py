"""Historisation des valorisations, et le repli qu'elle rend mesurable.

Le point vérifié n'est pas qu'une série se stocke, mais que le repli **refuse**
de se calculer sur les seuls titres. Le mesurer ainsi ferait apparaître un recul
de 100 % dès qu'une ligne est soldée, alors que l'argent est passé en espèces —
exactement la faute qui avait fait retirer le TWR.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from brvm.domain.modeles import Valorisation
from brvm.portfolio.historique import (
    MOTIF_ACTIF_INCOMPLET,
    MOTIF_SERIE_TROP_COURTE,
    serie_actif_total,
)
from brvm.risk.mesures import calculer_drawdown
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotValorisations

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)


def valorisation(
    jour: date, titres: int, especes: int | None = None, motif: str | None = None
) -> Valorisation:
    return Valorisation(
        date_seance=jour,
        valeur_titres=titres,
        cout_total=titres,
        plus_value_brute=0,
        nb_lignes=1,
        horodatage_calcul=INSTANT,
        especes=especes,
        actif_total=None if especes is None else titres + especes,
        motif_especes=motif if especes is None else None,
    )


class TestModele:
    def test_actif_total_et_especes_vont_ensemble(self) -> None:
        with pytest.raises(ValueError, match="vont ensemble"):
            Valorisation(
                date_seance=date(2026, 3, 2),
                valeur_titres=100,
                cout_total=100,
                plus_value_brute=0,
                nb_lignes=1,
                horodatage_calcul=INSTANT,
                especes=50,
                actif_total=None,
            )

    def test_un_solde_absent_doit_porter_son_motif(self) -> None:
        """Une absence sans raison ne se distingue pas d'un oubli."""
        with pytest.raises(ValueError, match="motif"):
            Valorisation(
                date_seance=date(2026, 3, 2),
                valeur_titres=100,
                cout_total=100,
                plus_value_brute=0,
                nb_lignes=1,
                horodatage_calcul=INSTANT,
            )

    def test_l_actif_total_doit_etre_la_somme(self) -> None:
        with pytest.raises(ValueError, match="ne correspond pas"):
            Valorisation(
                date_seance=date(2026, 3, 2),
                valeur_titres=100,
                cout_total=100,
                plus_value_brute=0,
                nb_lignes=1,
                horodatage_calcul=INSTANT,
                especes=50,
                actif_total=999,
            )

    def test_plus_de_non_valorisees_que_de_lignes_est_refuse(self) -> None:
        with pytest.raises(ValueError, match="Plus de lignes non valorisées"):
            Valorisation(
                date_seance=date(2026, 3, 2),
                valeur_titres=100,
                cout_total=100,
                plus_value_brute=0,
                nb_lignes=1,
                nb_non_valorisees=2,
                horodatage_calcul=INSTANT,
                especes=0,
                actif_total=100,
            )


class TestSerieActifTotal:
    def test_serie_complete_est_exploitable(self) -> None:
        serie, motif = serie_actif_total(
            [
                valorisation(date(2026, 3, 2), 1_000, 500),
                valorisation(date(2026, 3, 3), 1_100, 500),
            ]
        )
        assert motif is None
        assert serie == [(date(2026, 3, 2), 1_500), (date(2026, 3, 3), 1_600)]

    def test_un_seul_point_manquant_invalide_toute_la_serie(self) -> None:
        """Une série partielle sauterait au-dessus des creux et sous-estimerait
        le recul."""
        serie, motif = serie_actif_total(
            [
                valorisation(date(2026, 3, 2), 1_000, 500),
                valorisation(date(2026, 3, 3), 1_100, None, "aucun apport déclaré"),
                valorisation(date(2026, 3, 4), 1_200, 500),
            ]
        )
        assert serie == []
        assert motif == MOTIF_ACTIF_INCOMPLET

    def test_le_motif_explique_pourquoi_pas_sur_les_titres_seuls(self) -> None:
        _, motif = serie_actif_total([valorisation(date(2026, 3, 2), 1_000, None, "x")])
        assert motif is not None
        assert "100 %" in motif

    def test_une_seule_seance_ne_mesure_aucun_repli(self) -> None:
        serie, motif = serie_actif_total([valorisation(date(2026, 3, 2), 1_000, 500)])
        assert serie == []
        assert motif == MOTIF_SERIE_TROP_COURTE

    def test_serie_vide(self) -> None:
        serie, motif = serie_actif_total([])
        assert serie == []
        assert motif is not None


class TestReplíSurActifTotal:
    def test_un_portefeuille_solde_ne_recule_pas_de_cent_pour_cent(self) -> None:
        """Le cas qui avait fait retirer le TWR : tout vendre laisse les espèces."""
        serie, motif = serie_actif_total(
            [
                valorisation(date(2026, 3, 2), 1_000_000, 0),
                valorisation(date(2026, 3, 3), 0, 990_000),  # tout vendu, frais payés
            ]
        )
        assert motif is None
        resultat = calculer_drawdown(serie)
        assert resultat.drawdown_courant < Decimal("0.02"), "un aller-retour ne coûte que ses frais"

    def test_le_repli_se_mesure_bien_quand_l_actif_baisse(self) -> None:
        serie, _ = serie_actif_total(
            [
                valorisation(date(2026, 3, 2), 1_000_000, 0),
                valorisation(date(2026, 3, 3), 800_000, 0),
            ]
        )
        recul = calculer_drawdown(serie).drawdown_courant
        assert abs(recul - Decimal("0.2")) < Decimal("0.000001")


class TestDepot:
    def test_ecriture_idempotente_sur_la_seance(self, base: BaseDonnees) -> None:
        """Deux valorisations d'une même séance se contrediraient."""
        depot = DepotValorisations(base)
        depot.enregistrer(valorisation(date(2026, 3, 2), 1_000, 500))
        depot.enregistrer(valorisation(date(2026, 3, 2), 1_200, 500))
        lignes = depot.lire()
        assert len(lignes) == 1
        assert lignes[0].valeur_titres == 1_200

    def test_lecture_ordonnee_et_bornee(self, base: BaseDonnees) -> None:
        depot = DepotValorisations(base)
        for jour in (date(2026, 3, 4), date(2026, 3, 2), date(2026, 3, 3)):
            depot.enregistrer(valorisation(jour, 1_000, 500))
        assert [v.date_seance.day for v in depot.lire()] == [2, 3, 4]
        bornee = depot.lire(debut=date(2026, 3, 3), fin=date(2026, 3, 3))
        assert [v.date_seance.day for v in bornee] == [3]

    def test_un_solde_absent_traverse_la_base(self, base: BaseDonnees) -> None:
        depot = DepotValorisations(base)
        depot.enregistrer(valorisation(date(2026, 3, 2), 1_000, None, "aucun apport"))
        relue = depot.lire()[0]
        assert relue.especes is None
        assert relue.actif_total is None
        assert relue.motif_especes == "aucun apport"

    def test_derniere_valorisation(self, base: BaseDonnees) -> None:
        depot = DepotValorisations(base)
        assert depot.derniere() is None
        depot.enregistrer(valorisation(date(2026, 3, 2), 1_000, 500))
        depot.enregistrer(valorisation(date(2026, 3, 5), 1_100, 500))
        derniere = depot.derniere()
        assert derniere is not None and derniere.date_seance == date(2026, 3, 5)
