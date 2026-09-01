"""Suivi des lignes : PMP, FIFO, opérations sur titres, cessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from brvm.domain.enums import MethodeValorisation, SensOperation, TypeOst
from brvm.domain.modeles import OperationSurTitre, Transaction
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.positions import mois_ecoules, suivre, suivre_les_deux
from brvm.utils.erreurs import ErreurValidation


def ost_division(numerateur: int, denominateur: int, jour: date) -> OperationSurTitre:
    return OperationSurTitre(
        identifiant=f"OST-{jour}",
        ticker="TEST1",
        type_ost=TypeOst.DIVISION,
        date_ex=jour,
        ratio_numerateur=numerateur,
        ratio_denominateur=denominateur,
        source="fixture",
    )


class TestPmp:
    def test_achats_successifs_moyennent_le_prix(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.PMP)
        position = suivi.positions["TEST1"]
        assert position.quantite == 20
        assert position.cout_total == 30_000
        assert position.prix_revient_unitaire == Decimal(1_500)

    def test_vente_ne_change_pas_le_prix_de_revient(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
            fabrique_transaction(
                "T3",
                quantite=5,
                cours=3_000,
                jour=date(2026, 3, 4),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.PMP)
        assert suivi.positions["TEST1"].prix_revient_unitaire == Decimal(1_500)
        assert suivi.positions["TEST1"].quantite == 15

    def test_plus_value_realisee(self, fabrique_transaction: Callable[..., Transaction]) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction(
                "T2",
                quantite=4,
                cours=1_500,
                jour=date(2026, 3, 3),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.PMP)
        cession = suivi.cessions[0]
        assert cession.cout_de_revient == 4_000
        assert cession.produit_net == 6_000
        assert cession.plus_value_brute == 2_000

    def test_la_duree_de_detention_n_existe_pas_en_pmp(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """Les titres ont perdu leur identité : renvoyer une durée serait l'inventer."""
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction(
                "T2",
                quantite=5,
                cours=1_500,
                jour=date(2027, 3, 3),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.PMP)
        assert suivi.cessions[0].duree_detention_mois is None
        assert suivi.cessions[0].date_acquisition is None

    def test_solde_total_laisse_une_ligne_a_zero(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """La dernière cession emporte tout le coût restant, sans résidu d'arrondi."""
        transactions = [
            fabrique_transaction("T1", quantite=3, cours=1_000),
            fabrique_transaction("T2", quantite=3, cours=1_001, jour=date(2026, 3, 3)),
            fabrique_transaction(
                "T3",
                quantite=6,
                cours=1_200,
                jour=date(2026, 3, 4),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.PMP)
        assert suivi.positions["TEST1"].quantite == 0
        assert suivi.positions["TEST1"].cout_total == 0
        assert sum(c.cout_de_revient for c in suivi.cessions) == 6_003


class TestFifo:
    def test_lots_conserves(self, fabrique_transaction: Callable[..., Transaction]) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.FIFO)
        lots = suivi.positions["TEST1"].lots
        assert [lot.quantite for lot in lots] == [10, 10]
        assert [lot.cout_unitaire for lot in lots] == [Decimal(1_000), Decimal(2_000)]

    def test_vente_consomme_les_lots_les_plus_anciens(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
            fabrique_transaction(
                "T3",
                quantite=6,
                cours=3_000,
                jour=date(2026, 3, 4),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.FIFO)
        assert len(suivi.cessions) == 1
        assert suivi.cessions[0].cout_de_revient == 6_000  # 6 titres du lot à 1 000
        lots = suivi.positions["TEST1"].lots
        assert [lot.quantite for lot in lots] == [4, 10]

    def test_une_cession_par_lot_traverse(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """Une vente qui traverse deux lots donne deux cessions : c'est ce que
        réclame un calcul de plus-value adossé à la durée de détention."""
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 6, 1)),
            fabrique_transaction(
                "T3",
                quantite=15,
                cours=3_000,
                jour=date(2027, 3, 2),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.FIFO)
        assert len(suivi.cessions) == 2
        assert [c.quantite for c in suivi.cessions] == [10, 5]
        assert suivi.cessions[0].duree_detention_mois == 12
        assert suivi.cessions[1].duree_detention_mois == 9

    def test_le_produit_est_reparti_sans_perte(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """La somme des cessions doit rendre exactement le montant encaissé."""
        transactions = [
            fabrique_transaction("T1", quantite=3, cours=1_000),
            fabrique_transaction("T2", quantite=4, cours=1_000, jour=date(2026, 3, 3)),
            fabrique_transaction(
                "T3",
                quantite=7,
                cours=1_001,
                jour=date(2026, 3, 4),
                sens=SensOperation.VENTE,
            ),
        ]
        suivi = suivre(transactions, methode=MethodeValorisation.FIFO)
        assert sum(c.produit_net for c in suivi.cessions) == 7 * 1_001


class TestDivergenceDesMethodes:
    def test_meme_prix_de_revient_tant_qu_aucune_vente(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
        ]
        suivis = suivre_les_deux(transactions)
        pmp = suivis[MethodeValorisation.PMP].positions["TEST1"]
        fifo = suivis[MethodeValorisation.FIFO].positions["TEST1"]
        assert pmp.cout_total == fifo.cout_total
        assert pmp.prix_revient_unitaire == fifo.prix_revient_unitaire

    def test_les_plus_values_divergent_apres_une_vente(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """FIFO cède les titres les moins chers d'abord : la plus-value réalisée
        est plus élevée, et l'impôt éventuel aussi."""
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
            fabrique_transaction(
                "T3",
                quantite=10,
                cours=2_500,
                jour=date(2026, 3, 4),
                sens=SensOperation.VENTE,
            ),
        ]
        suivis = suivre_les_deux(transactions)
        pmp = suivis[MethodeValorisation.PMP].plus_values_realisees()
        fifo = suivis[MethodeValorisation.FIFO].plus_values_realisees()
        assert fifo > pmp
        assert pmp == 25_000 - 15_000
        assert fifo == 25_000 - 10_000


class TestOperationsSurTitres:
    def test_division_multiplie_les_titres_sans_changer_le_cout(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """Une division ne fait rien débourser : le coût total est inchangé."""
        transactions = [fabrique_transaction("T1", quantite=10, cours=1_000)]
        suivi = suivre(
            transactions,
            [ost_division(2, 1, date(2026, 3, 3))],
            methode=MethodeValorisation.PMP,
        )
        position = suivi.positions["TEST1"]
        assert position.quantite == 20
        assert position.cout_total == 10_000
        assert position.prix_revient_unitaire == Decimal(500)

    def test_division_ajuste_chaque_lot_en_fifo(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=2_000, jour=date(2026, 3, 3)),
        ]
        suivi = suivre(
            transactions,
            [ost_division(2, 1, date(2026, 3, 4))],
            methode=MethodeValorisation.FIFO,
        )
        lots = suivi.positions["TEST1"].lots
        assert [lot.quantite for lot in lots] == [20, 20]
        assert [lot.cout_unitaire for lot in lots] == [Decimal(500), Decimal(1_000)]

    def test_regroupement_reduit_les_titres(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [fabrique_transaction("T1", quantite=100, cours=100)]
        regroupement = OperationSurTitre(
            identifiant="R1",
            ticker="TEST1",
            type_ost=TypeOst.REGROUPEMENT,
            date_ex=date(2026, 3, 3),
            ratio_numerateur=1,
            ratio_denominateur=10,
            source="fixture",
        )
        suivi = suivre(transactions, [regroupement])
        assert suivi.positions["TEST1"].quantite == 10
        assert suivi.positions["TEST1"].cout_total == 10_000

    def test_rompu_signale_et_non_invente(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """3 titres pour 2 anciens sur une ligne de 5 donne 7,5 titres."""
        transactions = [fabrique_transaction("T1", quantite=5, cours=1_000)]
        suivi = suivre(transactions, [ost_division(3, 2, date(2026, 3, 3))])
        assert suivi.positions["TEST1"].quantite == 7
        assert any("rompu" in message for message in suivi.avertissements)

    def test_ost_sur_une_ligne_non_detenue_est_ignoree(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        suivi = suivre([], [ost_division(2, 1, date(2026, 3, 3))])
        assert suivi.positions == {}

    def test_ost_appliquee_avant_les_transactions_du_meme_jour(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """Un détachement intervient à l'ouverture, avant les échanges de la séance."""
        transactions = [
            fabrique_transaction("T1", quantite=10, cours=1_000),
            fabrique_transaction("T2", quantite=10, cours=500, jour=date(2026, 3, 3)),
        ]
        suivi = suivre(transactions, [ost_division(2, 1, date(2026, 3, 3))])
        # 10 titres → 20 après division, puis 10 achetés : 30 au total.
        assert suivi.positions["TEST1"].quantite == 30


class TestFraisEtErreurs:
    def test_les_frais_saisis_priment_sur_le_bareme(
        self, moteur_frais: MoteurFrais, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        """L'avis d'opéré fait foi, pas le modèle."""
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 10, 1_000)
        reels = tuple(ligne.model_copy(update={"montant": 1}) for ligne in decompte.lignes)
        transaction = fabrique_transaction("T1", quantite=10, cours=1_000, frais=reels)
        suivi = suivre([transaction], moteur=moteur_frais)
        assert suivi.positions["TEST1"].cout_total == 10_000 + len(reels)

    def test_le_bareme_supplee_une_transaction_sans_frais(
        self, moteur_frais: MoteurFrais, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transaction = fabrique_transaction("T1", quantite=10, cours=1_000)
        suivi = suivre([transaction], moteur=moteur_frais)
        attendu = moteur_frais.calculer(SensOperation.ACHAT, 10, 1_000).montant_net
        assert suivi.positions["TEST1"].cout_total == attendu

    def test_vente_a_decouvert_refusee(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction("T1", quantite=5, cours=1_000),
            fabrique_transaction(
                "T2",
                quantite=10,
                cours=1_200,
                jour=date(2026, 3, 3),
                sens=SensOperation.VENTE,
            ),
        ]
        with pytest.raises(ErreurValidation, match="alors que 5 seulement"):
            suivre(transactions)

    def test_transactions_desordonnees_sont_rejouees_dans_l_ordre(
        self, fabrique_transaction: Callable[..., Transaction]
    ) -> None:
        transactions = [
            fabrique_transaction(
                "T2",
                quantite=5,
                cours=2_000,
                jour=date(2026, 3, 3),
                sens=SensOperation.VENTE,
            ),
            fabrique_transaction("T1", quantite=10, cours=1_000),
        ]
        suivi = suivre(transactions)
        assert suivi.positions["TEST1"].quantite == 5


class TestDurees:
    @pytest.mark.parametrize(
        ("debut", "fin", "attendu"),
        [
            (date(2026, 1, 15), date(2026, 1, 15), 0),
            (date(2026, 1, 15), date(2026, 2, 14), 0),
            (date(2026, 1, 15), date(2026, 2, 15), 1),
            (date(2026, 1, 15), date(2027, 1, 15), 12),
            (date(2026, 1, 31), date(2026, 3, 1), 1),
        ],
    )
    def test_mois_entiers(self, debut: date, fin: date, attendu: int) -> None:
        assert mois_ecoules(debut, fin) == attendu

    def test_duree_de_la_position(self, fabrique_transaction: Callable[..., Transaction]) -> None:
        suivi = suivre([fabrique_transaction("T1", jour=date(2026, 1, 15))])
        assert suivi.positions["TEST1"].duree_detention_mois(date(2026, 7, 15)) == 6
