"""Valorisation et simulateur d'ordre : coût réel, fraîcheur, seuil de rentabilité."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from brvm.domain.enums import SensOperation, StatutSeance, TypeFluxEspece
from brvm.domain.modeles import Cotation, FluxEspece, Transaction
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.positions import suivre
from brvm.portfolio.simulateur import position_vide, seuil_rentabilite, simuler
from brvm.portfolio.valorisation import valoriser
from brvm.utils.erreurs import ErreurValidation

T = datetime(2026, 8, 28, 15, 30, tzinfo=UTC)


def cotation(ticker: str, cloture: int, horodatage: datetime = T) -> Cotation:
    return Cotation(
        ticker=ticker,
        date_seance=horodatage.date(),
        source="fixture",
        statut_seance=StatutSeance.COTEE,
        cloture=cloture,
        volume_titres=100,
        horodatage_donnee=horodatage,
        horodatage_collecte=T,
    )


class TestValorisation:
    def test_ligne_valorisee_au_dernier_cours(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(
            suivi, {"TEST1": cotation("TEST1", 1_200)}, moteur_frais, moteur_fiscal
        )
        ligne = portefeuille.lignes[0]
        assert ligne.valeur == 12_000
        assert ligne.plus_value_latente_brute == 2_000

    def test_la_plus_value_nette_retranche_frais_et_impot(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """Ce qui resterait si l'on vendait aujourd'hui, et non le gain affiché."""
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(
            suivi, {"TEST1": cotation("TEST1", 1_200)}, moteur_frais, moteur_fiscal
        )
        ligne = portefeuille.lignes[0]
        assert ligne.frais_cession_estimes is not None
        assert ligne.plus_value_latente_nette is not None
        assert ligne.plus_value_latente_nette < ligne.plus_value_latente_brute  # type: ignore[operator]
        assert (
            ligne.plus_value_latente_nette
            == ligne.plus_value_latente_brute - ligne.frais_cession_estimes  # type: ignore[operator]
        )

    def test_poids_des_lignes(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre(
            [
                fabrique_transaction("T1", ticker="TEST1", quantite=10, cours=1_000),
                fabrique_transaction("T2", ticker="TEST2", quantite=10, cours=3_000),
            ]
        )
        portefeuille = valoriser(
            suivi,
            {"TEST1": cotation("TEST1", 1_000), "TEST2": cotation("TEST2", 3_000)},
            moteur_frais,
            moteur_fiscal,
        )
        poids = {ligne.ticker: ligne.poids for ligne in portefeuille.lignes}
        assert poids["TEST1"] == Decimal("0.250000")
        assert poids["TEST2"] == Decimal("0.750000")

    def test_ligne_sans_cours_n_est_pas_comptee_pour_zero(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """La compter à zéro afficherait une perte totale qui n'a pas eu lieu."""
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(suivi, {}, moteur_frais, moteur_fiscal)
        ligne = portefeuille.lignes[0]
        assert ligne.valeur is None
        assert ligne.plus_value_latente_brute is None
        assert portefeuille.valeur_totale == 0
        assert any("n'est pas valorisée" in a for a in portefeuille.avertissements)
        assert portefeuille.lignes_non_valorisees


class TestFraicheur:
    def test_horodatage_le_plus_ancien_retenu(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """Chaque écran doit afficher l'âge de la donnée la plus périmée qu'il utilise."""
        ancien = T - timedelta(days=7)
        suivi = suivre(
            [
                fabrique_transaction("T1", ticker="TEST1", quantite=10, cours=1_000),
                fabrique_transaction("T2", ticker="TEST2", quantite=10, cours=1_000),
            ]
        )
        portefeuille = valoriser(
            suivi,
            {
                "TEST1": cotation("TEST1", 1_000),
                "TEST2": cotation("TEST2", 1_000, horodatage=ancien),
            },
            moteur_frais,
            moteur_fiscal,
        )
        assert portefeuille.horodatage_le_plus_ancien == ancien
        assert portefeuille.age_donnee_la_plus_ancienne(T) == Decimal(7 * 24 * 60)

    def test_entete_de_fraicheur(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(
            suivi, {"TEST1": cotation("TEST1", 1_000)}, moteur_frais, moteur_fiscal
        )
        assert "Donnée la plus ancienne" in portefeuille.entete_fraicheur(T)

    def test_portefeuille_non_valorise_le_dit(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(suivi, {}, moteur_frais, moteur_fiscal)
        assert portefeuille.horodatage_le_plus_ancien is None
        assert "n'est pas valorisé" in portefeuille.entete_fraicheur(T)


class TestDividendes:
    def test_dividendes_nets_rattaches_aux_lignes(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        flux = [
            FluxEspece(
                identifiant="F1",
                date_flux=date(2026, 5, 22),
                type_flux=TypeFluxEspece.DIVIDENDE,
                ticker="TEST1",
                montant_brut=5_000,
                retenue_fiscale=500,
                source="fixture",
            )
        ]
        portefeuille = valoriser(
            suivi, {"TEST1": cotation("TEST1", 1_000)}, moteur_frais, moteur_fiscal, flux
        )
        assert portefeuille.dividendes_nets_encaisses == 4_500
        assert portefeuille.lignes[0].dividendes_nets == 4_500


class TestSimulateur:
    def test_seuil_de_rentabilite_superieur_au_cours_d_achat(
        self, moteur_frais: MoteurFrais, moteur_fiscal: MoteurFiscal
    ) -> None:
        """Frais d'achat et de revente doivent d'abord être couverts."""
        simulation = simuler(
            "TEST1",
            SensOperation.ACHAT,
            100,
            10_000,
            moteur_frais,
            moteur_fiscal,
            position_vide("TEST1"),
        )
        assert simulation.seuil_rentabilite is not None
        assert simulation.seuil_rentabilite > 10_000
        assert simulation.hausse_necessaire is not None
        assert simulation.hausse_necessaire > 0

    def test_seuil_juste_au_franc_pres(
        self, moteur_frais: MoteurFrais, moteur_fiscal: MoteurFiscal
    ) -> None:
        """Au seuil, la revente couvre tout ; un franc en dessous, elle ne couvre plus."""
        simulation = simuler(
            "TEST1",
            SensOperation.ACHAT,
            100,
            10_000,
            moteur_frais,
            moteur_fiscal,
            position_vide("TEST1"),
        )
        seuil = simulation.seuil_rentabilite
        assert seuil is not None
        cout = simulation.cout_total_apres

        au_seuil = moteur_frais.calculer(SensOperation.VENTE, 100, seuil).montant_net
        juste_en_dessous = moteur_frais.calculer(SensOperation.VENTE, 100, seuil - 1).montant_net
        assert au_seuil >= cout
        assert juste_en_dessous < cout

    def test_un_petit_ordre_exige_une_hausse_plus_forte(
        self, moteur_frais: MoteurFrais, moteur_fiscal: MoteurFiscal
    ) -> None:
        """Le minimum de perception du barème de test pèse lourd sur un petit montant."""
        petit = simuler(
            "TEST1",
            SensOperation.ACHAT,
            1,
            10_000,
            moteur_frais,
            moteur_fiscal,
            position_vide("TEST1"),
        )
        gros = simuler(
            "TEST1",
            SensOperation.ACHAT,
            1_000,
            10_000,
            moteur_frais,
            moteur_fiscal,
            position_vide("TEST1"),
        )
        assert petit.hausse_necessaire is not None and gros.hausse_necessaire is not None
        assert petit.hausse_necessaire > gros.hausse_necessaire

    def test_prix_de_revient_apres_achat_complementaire(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        position = suivi.positions["TEST1"]
        simulation = simuler(
            "TEST1", SensOperation.ACHAT, 10, 2_000, moteur_frais, moteur_fiscal, position
        )
        assert simulation.quantite_apres == 20
        assert simulation.prix_revient_apres > Decimal(1_500)

    def test_simulation_de_vente(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        simulation = simuler(
            "TEST1",
            SensOperation.VENTE,
            4,
            1_500,
            moteur_frais,
            moteur_fiscal,
            suivi.positions["TEST1"],
        )
        assert simulation.quantite_apres == 6
        assert simulation.decompte.montant_net < 6_000

    def test_vente_superieure_a_la_position_refusee(
        self,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        with pytest.raises(ErreurValidation, match="seulement sont détenus"):
            simuler(
                "TEST1",
                SensOperation.VENTE,
                20,
                1_500,
                moteur_frais,
                moteur_fiscal,
                suivi.positions["TEST1"],
            )

    def test_impot_pris_en_compte_dans_le_seuil(
        self, moteur_frais: MoteurFrais, configuration: object
    ) -> None:
        """Un régime imposable relève le seuil : l'impôt doit être couvert aussi."""
        from brvm.config.modeles import Configuration

        assert isinstance(configuration, Configuration)
        impose = MoteurFiscal(
            configuration.model_copy(
                update={
                    "fiscalite": configuration.fiscalite.model_copy(
                        update={
                            "plus_values_imposables": True,
                            "plus_values_taux": Decimal("0.30"),
                        }
                    )
                }
            )
        )
        exonere = MoteurFiscal(configuration)
        cout = 1_000_000
        seuil_impose, _ = seuil_rentabilite(100, cout, moteur_frais, impose)
        seuil_exonere, _ = seuil_rentabilite(100, cout, moteur_frais, exonere)
        assert seuil_impose is not None and seuil_exonere is not None
        assert seuil_impose >= seuil_exonere

    def test_detail_lisible(self, moteur_frais: MoteurFrais, moteur_fiscal: MoteurFiscal) -> None:
        detail = simuler(
            "TEST1",
            SensOperation.ACHAT,
            100,
            10_000,
            moteur_frais,
            moteur_fiscal,
            position_vide("TEST1"),
        ).detail()
        assert "Seuil de rentabilité" in detail
        assert "Position après" in detail

    def test_quantite_nulle_refusee(
        self, moteur_frais: MoteurFrais, moteur_fiscal: MoteurFiscal
    ) -> None:
        with pytest.raises(ErreurValidation):
            seuil_rentabilite(0, 1_000, moteur_frais, moteur_fiscal)
