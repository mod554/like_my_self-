"""L'alerte de repli, de l'historisation jusqu'au constat diffusé.

Le seuil `risque.drawdown_alerte` figurait dans les trois configurations livrées
et ne pouvait se comparer à rien : aucune valorisation n'était conservée. Ce
module vérifie la chaîne entière, et surtout ses deux abstentions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from brvm.app.alertes import CategorieAlerte, NiveauAlerte
from brvm.app.surveillance import depuis_repli
from brvm.config.modeles import Configuration
from brvm.domain.modeles import Valorisation

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)


def valorisation(jour: date, actif: int, especes: int = 0) -> Valorisation:
    return Valorisation(
        date_seance=jour,
        valeur_titres=actif - especes,
        cout_total=actif,
        plus_value_brute=0,
        nb_lignes=1,
        horodatage_calcul=INSTANT,
        especes=especes,
        actif_total=actif,
    )


def sans_especes(jour: date, titres: int) -> Valorisation:
    return Valorisation(
        date_seance=jour,
        valeur_titres=titres,
        cout_total=titres,
        plus_value_brute=0,
        nb_lignes=1,
        horodatage_calcul=INSTANT,
        motif_especes="aucun apport déclaré",
    )


class TestDeclenchement:
    def test_un_repli_au_dela_du_seuil_alerte(self, configuration: Configuration) -> None:
        seuil = configuration.risque.drawdown_alerte
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), int(1_000_000 * (1 - float(seuil) - 0.05))),
        ]
        alertes = depuis_repli(serie, configuration, INSTANT)
        assert len(alertes) == 1
        assert alertes[0].categorie is CategorieAlerte.REPLI_PORTEFEUILLE

    def test_sous_le_seuil_rien_n_est_emis(self, configuration: Configuration) -> None:
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), 990_000),
        ]
        assert depuis_repli(serie, configuration, INSTANT) == []

    def test_un_repli_double_du_seuil_est_critique(self, configuration: Configuration) -> None:
        seuil = float(configuration.risque.drawdown_alerte)
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), int(1_000_000 * (1 - seuil * 2.5))),
        ]
        assert depuis_repli(serie, configuration, INSTANT)[0].niveau is NiveauAlerte.CRITIQUE

    def test_le_message_donne_de_quoi_verifier(self, configuration: Configuration) -> None:
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), 700_000),
        ]
        alerte = depuis_repli(serie, configuration, INSTANT)[0]
        assert "plus-haut" in alerte.message
        assert alerte.contexte["seuil"]
        assert alerte.contexte["plus_haut"] == "1000000"


class TestAbstentions:
    def test_sans_especes_connues_le_repli_n_est_pas_approche(
        self, configuration: Configuration
    ) -> None:
        """Mesurer sur les titres seuls afficherait 100 % dès qu'une ligne est
        soldée. On rend un constat d'impossibilité, pas un chiffre."""
        serie = [sans_especes(date(2026, 3, 2), 1_000_000), sans_especes(date(2026, 3, 3), 0)]
        alertes = depuis_repli(serie, configuration, INSTANT)
        assert len(alertes) == 1
        assert alertes[0].categorie is CategorieAlerte.CONFIGURATION
        assert alertes[0].niveau is NiveauAlerte.INFORMATION
        assert "100 %" in alertes[0].message

    def test_sans_historique_aucun_constat(self, configuration: Configuration) -> None:
        """Un portefeuille jamais valorisé ne produit pas de bruit."""
        assert depuis_repli([], configuration, INSTANT) == []

    def test_une_seule_seance_ne_declenche_rien_de_chiffre(
        self, configuration: Configuration
    ) -> None:
        alertes = depuis_repli([valorisation(date(2026, 3, 2), 1_000_000)], configuration, INSTANT)
        assert len(alertes) == 1
        assert alertes[0].categorie is CategorieAlerte.CONFIGURATION

    def test_alertes_de_risque_desactivees_taisent_le_repli(
        self, configuration: Configuration
    ) -> None:
        muet = configuration.model_copy(
            update={
                "alertes": configuration.alertes.model_copy(update={"alerter_seuil_risque": False})
            }
        )
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), 500_000),
        ]
        assert depuis_repli(serie, muet, INSTANT) == []


class TestSeuilEffectif:
    def test_le_seuil_declare_decide_vraiment(self, configuration: Configuration) -> None:
        """Le réglage était mort : ce test échouerait s'il le redevenait."""
        serie = [
            valorisation(date(2026, 3, 2), 1_000_000),
            valorisation(date(2026, 3, 3), 880_000),  # repli de 12 %
        ]
        tolerant = configuration.model_copy(
            update={
                "risque": configuration.risque.model_copy(
                    update={"drawdown_alerte": Decimal("0.20")}
                )
            }
        )
        strict = configuration.model_copy(
            update={
                "risque": configuration.risque.model_copy(
                    update={"drawdown_alerte": Decimal("0.05")}
                )
            }
        )
        assert depuis_repli(serie, tolerant, INSTANT) == []
        assert len(depuis_repli(serie, strict, INSTANT)) == 1
