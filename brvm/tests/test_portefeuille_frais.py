"""Moteur de frais : décompte ligne à ligne, arrondis, minimums, récurrents."""

from __future__ import annotations

from decimal import Decimal

import pytest

from brvm.config.modeles import ConfigFraisPeriodique, Configuration
from brvm.domain.enums import BaseFrais, Periodicite, SensOperation
from brvm.portfolio.frais import LIBELLE_COMPLEMENT, MoteurFrais, cumuler
from brvm.utils.erreurs import ErreurValidation


class TestDecompte:
    """Le barème de test : courtage 1 % (minimum 1 000), marché 0,2 %, TVA 18 %,
    puis 500 XOF de frais fixes."""

    def test_lignes_dans_l_ordre_du_bareme(self, moteur_frais: MoteurFrais) -> None:
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        assert [ligne.libelle for ligne in decompte.lignes] == [
            "Commission de courtage SGI",
            "Commission entreprise de marché",
            "TVA sur commissions",
            "Frais fixes d'avis d'opéré",
        ]

    def test_montants_calcules(self, moteur_frais: MoteurFrais) -> None:
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        montants = {ligne.libelle: ligne.montant for ligne in decompte.lignes}
        assert montants["Commission de courtage SGI"] == 10_000  # 1 % de 1 000 000
        assert montants["Commission entreprise de marché"] == 2_000  # 0,2 %
        assert montants["TVA sur commissions"] == 2_160  # 18 % de 12 000
        assert montants["Frais fixes d'avis d'opéré"] == 500
        assert decompte.total == 14_660

    def test_achat_ajoute_les_frais_vente_les_retranche(self, moteur_frais: MoteurFrais) -> None:
        achat = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        vente = moteur_frais.calculer(SensOperation.VENTE, 100, 10_000)
        assert achat.montant_net == 1_000_000 + achat.total
        assert vente.montant_net == 1_000_000 - vente.total

    def test_prix_de_revient_superieur_au_cours(self, moteur_frais: MoteurFrais) -> None:
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        assert decompte.prix_revient_unitaire > Decimal(10_000)

    def test_prix_de_revient_refuse_sur_une_vente(self, moteur_frais: MoteurFrais) -> None:
        """La notion n'a pas de sens : c'est un produit net, pas un coût."""
        decompte = moteur_frais.calculer(SensOperation.VENTE, 100, 10_000)
        with pytest.raises(ErreurValidation, match="ne se calcule pas sur une vente"):
            _ = decompte.prix_revient_unitaire
        assert decompte.montant_net_unitaire < Decimal(10_000)

    def test_taux_effectif(self, moteur_frais: MoteurFrais) -> None:
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        assert decompte.taux_effectif == Decimal("14660") / Decimal("1000000")

    def test_detail_lisible(self, moteur_frais: MoteurFrais) -> None:
        detail = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000).detail()
        assert "Montant brut" in detail
        assert "Total des frais" in detail
        assert "Prix de revient unitaire" in detail


class TestAssietteDeLaTva:
    def test_la_tva_porte_sur_les_commissions_qui_la_precedent(
        self, moteur_frais: MoteurFrais
    ) -> None:
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        tva = next(x for x in decompte.lignes if x.libelle == "TVA sur commissions")
        assert tva.assiette == 12_000  # courtage + commission marché

    def test_une_ligne_posterieure_echappe_a_la_tva(self, moteur_frais: MoteurFrais) -> None:
        """Les frais fixes du barème de test portent l'ordre 4, la TVA l'ordre 3 :
        ils ne sont donc pas taxés. C'est l'ordre déclaré qui décide."""
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
        tva = next(x for x in decompte.lignes if x.libelle == "TVA sur commissions")
        fixe = next(x for x in decompte.lignes if x.libelle.startswith("Frais fixes"))
        assert tva.assiette == 12_000
        assert tva.assiette + fixe.montant == 12_500

    def test_une_tva_ne_taxe_pas_une_autre_tva(self, configuration: Configuration) -> None:
        """Deux lignes assises sur le total des commissions ne se taxent pas l'une
        l'autre : sans cette règle, l'ordre des lignes changerait le total."""
        lignes = list(configuration.frais.lignes)
        seconde_tva = lignes[2].model_copy(
            update={"libelle": "Seconde taxe", "ordre": 5, "taux": Decimal("0.10")}
        )
        bareme = configuration.frais.model_copy(update={"lignes": (*lignes, seconde_tva)})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        decompte = moteur.calculer(SensOperation.ACHAT, 100, 10_000)
        premiere = next(x for x in decompte.lignes if x.libelle == "TVA sur commissions")
        seconde = next(x for x in decompte.lignes if x.libelle == "Seconde taxe")
        # Assiette = courtage 10 000 + marché 2 000 + forfait 500, sans la
        # première TVA (2 160) qui la précède pourtant.
        assert seconde.assiette == 12_500
        assert premiere.montant not in (0, seconde.assiette - 12_500)


class TestArrondis:
    def test_chaque_ligne_est_arrondie_avant_la_somme(self, configuration: Configuration) -> None:
        """C'est ainsi qu'un avis d'opéré est établi. Arrondir la somme donnerait
        un total différent de celui facturé."""
        ligne = configuration.frais.lignes[0].model_copy(
            update={"taux": Decimal("0.005"), "minimum_perception": None}
        )
        bareme = configuration.frais.model_copy(update={"lignes": (ligne,)})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        # 0,5 % de 101 = 0,505 → arrondi à 1 sur la ligne.
        decompte = moteur.calculer(SensOperation.ACHAT, 1, 101)
        assert decompte.lignes[0].montant == 1
        assert decompte.total == 1


class TestMinimumsEtPlafonds:
    def test_minimum_de_perception_de_ligne(self, moteur_frais: MoteurFrais) -> None:
        """1 % de 10 000 vaut 100, sous le minimum de 1 000 du barème de test."""
        decompte = moteur_frais.calculer(SensOperation.ACHAT, 1, 10_000)
        courtage = decompte.lignes[0]
        assert courtage.montant == 1_000

    def test_plafond_de_ligne(self, configuration: Configuration) -> None:
        ligne = configuration.frais.lignes[0].model_copy(
            update={"minimum_perception": None, "maximum_perception": 5_000}
        )
        bareme = configuration.frais.model_copy(update={"lignes": (ligne,)})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        decompte = moteur.calculer(SensOperation.ACHAT, 1000, 10_000)
        assert decompte.lignes[0].montant == 5_000

    def test_minimum_global_ajoute_une_ligne_nommee(self, configuration: Configuration) -> None:
        """Le complément est une ligne visible : la somme des lignes doit toujours
        faire le total."""
        bareme = configuration.frais.model_copy(update={"minimum_perception_global": 50_000})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        decompte = moteur.calculer(SensOperation.ACHAT, 100, 10_000)
        assert decompte.total == 50_000
        assert decompte.lignes[-1].libelle == LIBELLE_COMPLEMENT
        assert sum(ligne.montant for ligne in decompte.lignes) == decompte.total

    def test_minimum_global_non_atteint_n_ajoute_rien(self, configuration: Configuration) -> None:
        bareme = configuration.frais.model_copy(update={"minimum_perception_global": 1_000})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        decompte = moteur.calculer(SensOperation.ACHAT, 100, 10_000)
        assert all(ligne.libelle != LIBELLE_COMPLEMENT for ligne in decompte.lignes)


class TestApplicabilite:
    def test_ligne_reservee_a_un_sens(self, configuration: Configuration) -> None:
        lignes = list(configuration.frais.lignes)
        lignes[0] = lignes[0].model_copy(update={"applicable_a": "VENTE"})
        bareme = configuration.frais.model_copy(update={"lignes": tuple(lignes)})
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        achat = moteur.calculer(SensOperation.ACHAT, 100, 10_000)
        vente = moteur.calculer(SensOperation.VENTE, 100, 10_000)
        libelles_achat = {ligne.libelle for ligne in achat.lignes}
        assert "Commission de courtage SGI" not in libelles_achat
        assert "Commission de courtage SGI" in {ligne.libelle for ligne in vente.lignes}


class TestEntreesInvalides:
    @pytest.mark.parametrize("quantite", [0, -5])
    def test_quantite_invalide(self, moteur_frais: MoteurFrais, quantite: int) -> None:
        with pytest.raises(ErreurValidation, match="quantité"):
            moteur_frais.calculer(SensOperation.ACHAT, quantite, 1_000)

    @pytest.mark.parametrize("cours", [0, -100])
    def test_cours_invalide(self, moteur_frais: MoteurFrais, cours: int) -> None:
        with pytest.raises(ErreurValidation, match="cours"):
            moteur_frais.calculer(SensOperation.ACHAT, 10, cours)


class TestFraisRecurrents:
    def test_forfait_annualise_selon_la_periodicite(self, configuration: Configuration) -> None:
        bareme = configuration.frais.model_copy(
            update={
                "periodiques": (
                    ConfigFraisPeriodique(
                        libelle="Tenue de compte",
                        base_calcul="FORFAIT",
                        periodicite=Periodicite.TRIMESTRIELLE,
                        montant_fixe=2_500,
                    ),
                )
            }
        )
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        assert moteur.cout_annuel_detention(500_000) == 10_000

    def test_taux_sur_encours(self, configuration: Configuration) -> None:
        bareme = configuration.frais.model_copy(
            update={
                "periodiques": (
                    ConfigFraisPeriodique(
                        libelle="Droits de garde",
                        base_calcul="ENCOURS",
                        periodicite=Periodicite.ANNUELLE,
                        taux=Decimal("0.0025"),
                    ),
                )
            }
        )
        moteur = MoteurFrais(configuration.model_copy(update={"frais": bareme}))
        assert moteur.cout_annuel_detention(500_000) == 1_250

    def test_aucun_frais_recurrent_declare(self, moteur_frais: MoteurFrais) -> None:
        assert moteur_frais.cout_annuel_detention(500_000) == 0
        assert moteur_frais.frais_periodiques_annuels(500_000) == ()


def test_cumul_de_plusieurs_operations(moteur_frais: MoteurFrais) -> None:
    decomptes = [
        moteur_frais.calculer(SensOperation.ACHAT, 10, 1_000),
        moteur_frais.calculer(SensOperation.VENTE, 10, 1_100),
    ]
    assert cumuler(decomptes) == sum(decompte.total for decompte in decomptes)


def test_ligne_forfaitaire_sans_assiette(moteur_frais: MoteurFrais) -> None:
    decompte = moteur_frais.calculer(SensOperation.ACHAT, 100, 10_000)
    fixe = next(x for x in decompte.lignes if x.base_calcul is BaseFrais.MONTANT_FIXE)
    assert fixe.assiette == 0 and fixe.taux is None
