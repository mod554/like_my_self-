"""Garde-fous appliqués aux indicateurs : refus motivés, familles séparées."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.confiance import evaluer_confiance
from brvm.indicators.serie import SerieTechnique


def indicateurs(serie: SerieTechnique, configuration: Configuration) -> Indicateurs:
    return Indicateurs(serie, configuration)


class TestSeuilDeSeancesCotees:
    def test_serie_pleine_produit_des_valeurs(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index for index in range(10)])
        resultat = indicateurs(serie, configuration).moyenne_simple(fenetre=5)
        assert resultat.derniere_valeur is not None
        assert resultat.dernier is not None
        assert resultat.dernier.seances_cotees == 5

    def test_refus_motive_sous_le_seuil(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le seuil configuré est de 60 % : 2 séances cotées sur 5 ne suffisent pas.

        Le report borné fournit bien un nombre ; le système refuse quand même de
        le publier, parce qu'il décrirait l'absence d'échanges, pas le marché.
        """
        serie = fabrique_serie([1000, None, None, None, 1040, None, None, None, 1080])
        resultat = indicateurs(serie, configuration).moyenne_simple(fenetre=5)
        dernier = resultat.dernier
        assert dernier is not None
        assert dernier.valeur is None
        assert dernier.motif_refus is not None
        assert "réellement cotée" in dernier.motif_refus
        assert "60 %" in dernier.motif_refus.replace(" ", " ") or "60%" in dernier.motif_refus

    def test_motif_distinct_pour_une_fenetre_incomplete(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1010, 1020])
        resultat = indicateurs(serie, configuration).moyenne_simple(fenetre=5)
        premier = resultat.points[0]
        assert premier.valeur is None
        assert premier.motif_refus is not None
        assert "incomplète" in premier.motif_refus

    def test_chaque_point_porte_la_qualite_de_sa_fenetre(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, 1020, 1030, 1040])
        resultat = indicateurs(serie, configuration).moyenne_simple(fenetre=5)
        dernier = resultat.dernier
        assert dernier is not None
        assert dernier.seances_cotees == 4
        assert dernier.seances_fenetre == 5
        assert dernier.taux_remplissage == Decimal("0.2")

    def test_comptage_des_refus(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index for index in range(8)])
        resultat = indicateurs(serie, configuration).moyenne_simple(fenetre=5)
        assert resultat.nb_refus() == 4  # les quatre premières fenêtres sont incomplètes


class TestFamillesSeparees:
    def test_atr_ignore_les_seances_sans_transaction(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Sans cette séparation, une valeur qui ne cote pas verrait sa volatilité
        mesurée tendre vers zéro — et ses stops se resserrer d'autant."""
        continue_ = fabrique_serie([1000 + index * 10 for index in range(20)], amplitude=50)
        atr_continu = indicateurs(continue_, configuration).atr(fenetre=5).derniere_valeur

        creuse = fabrique_serie(
            [
                1000,
                None,
                1010,
                None,
                1020,
                None,
                1030,
                None,
                1040,
                None,
                1050,
                None,
                1060,
                None,
                1070,
                None,
                1080,
                None,
                1090,
                None,
            ],
            amplitude=50,
        )
        atr_creux = indicateurs(creuse, configuration).atr(fenetre=5).derniere_valeur

        assert atr_continu is not None and atr_creux is not None
        assert atr_creux > Decimal(50), "l'ATR ne doit pas être écrasé par les trous"

    def test_atr_indique_l_anciennete_de_sa_derniere_mesure(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1010, 1020, 1030, 1040, 1050, 1060, 1070, None, None])
        resultat = indicateurs(serie, configuration).atr(fenetre=3)
        dernier = resultat.dernier
        assert dernier is not None
        assert dernier.valeur is not None
        assert dernier.anciennete == 2

    def test_atr_refuse_sans_assez_de_seances_cotees(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, 1010])
        resultat = indicateurs(serie, configuration).atr(fenetre=14)
        dernier = resultat.dernier
        assert dernier is not None
        assert dernier.valeur is None
        assert dernier.motif_refus is not None
        assert "14 séances réellement cotées" in dernier.motif_refus

    def test_obv_ne_compte_que_les_volumes_echanges(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, 1010, None, 1020], volume=100)
        resultat = indicateurs(serie, configuration).obv()
        # Deux hausses effectives de 100 titres chacune.
        assert resultat.derniere_valeur == Decimal(200)


class TestJeuComplet:
    def test_tous_les_indicateurs_demandes_sont_produits(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + (index * 7) % 40 for index in range(120)])
        resultats = indicateurs(serie, configuration).tous()
        attendus = {"MM20", "MM50", "MM200", "MME20", "RSI14", "MACD", "ATR14", "OBV"}
        assert attendus <= set(resultats)

    def test_moyenne_de_fond_refusee_sur_historique_court(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """200 séances ne s'improvisent pas : le système le dit au lieu d'approximer."""
        serie = fabrique_serie([1000 + index for index in range(60)])
        resultat = indicateurs(serie, configuration).tous()["MM200"]
        assert resultat.derniere_valeur is None

    def test_resume_lisible(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index for index in range(30)])
        resume = indicateurs(serie, configuration).moyenne_simple(fenetre=5).resume()
        assert "MM5" in resume and "séances cotées" in resume and "confiance" in resume

    def test_resume_dit_pourquoi_quand_il_n_y_a_pas_de_valeur(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1010])
        resume = indicateurs(serie, configuration).moyenne_simple(fenetre=20).resume()
        assert "non calculé" in resume


class TestConfiance:
    def test_serie_pleine_et_liquide(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 20, volume=10_000)
        score = evaluer_confiance(serie, configuration)
        assert score.assiduite == Decimal(1)
        assert score.profondeur == Decimal(1)  # 10 000 × 1 000 largement au-dessus
        assert score.niveau == "élevée"

    def test_assiduite_reflete_les_seances_cotees(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, 1010, None], volume=10_000)
        score = evaluer_confiance(serie, configuration)
        assert score.assiduite == Decimal("0.5")
        assert score.seances_cotees == 2 and score.seances_attendues == 4

    def test_faible_profondeur_ecrase_le_score(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le score est un produit : une composante quasi nulle tire tout vers le bas."""
        serie = fabrique_serie([1000] * 20, volume=1)
        score = evaluer_confiance(serie, configuration)
        assert score.assiduite == Decimal(1)
        assert score.profondeur < Decimal("0.01")
        assert score.niveau == "faible"

    def test_fourchette_non_publiee_est_signalee_comme_optimiste(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        score = evaluer_confiance(fabrique_serie([1000] * 20), configuration)
        assert score.fourchette_moyenne is None
        assert any("optimiste" in commentaire for commentaire in score.commentaires)

    def test_fourchette_large_penalise(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie(
            [1000] * 20,
            volume=10_000,
            meilleure_limite_achat=900,
            meilleure_limite_vente=1100,
        )
        score = evaluer_confiance(serie, configuration)
        assert score.fourchette_moyenne == Decimal("0.2")
        assert score.etroitesse == Decimal("0.25")  # référence 0,05 / 0,20

    def test_seuil_franchi_est_commente(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, None, None, 1040], volume=10_000)
        score = evaluer_confiance(serie, configuration)
        assert any("refuseront de se calculer" in c for c in score.commentaires)

    def test_resume_decomposable(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        score = evaluer_confiance(fabrique_serie([1000] * 20, volume=10_000), configuration)
        resume = score.resume()
        assert "assiduité" in resume and "profondeur" in resume and "étroitesse" in resume
