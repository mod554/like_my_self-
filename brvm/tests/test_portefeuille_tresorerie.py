"""Compte espèces : le solde, et les cas où il n'existe pas.

Le point vérifié ici n'est pas qu'une addition tombe juste, mais que le système
distingue **un solde nul** d'**un solde inconnu**. Sans apport déclaré, la somme
des mouvements mesure l'argent dépensé, pas la trésorerie disponible : l'afficher
comme un solde serait faux.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from brvm.domain.enums import SensOperation, TypeFluxEspece
from brvm.domain.modeles import FluxEspece, Transaction
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.positions import montant_net_effectif
from brvm.portfolio.tresorerie import MOTIF_SANS_APPORT, calculer_tresorerie


def flux(
    identifiant: str,
    type_flux: TypeFluxEspece,
    brut: int,
    *,
    retenue: int = 0,
    frais: int = 0,
    ticker: str | None = None,
) -> FluxEspece:
    return FluxEspece(
        identifiant=identifiant,
        date_flux=date(2026, 3, 2),
        type_flux=type_flux,
        ticker=ticker,
        montant_brut=brut,
        retenue_fiscale=retenue,
        frais=frais,
        source="test",
    )


class TestSoldeInconnu:
    def test_sans_apport_le_solde_n_est_pas_calcule(self) -> None:
        tresorerie = calculer_tresorerie([], [], None)
        assert tresorerie.solde is None
        assert tresorerie.mesurable is False
        assert tresorerie.motif_indisponible == MOTIF_SANS_APPORT

    def test_des_achats_sans_apport_ne_font_pas_un_solde_negatif(
        self, fabrique_transaction: Callable[..., Transaction], moteur_frais: MoteurFrais
    ) -> None:
        """Le nombre serait l'argent dépensé, pas la trésorerie. On s'abstient."""
        achats = [fabrique_transaction("T1", quantite=10, cours=1_000)]
        tresorerie = calculer_tresorerie(achats, [], moteur_frais)
        assert tresorerie.solde is None
        assert tresorerie.decaissements_achats > 0

    def test_un_dividende_seul_ne_suffit_pas(self) -> None:
        """Encaisser un dividende ne dit pas avec quoi les titres ont été payés."""
        mouvements = [flux("F1", TypeFluxEspece.DIVIDENDE, 12_000, ticker="TEST1")]
        assert calculer_tresorerie([], mouvements, None).solde is None

    def test_le_motif_dit_quoi_faire(self) -> None:
        motif = calculer_tresorerie([], [], None).motif_indisponible or ""
        assert "APPORT" in motif

    def test_le_resume_annonce_l_indisponibilite(self) -> None:
        assert "non calculables" in calculer_tresorerie([], [], None).resume()


class TestSoldeConnu:
    def test_un_apport_seul_est_le_solde(self) -> None:
        tresorerie = calculer_tresorerie([], [flux("F1", TypeFluxEspece.APPORT, 5_000_000)], None)
        assert tresorerie.solde == 5_000_000

    def test_tous_les_postes_entrent_dans_le_solde(self) -> None:
        mouvements = [
            flux("F1", TypeFluxEspece.APPORT, 5_000_000),
            flux("F2", TypeFluxEspece.RETRAIT, 200_000),
            flux("F3", TypeFluxEspece.DIVIDENDE, 100_000, retenue=15_000, ticker="TEST1"),
            flux("F4", TypeFluxEspece.FRAIS_GARDE, 12_000),
            flux("F5", TypeFluxEspece.AUTRE, 3_000),
        ]
        tresorerie = calculer_tresorerie([], mouvements, None)
        # 5 000 000 − 200 000 + (100 000 − 15 000) − 12 000 + 3 000
        assert tresorerie.solde == 4_876_000
        assert tresorerie.dividendes_nets == 85_000

    def test_un_achat_diminue_le_solde_de_son_decaissement_reel(
        self, fabrique_transaction: Callable[..., Transaction], moteur_frais: MoteurFrais
    ) -> None:
        """Frais compris : c'est ce qui sort du compte, pas le montant brut."""
        achat = fabrique_transaction("T1", quantite=10, cours=28_400)
        tresorerie = calculer_tresorerie(
            [achat], [flux("F1", TypeFluxEspece.APPORT, 5_000_000)], moteur_frais
        )
        decaisse = montant_net_effectif(achat, moteur_frais)
        assert decaisse > 10 * 28_400, "les frais s'ajoutent au brut"
        assert tresorerie.solde == 5_000_000 - decaisse

    def test_une_vente_augmente_le_solde_de_son_encaissement_reel(
        self, fabrique_transaction: Callable[..., Transaction], moteur_frais: MoteurFrais
    ) -> None:
        vente = fabrique_transaction("T2", sens=SensOperation.VENTE, quantite=10, cours=30_000)
        tresorerie = calculer_tresorerie(
            [vente], [flux("F1", TypeFluxEspece.APPORT, 1_000_000)], moteur_frais
        )
        encaisse = montant_net_effectif(vente, moteur_frais)
        assert encaisse < 10 * 30_000, "les frais se retranchent du brut"
        assert tresorerie.solde == 1_000_000 + encaisse

    def test_acheter_puis_tout_vendre_rend_les_especes(
        self, fabrique_transaction: Callable[..., Transaction], moteur_frais: MoteurFrais
    ) -> None:
        """Le cas qui rendait toute mesure de performance impossible : un
        portefeuille entièrement soldé ne vaut pas zéro, son argent est en
        espèces."""
        operations = [
            fabrique_transaction("T1", quantite=10, cours=28_400),
            fabrique_transaction("T2", sens=SensOperation.VENTE, quantite=10, cours=28_400),
        ]
        tresorerie = calculer_tresorerie(
            operations, [flux("F1", TypeFluxEspece.APPORT, 5_000_000)], moteur_frais
        )
        assert tresorerie.solde is not None
        # Aller-retour au même cours : on perd exactement les frais des deux côtés.
        frais_aller_retour = sum(
            montant_net_effectif(op, moteur_frais) * (1 if op.sens is SensOperation.ACHAT else -1)
            for op in operations
        )
        assert tresorerie.solde == 5_000_000 - frais_aller_retour
        assert tresorerie.solde < 5_000_000, "l'aller-retour coûte ses frais"

    def test_le_resume_detaille_chaque_poste(self) -> None:
        """Un solde juste dont on ne peut pas expliquer la composition ne se
        vérifie pas contre un relevé de compte."""
        mouvements = [
            flux("F1", TypeFluxEspece.APPORT, 5_000_000),
            flux("F2", TypeFluxEspece.FRAIS_GARDE, 12_000),
        ]
        resume = calculer_tresorerie([], mouvements, None).resume()
        for poste in ("Apports", "Retraits", "Dividendes", "Frais de garde", "Solde espèces"):
            assert poste in resume


class TestActifTotal:
    def test_titres_plus_especes(
        self,
        fabrique_transaction: Callable[..., Transaction],
        moteur_frais: MoteurFrais,
        moteur_fiscal: object,
        fabrique_cotation: Callable[..., object],
    ) -> None:
        from brvm.portfolio.positions import suivre
        from brvm.portfolio.valorisation import valoriser

        transactions = [fabrique_transaction("T1", quantite=10, cours=1_000)]
        suivi = suivre(transactions)
        portefeuille = valoriser(
            suivi,
            {"TEST1": fabrique_cotation(cloture=1_200)},  # type: ignore[dict-item]
            moteur_frais,
            moteur_fiscal,  # type: ignore[arg-type]
            flux=[flux("F1", TypeFluxEspece.APPORT, 5_000_000)],
            transactions=transactions,
        )
        assert portefeuille.tresorerie.mesurable
        assert portefeuille.actif_total == (
            portefeuille.valeur_totale + (portefeuille.tresorerie.solde or 0)
        )

    def test_sans_apport_l_actif_total_reste_inconnu(
        self,
        fabrique_transaction: Callable[..., Transaction],
        moteur_frais: MoteurFrais,
        moteur_fiscal: object,
        fabrique_cotation: Callable[..., object],
    ) -> None:
        from brvm.portfolio.positions import suivre
        from brvm.portfolio.valorisation import valoriser

        transactions = [fabrique_transaction("T1", quantite=10, cours=1_000)]
        portefeuille = valoriser(
            suivre(transactions),
            {"TEST1": fabrique_cotation(cloture=1_200)},  # type: ignore[dict-item]
            moteur_frais,
            moteur_fiscal,  # type: ignore[arg-type]
            transactions=transactions,
        )
        assert portefeuille.actif_total is None
        assert "non calculables" in portefeuille.resume(
            __import__("datetime").datetime(2026, 3, 2, tzinfo=__import__("datetime").UTC)
        )
