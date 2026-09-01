"""Allocation : l'enveloppe n'est jamais dépassée, et la limite qui mord est nommée."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.enums import Pays, SensOperation
from brvm.domain.modeles import Instrument
from brvm.market.allocation import Proposition, proposer, rebalancer
from brvm.market.analyse import AnalyseValeur
from brvm.market.criteres import Critere, Score
from brvm.market.horizons import Classement, Rang
from brvm.portfolio.frais import MoteurFrais


def rang(
    ticker: str,
    score: str,
    cours: int = 1000,
    taille_tenable: int = 100_000,
    confiance: str = "0.9",
) -> Rang:
    analyse = AnalyseValeur(
        ticker=ticker,
        instrument=None,
        cours=cours,
        date_cours=date(2026, 3, 2),
        confiance=Decimal(confiance),
        niveau_confiance="test",
        seances_cotees=90,
        seances_attendues=100,
        taille_tenable=taille_tenable,
        motif_taille=None,
        criteres={},
    )
    return Rang(
        ticker=ticker,
        analyse=analyse,
        score=Score(valeur=Decimal(score), criteres=(), couverture=Decimal(1)),
    )


def classement(*rangs: Rang, ecartes: tuple[Rang, ...] = ()) -> Classement:
    return Classement(
        horizon="test",
        libelle="Test",
        description="Classement de test",
        classes=rangs,
        ecartes=ecartes,
    )


def valider_enveloppe(proposition: Proposition, configuration: Configuration) -> None:
    """Invariant central : le décaissement réel, frais compris, tient dans
    l'enveloppe investissable déclarée."""
    enveloppe = Decimal(proposition.capital) * (
        Decimal(1) - configuration.allocation.part_liquidites
    )
    assert Decimal(proposition.investi) <= enveloppe, (
        f"{proposition.investi} XOF investis pour une enveloppe de {enveloppe} XOF"
    )
    assert proposition.investi == sum(ligne.montant_net for ligne in proposition.lignes)


class TestEnveloppe:
    @pytest.mark.parametrize("capital", [250_000, 800_000, 5_000_000, 50_000_000])
    def test_les_frais_ne_font_jamais_deborder_l_enveloppe(
        self, capital: int, configuration: Configuration
    ) -> None:
        """Une quantité calculée sur le seul montant brut fait dépasser
        l'enveloppe de ses propres frais."""
        cote = classement(
            rang("AAA", "0.9"),
            rang("BBB", "0.8"),
            rang("CCC", "0.7"),
            rang("DDD", "0.6"),
        )
        proposition = proposer(cote, capital, configuration)
        valider_enveloppe(proposition, configuration)

    def test_capital_nul_ne_propose_rien_et_le_dit(self, configuration: Configuration) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 0, configuration)
        assert proposition.lignes == ()
        assert any("Capital nul" in a for a in proposition.avertissements)

    def test_liquidites_sont_le_reliquat_du_capital(self, configuration: Configuration) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 5_000_000, configuration)
        assert proposition.liquidites == proposition.capital - proposition.investi

    def test_part_liquidites_est_respectee(self, configuration: Configuration) -> None:
        cote = classement(*(rang(f"V{i}", f"0.{9 - i}") for i in range(6)))
        proposition = proposer(cote, 20_000_000, configuration)
        part_liquide = Decimal(proposition.liquidites) / Decimal(proposition.capital)
        assert part_liquide >= configuration.allocation.part_liquidites


class TestContraintes:
    def test_la_limite_qui_mord_est_nommee_sur_chaque_ligne(
        self, configuration: Configuration
    ) -> None:
        proposition = proposer(
            classement(rang("AAA", "0.9"), rang("BBB", "0.8")), 5_000_000, configuration
        )
        assert proposition.lignes
        for ligne in proposition.lignes:
            assert ligne.contrainte

    def test_liquidite_borne_la_ligne_et_le_dit(self, configuration: Configuration) -> None:
        """Sur cette place, c'est presque toujours elle qui mord la première."""
        cote = classement(rang("ETROIT", "0.9", cours=1000, taille_tenable=200))
        proposition = proposer(cote, 50_000_000, configuration)
        assert len(proposition.lignes) == 1
        assert proposition.lignes[0].quantite == 200
        assert "liquidité" in proposition.lignes[0].contrainte

    def test_concentration_par_ligne_borne_sur_un_gros_capital(
        self, configuration: Configuration
    ) -> None:
        cote = classement(*(rang(f"V{i}", "0.9") for i in range(6)))
        proposition = proposer(cote, 100_000_000, configuration)
        enveloppe = Decimal(proposition.capital) * (
            Decimal(1) - configuration.allocation.part_liquidites
        )
        plafond = enveloppe * configuration.risque.poids_max_ligne
        for ligne in proposition.lignes:
            assert Decimal(ligne.montant_net) <= plafond

    def test_nombre_de_lignes_plafonne_et_les_suivantes_sont_ecartees(
        self, configuration: Configuration
    ) -> None:
        """Lignes étroites : la liquidité borne chacune bien en deçà de la
        limite de concentration, si bien que c'est le nombre de lignes qui
        finit par mordre."""
        maxi = configuration.allocation.lignes_max
        cote = classement(
            *(rang(f"V{i:02d}", "0.9", cours=1000, taille_tenable=150) for i in range(maxi + 3))
        )
        proposition = proposer(cote, 50_000_000, configuration)
        assert len(proposition.lignes) == maxi
        motifs = [e.motif for e in proposition.ecartes]
        assert sum(f"limite de {maxi} lignes" in motif for motif in motifs) == 3

    def test_concentration_par_ligne_mord_avant_le_nombre_de_lignes(
        self, configuration: Configuration
    ) -> None:
        """Avec une limite de 20 % par ligne, cinq lignes remplissent
        l'enveloppe : la limite de huit lignes ne peut pas être atteinte, et les
        valeurs suivantes sortent pour capital épuisé, pas pour nombre de lignes."""
        maxi = configuration.allocation.lignes_max
        cote = classement(*(rang(f"V{i:02d}", "0.9") for i in range(maxi + 3)))
        proposition = proposer(cote, 100_000_000, configuration)
        attendu = int(Decimal(1) / configuration.risque.poids_max_ligne)
        assert len(proposition.lignes) == attendu
        assert all(
            "limite de" not in e.motif or "lignes" not in e.motif for e in proposition.ecartes
        )

    def test_ligne_sous_le_minimum_est_ecartee_avec_la_contrainte_d_origine(
        self, configuration: Configuration
    ) -> None:
        minimum = configuration.allocation.montant_minimum_ligne
        cote = classement(rang("MINUSCULE", "0.9", cours=100, taille_tenable=10))
        proposition = proposer(cote, 5_000_000, configuration)
        assert proposition.lignes == ()
        motif = proposition.ecartes[0].motif
        assert str(minimum) in motif
        assert "bornée par" in motif

    def test_concentration_sectorielle_borne_deux_valeurs_du_meme_secteur(
        self, configuration: Configuration
    ) -> None:
        instruments = {
            ticker: Instrument(ticker=ticker, nom=ticker, pays=Pays.COTE_DIVOIRE, secteur="Finance")
            for ticker in ("AAA", "BBB", "CCC")
        }
        cote = classement(rang("AAA", "0.9"), rang("BBB", "0.8"), rang("CCC", "0.7"))
        proposition = proposer(cote, 100_000_000, configuration, instruments=instruments)
        enveloppe = Decimal(proposition.capital) * (
            Decimal(1) - configuration.allocation.part_liquidites
        )
        total_secteur = sum(Decimal(ligne.montant_net) for ligne in proposition.lignes)
        assert total_secteur <= enveloppe * configuration.risque.poids_max_secteur

    def test_sans_cours_cote_la_valeur_est_ecartee(self, configuration: Configuration) -> None:
        cote = classement(rang("MUET", "0.9", cours=None))  # type: ignore[arg-type]
        proposition = proposer(cote, 5_000_000, configuration)
        assert proposition.lignes == ()
        assert "aucun cours" in proposition.ecartes[0].motif


class TestPoidsObtenu:
    def test_les_poids_obtenus_somment_a_un(self, configuration: Configuration) -> None:
        cote = classement(rang("AAA", "0.9"), rang("BBB", "0.8"), rang("CCC", "0.7"))
        proposition = proposer(cote, 10_000_000, configuration)
        assert proposition.lignes
        total = sum(ligne.poids_obtenu for ligne in proposition.lignes)
        assert abs(total - Decimal(1)) < Decimal("0.0001")

    def test_depassement_de_concentration_reel_est_signale_avec_son_remede(
        self, configuration: Configuration
    ) -> None:
        """Les limites s'appliquent à l'enveloppe, les poids se constatent sur
        l'investi. Quand l'enveloppe n'a pas pu être remplie, l'écart est dit —
        sinon les contrôles de risque signaleraient un portefeuille que
        l'allocateur vient de proposer."""
        cote = classement(rang("AAA", "0.9"), rang("BBB", "0.8"))
        proposition = proposer(cote, 800_000, configuration)
        depassements = [
            ligne
            for ligne in proposition.lignes
            if ligne.poids_obtenu > configuration.risque.poids_max_ligne
        ]
        if depassements:
            assert any("est dépassée" in a for a in proposition.avertissements)
            assert any("Abaissez ce minimum" in a for a in proposition.avertissements)

    def test_une_seule_ligne_n_est_pas_un_portefeuille(self, configuration: Configuration) -> None:
        cote = classement(rang("AAA", "0.9"))
        proposition = proposer(cote, 5_000_000, configuration)
        assert len(proposition.lignes) == 1
        assert any("c'est une position" in a for a in proposition.avertissements)


class TestAvertissements:
    def test_aucune_promesse_de_rendement(self, configuration: Configuration) -> None:
        """Contrainte du projet : le système ne promet jamais un rendement."""
        proposition = proposer(classement(rang("AAA", "0.9")), 5_000_000, configuration)
        assert any("ne prédit aucun rendement" in a for a in proposition.avertissements)

    def test_classement_vide_le_dit(self, configuration: Configuration) -> None:
        proposition = proposer(classement(), 5_000_000, configuration)
        assert proposition.lignes == ()
        assert any("Aucune ligne proposée" in a for a in proposition.avertissements)

    def test_valeurs_non_classees_sont_rappelees(self, configuration: Configuration) -> None:
        cote = classement(rang("AAA", "0.9"), ecartes=(rang("REJET", "0"),))
        proposition = proposer(cote, 5_000_000, configuration)
        assert any("n'ont pas été classées" in a for a in proposition.avertissements)

    def test_frais_lourds_sur_petite_ligne_sont_signales(
        self, configuration: Configuration
    ) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 5_000_000, configuration)
        couteuses = [
            ligne
            for ligne in proposition.lignes
            if ligne.part_frais > configuration.allocation.frais_alerte
        ]
        if couteuses:
            assert any("Frais d'entrée au-delà" in a for a in proposition.avertissements)


class TestRebalancement:
    def test_ordres_pour_rejoindre_la_cible(self, configuration: Configuration) -> None:
        proposition = proposer(
            classement(rang("AAA", "0.9"), rang("BBB", "0.8")), 10_000_000, configuration
        )
        cible = {ligne.ticker: ligne.quantite for ligne in proposition.lignes}
        detenu = {"AAA": cible["AAA"] - 50, "ZZZ": 100}
        cours = {ligne.ticker: ligne.cours for ligne in proposition.lignes} | {"ZZZ": 1000}
        mouvements, _ = rebalancer(detenu, proposition, cours, configuration)
        par_ticker = {m.ticker: m for m in mouvements}
        assert par_ticker["AAA"].sens is SensOperation.ACHAT
        assert par_ticker["AAA"].quantite == 50
        assert par_ticker["ZZZ"].sens is SensOperation.VENTE
        assert "sortie complète" in par_ticker["ZZZ"].motif

    def test_ligne_deja_a_la_cible_ne_produit_aucun_ordre(
        self, configuration: Configuration
    ) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 10_000_000, configuration)
        cible = {ligne.ticker: ligne.quantite for ligne in proposition.lignes}
        cours = {ligne.ticker: ligne.cours for ligne in proposition.lignes}
        mouvements, _ = rebalancer(cible, proposition, cours, configuration)
        assert mouvements == ()

    def test_sans_cours_l_ordre_n_est_pas_chiffre(self, configuration: Configuration) -> None:
        """Chiffrer un ordre sans cours reviendrait à inventer un montant."""
        proposition = proposer(classement(rang("AAA", "0.9")), 10_000_000, configuration)
        mouvements, avertissements = rebalancer({"ZZZ": 100}, proposition, {}, configuration)
        assert all(m.ticker != "ZZZ" for m in mouvements)
        assert any("aucun cours disponible" in a for a in avertissements)

    def test_frais_de_rebalancement_au_dela_du_seuil_sont_signales(
        self, configuration: Configuration
    ) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 10_000_000, configuration)
        moteur = MoteurFrais(configuration)
        mouvements, avertissements = rebalancer(
            {"PETIT": 0, "AAA": proposition.lignes[0].quantite - 1},
            proposition,
            {"AAA": proposition.lignes[0].cours},
            configuration,
            moteur=moteur,
        )
        assert mouvements
        if mouvements[0].part_frais > configuration.allocation.frais_alerte:
            assert any("Rééquilibrer coûte" in a for a in avertissements)


class TestTracabilite:
    def test_chaque_ligne_porte_son_decompte_complet(self, configuration: Configuration) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 10_000_000, configuration)
        ligne = proposition.lignes[0]
        assert ligne.montant_brut == ligne.quantite * ligne.cours
        assert ligne.montant_net == ligne.montant_brut + ligne.frais
        assert proposition.frais_totaux == sum(el.frais for el in proposition.lignes)

    def test_confiance_basse_est_rappelee_sur_la_ligne(self, configuration: Configuration) -> None:
        cote = classement(rang("DOUTEUX", "0.9", confiance="0.30"))
        proposition = proposer(cote, 10_000_000, configuration)
        assert proposition.lignes[0].avertissements
        assert "Confiance de la donnée" in proposition.lignes[0].avertissements[0]

    def test_resume_est_lisible(self, configuration: Configuration) -> None:
        proposition = proposer(classement(rang("AAA", "0.9")), 10_000_000, configuration)
        resume = proposition.resume()
        assert "AAA" in resume
        assert "Frais d'entrée" in resume


def test_critere_non_utilise_ici_reste_importable() -> None:
    """Garde l'import de Critere significatif si le module évolue."""
    assert Critere.absent("x", "X", "motif").note is None
