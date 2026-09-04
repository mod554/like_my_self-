"""Classement : les portes annulent, les fondamentaux ne se devinent pas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from brvm.config.modeles import ConfigHorizon, Configuration
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import SerieTechnique
from brvm.market.analyse import AnalyseValeur, analyser
from brvm.market.criteres import Critere
from brvm.market.fondamentaux import Fondamentaux
from brvm.market.horizons import (
    classer,
    classer_tous,
    criteres_fondamentaux_manquants,
    resume_couverture,
)


def analyse_de(
    serie: SerieTechnique,
    configuration: Configuration,
    ticker: str = "TEST1",
    exercices: tuple[Fondamentaux, ...] = (),
) -> AnalyseValeur:
    return analyser(
        ticker=ticker,
        serie=serie,
        indicateurs=Indicateurs(serie, configuration),
        configuration=configuration,
        exercices=exercices,
        annee_courante=2026,
    )


def fabriquer_analyse(
    ticker: str,
    notes: dict[str, str],
    confiance: str = "0.9",
    cours: int = 1000,
    taille_tenable: int = 1000,
    exercice: Fondamentaux | None = None,
    seances_cotees: int = 90,
    profondeur: str = "1",
    etroitesse: str = "1",
) -> AnalyseValeur:
    """Analyse entièrement synthétique : le classement se teste sans passer par
    le calcul des indicateurs, dont les tests sont ailleurs."""
    return AnalyseValeur(
        ticker=ticker,
        instrument=None,
        cours=cours,
        date_cours=date(2026, 3, 2),
        confiance=Decimal(confiance),
        niveau_confiance="test",
        seances_cotees=seances_cotees,
        seances_attendues=100,
        taille_tenable=taille_tenable,
        motif_taille=None,
        profondeur=Decimal(profondeur),
        etroitesse=Decimal(etroitesse),
        criteres={
            nom: Critere(nom=nom, libelle=nom, valeur=Decimal(note), note=Decimal(note))
            for nom, note in notes.items()
        },
        exercice=exercice,
    )


PROFIL_TECHNIQUE = ConfigHorizon(
    libelle="Test court",
    description="Profil de test",
    couverture_minimale=Decimal("0.6"),
    confiance_minimale=Decimal("0.25"),
    exige_fondamentaux=False,
    poids={"momentum": Decimal(3), "tendance": Decimal(2), "volume": Decimal(1)},
)


class TestOrdre:
    def test_classe_par_score_decroissant(self, configuration: Configuration) -> None:
        analyses = [
            fabriquer_analyse("BAS", {"momentum": "0.1", "tendance": "0.1", "volume": "0.5"}),
            fabriquer_analyse("HAUT", {"momentum": "0.9", "tendance": "0.9", "volume": "0.9"}),
        ]
        classement = classer(analyses, PROFIL_TECHNIQUE, "court", configuration)
        assert [rang.ticker for rang in classement.classes] == ["HAUT", "BAS"]

    def test_egalite_departagee_alphabetiquement_pour_rester_stable(
        self, configuration: Configuration
    ) -> None:
        """Deux valeurs à score égal ne doivent pas changer de place d'une
        exécution à l'autre."""
        notes = {"momentum": "0.5", "tendance": "0.5", "volume": "0.5"}
        analyses = [fabriquer_analyse(t, notes) for t in ("ZZZ", "AAA", "MMM")]
        classement = classer(analyses, PROFIL_TECHNIQUE, "court", configuration)
        assert [rang.ticker for rang in classement.classes] == ["AAA", "MMM", "ZZZ"]

    def test_couverture_cote_compte_classees_et_ecartees(
        self, configuration: Configuration
    ) -> None:
        analyses = [
            fabriquer_analyse("OK", {"momentum": "0.5", "tendance": "0.5", "volume": "0.5"}),
            fabriquer_analyse("TROUE", {"momentum": "0.9"}, confiance="0.05"),
        ]
        classement = classer(analyses, PROFIL_TECHNIQUE, "court", configuration)
        assert classement.couverture_cote == "1/2"


class TestPorteConfiance:
    def test_sous_le_seuil_la_valeur_n_est_pas_classee_du_tout(
        self, configuration: Configuration
    ) -> None:
        """Une valeur au momentum superbe qui cote trois fois par mois n'est pas
        une demi-occasion : elle n'est pas jouable."""
        analyse = fabriquer_analyse(
            "RARE", {"momentum": "1", "tendance": "1", "volume": "1"}, confiance="0.10"
        )
        classement = classer([analyse], PROFIL_TECHNIQUE, "court", configuration)
        assert classement.classes == ()
        assert len(classement.ecartes) == 1
        motif = classement.ecartes[0].score.motif_absent or ""
        assert "Confiance" in motif

    def test_le_motif_nomme_la_composante_qui_borne_vraiment(
        self, configuration: Configuration
    ) -> None:
        """La confiance est un produit de trois facteurs. Attribuer d'office une
        confiance faible à des trous dans la série enverrait chercher au mauvais
        endroit une valeur qui cote toutes les séances mais n'échange rien."""
        notes = {"momentum": "1", "tendance": "1", "volume": "1"}
        peu_profonde = fabriquer_analyse(
            "PLATE", notes, confiance="0.10", seances_cotees=100, profondeur="0.10"
        )
        trouee = fabriquer_analyse(
            "TROUEE", notes, confiance="0.10", seances_cotees=10, profondeur="1"
        )
        classement = classer([peu_profonde, trouee], PROFIL_TECHNIQUE, "court", configuration)
        motifs = {rang.ticker: rang.score.motif_absent or "" for rang in classement.ecartes}
        assert "profondeur" in motifs["PLATE"]
        assert "assiduité" in motifs["TROUEE"]
        assert "10 séance(s) cotée(s) sur 100" in motifs["TROUEE"]

    def test_confiance_basse_mais_admise_ecrase_le_score(
        self, configuration: Configuration
    ) -> None:
        notes = {"momentum": "1", "tendance": "1", "volume": "1"}
        fort = fabriquer_analyse("FORT", notes, confiance="0.95")
        faible = fabriquer_analyse("FAIBLE", notes, confiance="0.30")
        classement = classer([fort, faible], PROFIL_TECHNIQUE, "court", configuration)
        assert [rang.ticker for rang in classement.classes] == ["FORT", "FAIBLE"]
        assert classement.classes[1].valeur is not None
        assert classement.classes[1].valeur < classement.classes[0].valeur  # type: ignore[operator]


class TestPorteLiquidite:
    def test_position_sous_le_minimum_de_ligne_n_est_pas_classee(
        self, configuration: Configuration
    ) -> None:
        """Ce n'est pas une question de qualité : la ligne ne peut pas exister."""
        minimum = configuration.allocation.montant_minimum_ligne
        analyse = fabriquer_analyse(
            "ETROIT",
            {"momentum": "1", "tendance": "1", "volume": "1"},
            cours=100,
            taille_tenable=(minimum // 100) - 1,
        )
        classement = classer([analyse], PROFIL_TECHNIQUE, "court", configuration)
        assert classement.classes == ()
        motif = classement.ecartes[0].score.motif_absent or ""
        assert "Capacité d'accueil" in motif

    def test_sans_cours_cote_aucune_capacite_d_accueil(self, configuration: Configuration) -> None:
        analyse = fabriquer_analyse(
            "MUET",
            {"momentum": "1", "tendance": "1", "volume": "1"},
            cours=None,  # type: ignore[arg-type]
        )
        classement = classer([analyse], PROFIL_TECHNIQUE, "court", configuration)
        assert classement.classes == ()
        assert "cours" in (classement.ecartes[0].score.motif_absent or "")


class TestCouverture:
    def test_sous_la_couverture_minimale_le_score_n_est_pas_rendu(
        self, configuration: Configuration
    ) -> None:
        """Une moyenne sur un critère parmi trois ne mesure pas la même chose
        qu'une moyenne sur trois."""
        analyse = fabriquer_analyse("PARTIEL", {"momentum": "0.9"})
        classement = classer([analyse], PROFIL_TECHNIQUE, "court", configuration)
        assert classement.classes == ()
        assert "couverture insuffisante" in (classement.ecartes[0].score.motif_absent or "")

    def test_un_poids_portant_un_nom_inconnu_est_refuse_a_la_configuration(self) -> None:
        """Première barrière : un critère mal orthographié ne se charge pas."""
        with pytest.raises(ValidationError, match="Critères inconnus"):
            ConfigHorizon(
                libelle="Bancal",
                description="Pondère un critère qui n'existe pas",
                couverture_minimale=Decimal("0.5"),
                confiance_minimale=Decimal("0.25"),
                exige_fondamentaux=False,
                poids={"momentum": Decimal(1), "critere_fantome": Decimal(1)},
            )

    def test_critere_connu_mais_jamais_produit_est_signale(
        self, configuration: Configuration
    ) -> None:
        """Seconde barrière : un critère valide que l'analyse ne produit sur
        aucune valeur pèse dans la couverture sans jamais être mesuré."""
        analyse = fabriquer_analyse("TEST1", {"momentum": "0.5", "tendance": "0.5"})
        classement = classer([analyse], PROFIL_TECHNIQUE, "court", configuration)
        assert any("volume" in a for a in classement.avertissements)


class TestExigenceFondamentaux:
    def test_sans_fondamentaux_le_profil_long_ne_retombe_pas_sur_le_prix(
        self, configuration: Configuration
    ) -> None:
        profil = ConfigHorizon(
            libelle="Long",
            description="Exige des comptes",
            couverture_minimale=Decimal("0.5"),
            confiance_minimale=Decimal("0.15"),
            exige_fondamentaux=True,
            poids={"rendement_dividende": Decimal(1), "per": Decimal(1)},
        )
        analyse = fabriquer_analyse("TEST1", {"momentum": "1", "tendance": "1", "volume": "1"})
        classement = classer([analyse], profil, "long", configuration)
        assert classement.classes == ()
        motif = classement.ecartes[0].score.motif_absent or ""
        assert "ne retombe pas sur le prix" in motif
        assert any("référentiel est vide" in a for a in classement.avertissements)

    def test_avec_fondamentaux_le_profil_long_classe(self, configuration: Configuration) -> None:
        profil = ConfigHorizon(
            libelle="Long",
            description="Exige des comptes",
            couverture_minimale=Decimal("0.5"),
            confiance_minimale=Decimal("0.15"),
            exige_fondamentaux=True,
            poids={"rendement_dividende": Decimal(1), "per": Decimal(1)},
        )
        exercice = Fondamentaux(ticker="TEST1", exercice=2025, source="fictif")
        analyse = fabriquer_analyse(
            "TEST1",
            {"rendement_dividende": "0.8", "per": "0.6"},
            exercice=exercice,
        )
        classement = classer([analyse], profil, "long", configuration)
        assert [rang.ticker for rang in classement.classes] == ["TEST1"]


class TestSurDonneesReelles:
    def test_tous_les_profils_declares_sont_appliques(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = analyse_de(fabrique_serie([1000 + i * 3 for i in range(150)]), configuration)
        classements = classer_tous([analyse], configuration)
        assert set(classements) == set(configuration.analyse.horizons)

    def test_le_profil_long_de_la_configuration_livree_s_abstient_sans_comptes(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = analyse_de(fabrique_serie([1000 + i * 3 for i in range(150)]), configuration)
        classements = classer_tous([analyse], configuration)
        long_terme = classements["long_terme"]
        assert long_terme.classes == ()
        assert long_terme.ecartes

    def test_couverture_par_critere_dit_ce_qui_bloque(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyses = [
            analyse_de(fabrique_serie([1000 + i * 3 for i in range(150)]), configuration, "T1"),
            analyse_de(fabrique_serie([1000, 1010, 1020]), configuration, "T2"),
        ]
        couverture = resume_couverture(analyses)
        assert couverture["momentum"] == 1
        assert couverture["rendement_dividende"] == 0

    def test_valeurs_sans_aucun_fondamental_sont_listees(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyses = [
            analyse_de(fabrique_serie([1000 + i for i in range(150)]), configuration, "VIDE"),
            analyse_de(
                fabrique_serie([1000 + i for i in range(150)], ticker="PLEIN"),
                configuration,
                "PLEIN",
                exercices=(
                    Fondamentaux(
                        ticker="PLEIN",
                        exercice=2025,
                        source="fictif",
                        dividende_par_action=50,
                    ),
                    Fondamentaux(
                        ticker="PLEIN",
                        exercice=2024,
                        source="fictif",
                        dividende_par_action=45,
                    ),
                ),
            ),
        ]
        assert criteres_fondamentaux_manquants(analyses) == ["VIDE"]
