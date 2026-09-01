"""Référentiel fondamental : lecture stricte, ratios qui refusent de mentir."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from brvm.market.fondamentaux import (
    EXERCICES_AVANT_PEREMPTION,
    Fondamentaux,
    calculer_ratios,
    charger_fondamentaux,
    dernier_exercice,
    regularite_dividende,
)
from brvm.utils.erreurs import ErreurConfiguration

ENTETE = (
    "ticker,exercice,source,dividende_par_action,resultat_net_par_action,"
    "capitaux_propres_par_action,nombre_actions,date_releve,commentaire"
)


def ecrire(tmp_path: Path, *lignes: str) -> Path:
    fichier = tmp_path / "fondamentaux.csv"
    fichier.write_text("\n".join([ENTETE, *lignes]) + "\n", encoding="utf-8")
    return fichier


def comptes(**extras: object) -> Fondamentaux:
    parametres: dict[str, object] = {
        "ticker": "TEST1",
        "exercice": 2025,
        "source": "Rapport annuel fictif",
        "dividende_par_action": 120,
        "resultat_net_par_action": 450,
        "capitaux_propres_par_action": 3200,
    }
    parametres.update(extras)
    return Fondamentaux(**parametres)  # type: ignore[arg-type]


class TestLecture:
    def test_lit_et_trie_du_plus_recent(self, dossier_config: Path) -> None:
        referentiel = charger_fondamentaux(dossier_config / "fondamentaux_test.csv")
        assert [f.exercice for f in referentiel["TEST1"]] == [2025, 2024, 2023]

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path: Path) -> None:
        """C'est l'état initial du système : les scores fondamentaux s'abstiennent."""
        assert charger_fondamentaux(tmp_path / "jamais_cree.csv") == {}

    def test_colonne_vide_reste_absente(self, dossier_config: Path) -> None:
        referentiel = charger_fondamentaux(dossier_config / "fondamentaux_test.csv")
        assert referentiel["TEST2"][0].dividende_par_action is None

    def test_source_obligatoire(self, tmp_path: Path) -> None:
        """Un chiffre sans provenance n'est pas auditable."""
        with pytest.raises(ErreurConfiguration, match="source"):
            charger_fondamentaux(ecrire(tmp_path, "TEST1,2025,,120,450,3200,1000,,"))

    def test_exercice_en_double_refuse(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="deux fois"):
            charger_fondamentaux(
                ecrire(
                    tmp_path,
                    "TEST1,2025,Rapport,120,450,3200,1000,,",
                    "TEST1,2025,Autre,130,460,3300,1000,,",
                )
            )

    def test_exercice_illisible_refuse(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="exercice illisible"):
            charger_fondamentaux(ecrire(tmp_path, "TEST1,l'an dernier,Rapport,,,,,,"))

    def test_montant_decimal_refuse(self, tmp_path: Path) -> None:
        """Le XOF ne circule pas en centimes."""
        with pytest.raises(ErreurConfiguration, match="décimales"):
            charger_fondamentaux(ecrire(tmp_path, "TEST1,2025,Rapport,120.5,,,,,"))

    def test_dernier_exercice(self, dossier_config: Path) -> None:
        referentiel = charger_fondamentaux(dossier_config / "fondamentaux_test.csv")
        recent = dernier_exercice(referentiel, "TEST1")
        assert recent is not None
        assert recent.exercice == 2025
        assert dernier_exercice(referentiel, "INCONNU") is None


class TestRatios:
    def test_les_trois_ratios_se_calculent(self) -> None:
        ratios = calculer_ratios(comptes(), cours=4000, annee_courante=2026)
        assert ratios.per is not None
        assert ratios.price_book is not None
        assert ratios.rendement_dividende == Decimal("0.03")
        assert round(ratios.per, 2) == Decimal("8.89")
        assert round(ratios.price_book, 4) == Decimal("1.25")
        assert ratios.exploitable

    def test_un_per_sur_une_perte_n_est_pas_calcule(self) -> None:
        """Il se lirait comme une valorisation."""
        ratios = calculer_ratios(
            comptes(resultat_net_par_action=-80), cours=4000, annee_courante=2026
        )
        assert ratios.per is None
        assert any("négatif" in a for a in ratios.avertissements)

    def test_des_capitaux_propres_negatifs_ne_donnent_pas_de_ratio(self) -> None:
        ratios = calculer_ratios(
            comptes(capitaux_propres_par_action=-500), cours=4000, annee_courante=2026
        )
        assert ratios.price_book is None

    def test_une_donnee_absente_reste_absente(self) -> None:
        ratios = calculer_ratios(
            comptes(dividende_par_action=None), cours=4000, annee_courante=2026
        )
        assert ratios.rendement_dividende is None
        assert ratios.per is not None

    def test_un_exercice_ancien_est_signale(self) -> None:
        vieux = comptes(exercice=2026 - EXERCICES_AVANT_PEREMPTION - 1)
        ratios = calculer_ratios(vieux, cours=4000, annee_courante=2026)
        assert any("telle qu'elle était" in a for a in ratios.avertissements)

    def test_un_exercice_recent_n_est_pas_signale(self) -> None:
        ratios = calculer_ratios(comptes(exercice=2026), cours=4000, annee_courante=2026)
        assert not any("ancienneté" in a for a in ratios.avertissements)

    def test_aucun_ratio_exploitable_sans_donnee(self) -> None:
        vide = Fondamentaux(ticker="X", exercice=2025, source="néant")
        assert not calculer_ratios(vide, 4000, 2026).exploitable


class TestRegularite:
    def test_compte_les_exercices_avec_dividende(self) -> None:
        """Le dénominateur montre sur combien d'exercices on juge."""
        exercices = [
            comptes(exercice=2025, dividende_par_action=120),
            comptes(exercice=2024, dividende_par_action=110),
            comptes(exercice=2023, dividende_par_action=0),
        ]
        assert regularite_dividende(exercices) == (2, 3)

    def test_les_exercices_non_renseignes_ne_comptent_pas(self) -> None:
        exercices = [
            comptes(exercice=2025, dividende_par_action=120),
            comptes(exercice=2024, dividende_par_action=None),
        ]
        assert regularite_dividende(exercices) == (1, 1)

    def test_sans_exercice_le_compte_est_nul(self) -> None:
        assert regularite_dividende([]) == (0, 0)


class TestPeremption:
    def test_seuil_de_peremption(self) -> None:
        recent = comptes(exercice=2026 - EXERCICES_AVANT_PEREMPTION)
        ancien = comptes(exercice=2026 - EXERCICES_AVANT_PEREMPTION - 1)
        assert not recent.perime(2026)
        assert ancien.perime(2026)
        assert ancien.anciennete(2026) == EXERCICES_AVANT_PEREMPTION + 1
