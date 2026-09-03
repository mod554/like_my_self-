"""Configuration : refus explicite des paramètres que le système ne doit pas inventer."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from pydantic import BaseModel

from brvm.config.chargement import (
    CHEMINS_A_RESOUDRE,
    CHEMINS_RESOLUS_A_PART,
    charger_configuration,
    charger_jours_feries,
    construire_calendrier_depuis_config,
    resume_configuration,
)
from brvm.config.modeles import ConfigSource, Configuration
from brvm.domain.enums import Pays
from brvm.utils.erreurs import ErreurConfiguration

RACINE_PROJET = Path(__file__).resolve().parents[1]
CONFIG_EXEMPLE = RACINE_PROJET / "config" / "config.exemple.yaml"


def ecrire(chemin: Path, contenu: dict[str, Any]) -> Path:
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True, sort_keys=False), "utf-8")
    return chemin


def charger_brut(dossier: Path) -> dict[str, Any]:
    contenu = yaml.safe_load((dossier / "config_valide.yaml").read_text(encoding="utf-8"))
    assert isinstance(contenu, dict)
    return contenu


class TestFichierExemple:
    """Le fichier livré doit échouer : il ne contient volontairement aucun barème."""

    def test_le_fichier_exemple_existe(self) -> None:
        assert CONFIG_EXEMPLE.is_file()

    def test_le_fichier_exemple_refuse_de_se_charger(self) -> None:
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(CONFIG_EXEMPLE)
        message = str(capture.value)
        assert "frais.source_bareme" in message
        assert "fiscalite.retenue_dividendes" in message
        assert "marche.seuil_variation_journaliere" in message

    def test_le_message_oriente_vers_la_grille_tarifaire(self) -> None:
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(CONFIG_EXEMPLE)
        message = str(capture.value)
        assert "grille tarifaire de votre SGI" in message
        assert "Aucune valeur par défaut n'est substituée" in message

    def test_toutes_les_erreurs_sont_listees_d_un_coup(self) -> None:
        """L'utilisateur ne doit pas découvrir les champs manquants un par un."""
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(CONFIG_EXEMPLE)
        assert str(capture.value).count("  • ") >= 6


class TestChargementValide:
    def test_configuration_de_test_valide(self, configuration: Configuration) -> None:
        assert configuration.general.devise.value == "XOF"
        assert configuration.marche.pays_place is Pays.COTE_DIVOIRE
        assert len(configuration.frais.lignes) == 4

    def test_chemins_relatifs_resolus_par_rapport_au_fichier(
        self, configuration: Configuration, dossier_config: Path
    ) -> None:
        assert configuration.marche.fichier_univers.is_absolute()
        assert configuration.marche.fichier_univers.parent == dossier_config

    def test_sources_actives_triees_par_priorite(self, configuration: Configuration) -> None:
        actives = configuration.sources_actives()
        assert [source.nom for source in actives] == ["fichier_manuel"]

    def test_resume_affichable(self, configuration: Configuration) -> None:
        resume = resume_configuration(configuration)
        assert resume["devise"] == "XOF"
        assert "FICTIF" in resume["barème de frais"]

    def test_fichier_absent(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="introuvable"):
            charger_configuration(tmp_path / "absent.yaml")

    def test_fichier_vide(self, tmp_path: Path) -> None:
        vide = tmp_path / "vide.yaml"
        vide.write_text("", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="vide"):
            charger_configuration(vide)

    def test_yaml_invalide(self, tmp_path: Path) -> None:
        casse = tmp_path / "casse.yaml"
        casse.write_text("general: [\n  non fermé", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="illisible"):
            charger_configuration(casse)


class TestRefusDesIncoherences:
    def modifier(self, dossier: Path, mutation: Callable[[dict[str, Any]], None]) -> Path:
        brut = charger_brut(dossier)
        mutation(brut)
        return ecrire(dossier / "modifie.yaml", brut)

    def test_devise_autre_que_xof_refusee(self, dossier_config: Path) -> None:
        chemin = self.modifier(dossier_config, lambda c: c["general"].update(devise="EUR"))
        with pytest.raises(ErreurConfiguration):
            charger_configuration(chemin)

    def test_taux_superieur_a_un_refuse(self, dossier_config: Path) -> None:
        """0,6 % saisi « 0.6 » passe ; saisi « 60 » doit être rejeté."""
        chemin = self.modifier(dossier_config, lambda c: c["frais"]["lignes"][0].update(taux=60))
        with pytest.raises(ErreurConfiguration):
            charger_configuration(chemin)

    def test_ligne_proportionnelle_sans_taux_refusee(self, dossier_config: Path) -> None:
        chemin = self.modifier(dossier_config, lambda c: c["frais"]["lignes"][0].update(taux=None))
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(chemin)
        assert "grille tarifaire" in str(capture.value)

    def test_tva_appliquee_avant_toute_commission_refusee(self, dossier_config: Path) -> None:
        """Une TVA d'ordre 1 n'aurait aucune assiette à taxer."""

        def mutation(config: dict[str, Any]) -> None:
            config["frais"]["lignes"] = [
                ligne for ligne in config["frais"]["lignes"] if ligne["ordre"] == 3
            ]
            config["frais"]["lignes"][0]["ordre"] = 1

        chemin = self.modifier(dossier_config, mutation)
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(chemin)
        assert "aucune commission ne la précède" in str(capture.value)

    def test_ordres_de_frais_en_double_refuses(self, dossier_config: Path) -> None:
        chemin = self.modifier(dossier_config, lambda c: c["frais"]["lignes"][1].update(ordre=1))
        with pytest.raises(ErreurConfiguration, match="même ordre"):
            charger_configuration(chemin)

    def test_aucune_source_active_refusee(self, dossier_config: Path) -> None:
        def mutation(config: dict[str, Any]) -> None:
            for source in config["sources"]:
                source["actif"] = False

        chemin = self.modifier(dossier_config, mutation)
        with pytest.raises(ErreurConfiguration, match="Aucune source active"):
            charger_configuration(chemin)

    def test_priorites_de_sources_actives_en_double_refusees(self, dossier_config: Path) -> None:
        def mutation(config: dict[str, Any]) -> None:
            config["sources"][1]["actif"] = True
            config["sources"][1]["chemin_fichier"] = "./cotations_test.csv"
            config["sources"][1]["priorite"] = 1

        chemin = self.modifier(dossier_config, mutation)
        with pytest.raises(ErreurConfiguration, match="même priorité"):
            charger_configuration(chemin)

    def test_source_active_sans_cible_refusee(self, dossier_config: Path) -> None:
        chemin = self.modifier(
            dossier_config, lambda c: c["sources"][1].update(actif=True, priorite=9)
        )
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(chemin)
        assert "url_base" in str(capture.value)

    def test_source_inactive_sans_cible_toleree(self, dossier_config: Path) -> None:
        """Un connecteur réseau peut rester déclaré tant que son adresse n'a pas
        été vérifiée par l'utilisateur."""
        configuration = charger_configuration(dossier_config / "config_valide.yaml")
        inactive = next(s for s in configuration.sources if not s.actif)
        assert inactive.url_base is None

    def test_plus_values_imposables_sans_taux_refusees(self, dossier_config: Path) -> None:
        chemin = self.modifier(
            dossier_config, lambda c: c["fiscalite"].update(plus_values_imposables=True)
        )
        with pytest.raises(ErreurConfiguration, match="plus_values_taux"):
            charger_configuration(chemin)

    def test_cle_inconnue_refusee(self, dossier_config: Path) -> None:
        """Une faute de frappe dans une clé ne doit pas passer inaperçue."""
        chemin = self.modifier(dossier_config, lambda c: c["general"].update(mode_arondi="HALF_UP"))
        with pytest.raises(ErreurConfiguration):
            charger_configuration(chemin)


class TestJoursFeries:
    def test_chargement(self, dossier_config: Path) -> None:
        feries = charger_jours_feries(dossier_config / "jours_feries_test.yaml")
        assert date(2026, 1, 1) in feries[Pays.COTE_DIVOIRE]
        assert date(2026, 4, 4) in feries[Pays.SENEGAL]

    def test_fichier_absent_refuse(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="introuvable"):
            charger_jours_feries(tmp_path / "absent.yaml")

    def test_code_pays_inconnu_refuse(self, tmp_path: Path) -> None:
        fichier = tmp_path / "feries.yaml"
        fichier.write_text("ZZ:\n  - 2026-01-01\n", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="Code pays inconnu"):
            charger_jours_feries(fichier)

    def test_date_mal_formee_refusee(self, tmp_path: Path) -> None:
        fichier = tmp_path / "feries.yaml"
        fichier.write_text("CI:\n  - 01/01/2026\n", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="invalide"):
            charger_jours_feries(fichier)

    def test_liste_vide_acceptee(self, tmp_path: Path) -> None:
        fichier = tmp_path / "feries.yaml"
        fichier.write_text("CI:\n", encoding="utf-8")
        assert charger_jours_feries(fichier)[Pays.COTE_DIVOIRE] == frozenset()


class TestCalendrierDepuisConfiguration:
    def test_construction(self, configuration: Configuration) -> None:
        calendrier = construire_calendrier_depuis_config(configuration)
        assert calendrier.pays_place is Pays.COTE_DIVOIRE
        # 2026-01-01 est déclaré férié dans le fichier de test.
        assert not calendrier.est_jour_de_seance(date(2026, 1, 1))
        assert calendrier.est_jour_de_seance(date(2026, 1, 2))

    def test_ferie_senegalais_ne_ferme_pas_la_place(self, configuration: Configuration) -> None:
        calendrier = construire_calendrier_depuis_config(configuration)
        assert calendrier.est_jour_de_seance(date(2026, 4, 3))
        assert calendrier.est_ferie(date(2026, 4, 4), Pays.SENEGAL)


def test_avertissements_non_bloquants(dossier_config: Path) -> None:
    brut = charger_brut(dossier_config)
    brut["fiscalite"]["pays_residence"] = "SN"
    chemin = ecrire(dossier_config / "residence_autre.yaml", brut)
    configuration = charger_configuration(chemin)
    messages = configuration.avertissements()
    assert any("convention fiscale" in message for message in messages)


def test_les_fichiers_exemples_ne_contiennent_aucun_taux(tmp_path: Path) -> None:
    """Garde-fou de gouvernance : le dépôt ne doit livrer aucun barème pré-rempli.

    On recharge le fichier d'exemple et on vérifie que chaque ligne de frais et
    chaque taux de fiscalité y sont vides.
    """
    shutil.copy(CONFIG_EXEMPLE, tmp_path / "exemple.yaml")
    brut = yaml.safe_load((tmp_path / "exemple.yaml").read_text(encoding="utf-8"))
    for ligne in brut["frais"]["lignes"]:
        assert ligne.get("taux") is None
        assert ligne.get("montant_fixe") is None
    assert brut["frais"]["source_bareme"] is None
    assert brut["fiscalite"]["retenue_dividendes"] is None
    assert brut["fiscalite"]["plus_values_taux"] is None
    assert brut["marche"]["seuil_variation_journaliere"] is None


class TestConfigurationPreRemplie:
    """Le fichier travaillé ne doit rien avoir deviné, et ne buter que sur l'identité."""

    CHEMIN = RACINE_PROJET / "config" / "config.sg-capital-2026.yaml"

    def test_le_fichier_existe(self) -> None:
        assert self.CHEMIN.is_file()

    def test_ne_bute_que_sur_l_identite_du_robot(self) -> None:
        with pytest.raises(ErreurConfiguration) as capture:
            charger_configuration(self.CHEMIN)
        lignes = [ligne for ligne in str(capture.value).splitlines() if ligne.startswith("  •")]
        assert len(lignes) == 1
        assert "ingestion.agent_utilisateur" in lignes[0]

    def _charge(self, tmp_path: Path) -> Configuration:
        brut = yaml.safe_load(self.CHEMIN.read_text(encoding="utf-8"))
        assert isinstance(brut, dict)
        brut["ingestion"]["agent_utilisateur"] = "test/0.1 (contact: test@exemple.org)"
        return charger_configuration(ecrire(tmp_path / "rempli.yaml", brut))

    def test_se_charge_une_fois_l_identite_renseignee(self, tmp_path: Path) -> None:
        configuration = self._charge(tmp_path)
        assert configuration.marche.seuil_variation_journaliere == Decimal("0.075")
        assert configuration.marche.heure_cloture_locale == "15:30"
        assert configuration.fiscalite.retenue_dividendes == Decimal("0.15")
        assert configuration.fiscalite.plus_values_imposables is False

    def test_chaque_valeur_porte_sa_provenance(self, tmp_path: Path) -> None:
        """Un barème sans source n'est pas auditable : la provenance est dans le champ."""
        configuration = self._charge(tmp_path)
        assert "28/03/2026" in configuration.frais.source_bareme
        assert "CONFIRMER" in configuration.frais.source_bareme.upper()
        assert "CONFIRMER" in configuration.fiscalite.source_reference.upper()

    def test_les_taux_incertains_restent_absents(self, tmp_path: Path) -> None:
        """La conservation est donnée en fourchette par la source : le système ne
        choisit pas à la place de l'utilisateur, il signale le manque."""
        configuration = self._charge(tmp_path)
        assert not any(frais.base_calcul == "ENCOURS" for frais in configuration.frais.periodiques)
        assert any("droit de garde" in m for m in configuration.avertissements())

    def test_frais_periodique_forfaitaire_conserve(self, tmp_path: Path) -> None:
        configuration = self._charge(tmp_path)
        tenue = next(f for f in configuration.frais.periodiques if f.base_calcul == "FORFAIT")
        assert tenue.montant_fixe == 2500
        assert tenue.periodicite.occurrences_par_an == 4

    def test_analyseur_lit_le_ticker_dans_le_lien(self, tmp_path: Path) -> None:
        """Sur la page de cote observée, le code valeur n'est pas dans la cellule."""
        source = self._source(tmp_path, "cote_du_jour")
        assert source.analyseur is not None
        assert source.analyseur.colonnes_lien["Nom"].champ == "ticker"
        assert source.actif is False  # inactive tant que l'URL n'est pas vérifiée

    def _source(self, tmp_path: Path, nom: str) -> ConfigSource:
        return next(s for s in self._charge(tmp_path).sources if s.nom == nom)

    def test_toutes_les_sources_reseau_restent_inactives(self, tmp_path: Path) -> None:
        """Aucune structure de page ou d'API n'a pu être observée depuis
        l'environnement de développement : rien ne collecte tant que
        l'utilisateur n'a pas vérifié lui-même."""
        configuration = self._charge(tmp_path)
        reseau = [s for s in configuration.sources if s.type in {"web", "api_json"}]
        assert reseau and all(s.actif is False for s in reseau)

    def test_page_officielle_declaree_avec_len_tete_manquant_en_evidence(
        self, tmp_path: Path
    ) -> None:
        """Les en-têtes attestés sont déclarés ; celui qui ne l'est pas porte la
        mention qui le signale, plutôt qu'un intitulé plausible inventé."""
        source = self._source(tmp_path, "brvm_officiel")
        assert source.analyseur is not None
        colonnes = source.analyseur.colonnes
        assert colonnes["Closing price"] == "cloture"
        assert colonnes["Previous price"] == "cours_precedent"
        entete_ticker = next(cle for cle, champ in colonnes.items() if champ == "ticker")
        assert "RENSEIGNER" in entete_ticker

    def test_api_historique_declare_deux_formats_de_date(self, tmp_path: Path) -> None:
        """Dates envoyées en aaaa-mm-jj, reçues en jj/mm/aaaa : confondre les deux
        ne produit pas une erreur mais une séance décalée."""
        source = self._source(tmp_path, "sikafinance_historique")
        assert source.api is not None
        assert source.api.format_date == "%d/%m/%Y"
        assert source.api.format_date_requete == "%Y-%m-%d"
        assert source.api.gabarit_ticker == "{ticker}.{pays_bas}"
        assert source.api.chemin_liste == "lst"
        assert source.api.historique is False

    def test_api_historique_ne_declare_que_les_champs_attestes(self, tmp_path: Path) -> None:
        source = self._source(tmp_path, "sikafinance_historique")
        assert source.api is not None
        assert set(source.api.champs) == {"Date", "Open", "High", "Low", "Close", "Volume"}


class TestFraisPeriodiques:
    def test_encours_sans_taux_refuse(self, dossier_config: Path) -> None:
        brut = charger_brut(dossier_config)
        brut["frais"]["periodiques"] = [
            {"libelle": "Droits de garde", "base_calcul": "ENCOURS", "periodicite": "ANNUELLE"}
        ]
        with pytest.raises(ErreurConfiguration, match="taux annuel"):
            charger_configuration(ecrire(dossier_config / "periodiques.yaml", brut))

    def test_forfait_sans_montant_refuse(self, dossier_config: Path) -> None:
        brut = charger_brut(dossier_config)
        brut["frais"]["periodiques"] = [
            {
                "libelle": "Tenue de compte",
                "base_calcul": "FORFAIT",
                "periodicite": "TRIMESTRIELLE",
            }
        ]
        with pytest.raises(ErreurConfiguration, match="montant_fixe"):
            charger_configuration(ecrire(dossier_config / "periodiques.yaml", brut))

    def test_absence_totale_signalee(self, configuration: Configuration) -> None:
        assert any("Aucun frais périodique" in m for m in configuration.avertissements())


class TestOrdonnancement:
    """L'expression cron est validée au chargement, pas au premier réveil manqué."""

    def test_expression_fautive_refusee_des_le_chargement(self, dossier_config: Path) -> None:
        brut = charger_brut(dossier_config)
        brut["ordonnanceur"]["cron_collecte"] = "30 15 * *"
        with pytest.raises(ErreurConfiguration, match="au lieu de 5"):
            charger_configuration(ecrire(dossier_config / "cron.yaml", brut))

    def test_jour_de_semaine_hors_bornes_refuse(self, dossier_config: Path) -> None:
        brut = charger_brut(dossier_config)
        brut["ordonnanceur"]["cron_collecte"] = "30 15 * * 9"
        with pytest.raises(ErreurConfiguration, match="hors bornes"):
            charger_configuration(ecrire(dossier_config / "cron.yaml", brut))

    def test_les_fichiers_livres_emploient_la_convention_du_projet(self) -> None:
        """0 = lundi. « 1-5 » désignerait mardi à samedi et sauterait tous les
        lundis sans produire le moindre message — d'où ce contrôle."""
        for chemin in (CONFIG_EXEMPLE, RACINE_PROJET / "config" / "config.sg-capital-2026.yaml"):
            brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
            jours = brut["ordonnanceur"]["cron_collecte"].split()[4]
            assert jours == "0-4", f"{chemin.name} : jours ouvrés attendus « 0-4 », lu « {jours} »"


class TestResolutionDesChemins:
    """Tout champ `Path` de la configuration doit être rendu absolu au
    chargement, faute de quoi il dépend du répertoire courant.

    Le mode d'échec est le plus grave de ceux que ce projet s'interdit : le
    fichier que l'utilisateur a rempli n'est pas lu, et le système annonce
    « aucune donnée saisie » — une affirmation fausse présentée comme un fait.
    C'est exactement ce qui était arrivé à `analyse.fichier_fondamentaux`.
    """

    @staticmethod
    def champs_chemin() -> set[str]:
        """Tous les champs typés `Path` de la configuration, en notation pointée."""
        trouves: set[str] = set()
        vus: set[str] = set()

        def parcourir(modele: type[Any], prefixe: str = "") -> None:
            if modele.__name__ in vus:
                return
            vus.add(modele.__name__)
            for nom, champ in modele.model_fields.items():
                annotation = champ.annotation
                arguments = getattr(annotation, "__args__", ())
                if annotation is Path or Path in arguments:
                    trouves.add(f"{prefixe}{nom}")
                for sous in (annotation, *arguments):
                    if isinstance(sous, type) and issubclass(sous, BaseModel):
                        parcourir(sous, f"{prefixe}{nom}.")

        parcourir(Configuration)
        return trouves

    def test_aucun_chemin_n_echappe_a_la_resolution(self) -> None:
        declares = {f"{section}.{cle}" for section, cle in CHEMINS_A_RESOUDRE}
        manquants = self.champs_chemin() - declares - CHEMINS_RESOLUS_A_PART
        assert manquants == set(), (
            "Chemins non résolus au chargement : "
            + ", ".join(sorted(manquants))
            + ". Ajoutez-les à CHEMINS_A_RESOUDRE, sinon ils dépendront du "
            "répertoire courant et seront lus vides sans le dire."
        )

    def test_les_chemins_charges_sont_absolus(self, configuration: Configuration) -> None:
        assert configuration.marche.fichier_univers.is_absolute()
        assert configuration.analyse.fichier_fondamentaux.is_absolute()
        assert configuration.calendrier.fichier_feries.is_absolute()

    def test_le_referentiel_fondamental_est_lu_depuis_le_dossier_de_config(
        self, configuration: Configuration
    ) -> None:
        """Contrôle de bout en bout : le fichier livré à côté du YAML est lu."""
        from brvm.market.fondamentaux import charger_fondamentaux

        referentiel = charger_fondamentaux(configuration.analyse.fichier_fondamentaux)
        assert referentiel, "le référentiel fondamental de test doit être lu"


class TestReglagesEffectivementLus:
    """Tout réglage déclaré doit être lu quelque part dans le code.

    Un champ obligatoire que personne ne lit est pire qu'un champ absent :
    l'utilisateur le renseigne, croit avoir réglé quelque chose, et rien ne
    change — sans le moindre message. C'est exactement ce qui était arrivé à
    `risque.fenetre_volatilite`, déclarée dans les trois configurations livrées
    et lue par aucun calcul : toutes les volatilités portaient sur l'historique
    entier au lieu de la fenêtre demandée.
    """

    #: Champs lus par les méthodes de la configuration elle-même, et donc
    #: invisibles au balayage ci-dessous, qui écarte `config/modeles.py`.
    #: Chacun nomme la méthode qui le lit : l'entrée est vérifiée, pas subie.
    LUS_DANS_LE_MODELE: ClassVar[dict[str, str]] = {
        "applicable_a": "ConfigLigneFrais.concerne",
        "priorite": "Configuration.sources_actives",
        "drawdown_alerte": "Configuration.avertissements",
    }

    @staticmethod
    def champs_declares() -> dict[str, str]:
        """Tous les champs des modèles de configuration, et leur modèle."""
        trouves: dict[str, str] = {}
        vus: set[str] = set()

        def parcourir(modele: type[Any]) -> None:
            if modele.__name__ in vus:
                return
            vus.add(modele.__name__)
            for nom, champ in modele.model_fields.items():
                trouves.setdefault(nom, modele.__name__)
                annotation = champ.annotation
                for sous in (annotation, *getattr(annotation, "__args__", ())):
                    if isinstance(sous, type) and issubclass(sous, BaseModel):
                        parcourir(sous)

        parcourir(Configuration)
        return trouves

    def test_aucun_reglage_declare_n_est_ignore_par_le_code(self) -> None:
        sources = [
            chemin.read_text(encoding="utf-8")
            for chemin in (RACINE_PROJET / "src").rglob("*.py")
            # Le fichier des modèles ne compte pas : il DÉCLARE les champs, il
            # ne les lit pas. S'y fier rendrait le contrôle inopérant.
            if chemin.name != "modeles.py" or "config" not in chemin.parts
        ]
        jamais_lus = {
            nom: modele
            for nom, modele in self.champs_declares().items()
            if nom not in self.LUS_DANS_LE_MODELE
            and not any(f".{nom}" in texte for texte in sources)
        }
        assert jamais_lus == {}, (
            "Réglages déclarés mais lus par aucun calcul : "
            + ", ".join(f"{modele}.{nom}" for nom, modele in sorted(jamais_lus.items()))
            + ". L'utilisateur les renseignerait sans effet et sans message."
        )

    def test_les_lectures_dans_le_modele_sont_reelles(self) -> None:
        """Une exemption doit rester vraie : si la méthode citée cesse de lire le
        champ, l'exemption devient un trou et ce contrôle le dit."""
        modeles = (RACINE_PROJET / "src" / "brvm" / "config" / "modeles.py").read_text(
            encoding="utf-8"
        )
        for nom in self.LUS_DANS_LE_MODELE:
            assert f"self.{nom}" in modeles or f".{nom}" in modeles, (
                f"{nom} est exempté au motif qu'il est lu dans modeles.py, "
                "mais il n'y apparaît plus."
            )
