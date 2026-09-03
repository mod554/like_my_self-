"""Schéma du fichier de configuration unique.

Deux catégories de paramètres coexistent, et la distinction est volontaire :

1. **Les faits que le système n'a pas le droit d'inventer** — barème de frais de
   votre SGI, taux de fiscalité, seuil réglementaire de variation journalière,
   URL des sources. Ces champs sont obligatoires et **sans valeur par défaut** :
   tant qu'ils ne sont pas renseignés, la configuration échoue avec un message
   qui nomme le champ et indique où trouver l'information.
2. **Vos préférences** — limites de risque, fenêtres de calcul, niveau de log.
   Elles sont également obligatoires dans le schéma, mais le fichier d'exemple
   propose des valeurs de départ explicites, à ajuster.

Convention des taux : tous les taux sont des **fractions**, jamais des
pourcentages. 0,6 % s'écrit ``0.006``. Un taux supérieur à 1 est rejeté, car
c'est presque toujours une saisie en pourcentage.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brvm.domain.enums import (
    BaseFrais,
    Devise,
    MethodeValorisation,
    Pays,
    Periodicite,
    SensOperation,
)
from brvm.domain.monnaie import ModeArrondi
from brvm.domain.planification import Cron

#: Taux exprimé en fraction de l'assiette (0.006 = 0,6 %).
Taux = Annotated[Decimal, Field(ge=0, le=1)]
#: Fraction d'un total (poids de portefeuille, part de volume…).
Fraction = Annotated[Decimal, Field(gt=0, le=1)]

#: Champs qu'un analyseur de page peut alimenter. Doit rester aligné sur
#: `brvm.ingestion.conversion.CHAMPS` ; un test le vérifie.
CHAMPS_ANALYSABLES: frozenset[str] = frozenset(
    {
        "ticker",
        "date_seance",
        "statut_seance",
        "ouverture",
        "plus_haut",
        "plus_bas",
        "cloture",
        "cours_precedent",
        "volume_titres",
        "volume_xof",
        "nb_transactions",
        "limite_achat",
        "limite_vente",
        "commentaire",
    }
)


#: Critères qu'un profil de classement peut pondérer. Doit rester aligné sur ce
#: que produit `brvm.market.analyse` ; un test le vérifie.
CRITERES_TECHNIQUES: frozenset[str] = frozenset(
    {"momentum", "tendance", "regime_rsi", "repli", "volatilite", "volume"}
)
CRITERES_FONDAMENTAUX: frozenset[str] = frozenset(
    {"rendement_dividende", "per", "price_book", "regularite_dividende"}
)
CRITERES_CONNUS: frozenset[str] = CRITERES_TECHNIQUES | CRITERES_FONDAMENTAUX


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class ConfigGeneral(_Base):
    devise: Devise = Devise.XOF
    #: Fuseau des horodatages affichés. Les données sont stockées en UTC.
    fuseau_horaire: str = Field(min_length=1)
    repertoire_donnees: Path
    base_donnees: Path
    methode_valorisation: MethodeValorisation
    mode_arrondi: ModeArrondi

    @field_validator("devise")
    @classmethod
    def _refuser_autre_devise(cls, valeur: Devise) -> Devise:
        if valeur is not Devise.XOF:
            raise ValueError("Le système ne gère que le XOF et ne convertit aucune devise.")
        return valeur


class ConfigMarche(_Base):
    #: Pays de la place de cotation : ses jours fériés ferment la bourse.
    pays_place: Pays
    #: Fichier CSV décrivant l'univers suivi (ticker, nom, ISIN, pays, secteur).
    fichier_univers: Path
    #: Seuil réglementaire de variation d'un cours sur une séance, en fraction.
    #: À relever dans les textes en vigueur de l'entreprise de marché. Aucune
    #: valeur par défaut n'est fournie : un seuil inventé fausserait la détection
    #: d'anomalies à l'ingestion.
    seuil_variation_journaliere: Taux
    #: Heure de clôture locale, utilisée pour juger de la fraîcheur d'une donnée.
    heure_cloture_locale: str = Field(pattern=r"^\d{2}:\d{2}$")


class ConfigCalendrier(_Base):
    #: 0 = lundi … 6 = dimanche.
    jours_ouvres: tuple[int, ...] = Field(min_length=1)
    couverture_debut: date
    couverture_fin: date
    #: Fichier YAML des jours fériés, par pays et par date.
    fichier_feries: Path
    fermetures_exceptionnelles: tuple[date, ...] = ()

    @field_validator("jours_ouvres")
    @classmethod
    def _valider_jours(cls, valeur: tuple[int, ...]) -> tuple[int, ...]:
        if any(jour not in range(7) for jour in valeur):
            raise ValueError("Jours ouvrés attendus entre 0 (lundi) et 6 (dimanche).")
        return valeur

    @model_validator(mode="after")
    def _valider_periode(self) -> ConfigCalendrier:
        if self.couverture_debut > self.couverture_fin:
            raise ValueError("couverture_debut est postérieure à couverture_fin.")
        return self


class ConfigColonneLien(_Base):
    """Colonne dont l'information utile est dans le lien, pas dans le texte affiché.

    Cas courant sur une page de cote : la cellule affiche « SONATEL » tandis que
    le code de la valeur n'existe que dans l'adresse du lien. Le motif est une
    expression régulière à **un seul groupe de capture**, appliquée à l'adresse.
    """

    champ: str
    #: Expression régulière appliquée au lien ; le groupe capturé devient la valeur.
    motif: str = Field(min_length=1)

    @field_validator("motif")
    @classmethod
    def _valider_motif(cls, valeur: str) -> str:
        try:
            compile_ = re.compile(valeur)
        except re.error as exc:
            raise ValueError(f"Expression régulière invalide : {exc}") from exc
        if compile_.groups != 1:
            raise ValueError(
                "Le motif doit comporter exactement un groupe de capture, celui qui "
                f"isole la valeur à retenir (il en compte {compile_.groups})."
            )
        return valeur


class ConfigAnalyseur(_Base):
    """Description de la structure d'une page, telle que VOUS l'avez constatée.

    Le système ne devine aucune mise en page. Pour activer un connecteur web, vous
    ouvrez la page, vous regardez le tableau de cotations, et vous décrivez ici ce
    que vous voyez : quel tableau, et à quel champ correspond chaque en-tête de
    colonne. Le connecteur ne fait qu'appliquer cette description.

    Tant que ce bloc est absent, la source refuse de collecter et explique la
    marche à suivre plutôt que de produire des cours faux.
    """

    type: Literal["tableau_html", "non_verifie"]
    #: Rang du tableau dans la page, 0 pour le premier. Utilisez la commande de
    #: capture pour les repérer : `python -m brvm.ingestion.capture --lister-tableaux`.
    index_tableau: int = Field(default=0, ge=0)
    #: En-tête de colonne du site → champ du système. Champs acceptés : ticker,
    #: date_seance, statut_seance, ouverture, plus_haut, plus_bas, cloture,
    #: cours_precedent, volume_titres, volume_xof, nb_transactions, limite_achat,
    #: limite_vente.
    colonnes: dict[str, str] = Field(default_factory=dict)
    #: Colonnes dont on lit le lien plutôt que le texte affiché.
    colonnes_lien: dict[str, ConfigColonneLien] = Field(default_factory=dict)
    #: D'où vient la date de séance : d'une colonne de la page, ou du jour de la
    #: collecte. Le second cas suppose que la page montre bien la séance du jour ;
    #: le contrôle « séance hors calendrier » rattrape l'erreur si ce n'est pas le cas.
    date_seance_depuis: Literal["colonne", "jour_de_collecte"] = "colonne"

    @model_validator(mode="after")
    def _valider(self) -> ConfigAnalyseur:
        if self.type != "tableau_html":
            return self
        if not self.colonnes and not self.colonnes_lien:
            raise ValueError(
                "Analyseur de type tableau_html sans correspondance de colonnes : "
                "décrivez les en-têtes de la page que vous avez consultée."
            )
        doublons = set(self.colonnes) & set(self.colonnes_lien)
        if doublons:
            raise ValueError(
                "Ces colonnes sont déclarées à la fois en texte et en lien : "
                + ", ".join(sorted(doublons))
                + ". Choisissez laquelle des deux lectures fait foi."
            )
        cibles = set(self.colonnes.values()) | {lien.champ for lien in self.colonnes_lien.values()}
        if "ticker" not in cibles:
            raise ValueError(
                "Aucune colonne ne correspond au champ `ticker` : sans identifiant de "
                "valeur, une ligne de cote n'est rattachable à rien."
            )
        if self.date_seance_depuis == "colonne" and "date_seance" not in cibles:
            raise ValueError(
                "date_seance_depuis vaut « colonne » mais aucune colonne n'est associée "
                "au champ `date_seance`. Choisissez « jour_de_collecte » si la page ne "
                "porte pas la date."
            )
        inconnus = cibles - CHAMPS_ANALYSABLES
        if inconnus:
            raise ValueError(
                "Champs inconnus dans la correspondance de colonnes : "
                + ", ".join(sorted(inconnus))
                + ". Champs acceptés : "
                + ", ".join(sorted(CHAMPS_ANALYSABLES))
            )
        return self


class ConfigApi(_Base):
    """Description d'une API JSON, telle que VOUS l'avez observée.

    Comme pour l'analyse de page, le système n'invente aucun schéma : vous
    déclarez le chemin menant à la liste d'enregistrements, la correspondance
    entre les champs de la réponse et ceux du système, et le corps de la requête.

    Le corps accepte trois jetons, remplacés à chaque appel :
    ``{ticker}``, ``{debut}`` et ``{fin}``.
    """

    #: Chemin pointé menant à la liste d'enregistrements dans la réponse.
    #: Vide si la réponse est déjà une liste.
    chemin_liste: str = ""
    #: Corps JSON de la requête POST. Vide pour un GET.
    corps: dict[str, str] = Field(default_factory=dict)
    #: Champ de la réponse → champ du système. Champs acceptés : voir
    #: CHAMPS_ANALYSABLES.
    champs: dict[str, str] = Field(default_factory=dict)
    #: Format des dates **dans la réponse**, au sens de `datetime.strptime`.
    format_date: str = Field(default="%Y-%m-%d", min_length=2)
    #: Format des dates **dans la requête**. Souvent différent du précédent :
    #: une API peut attendre 2026-03-30 et répondre 30/03/2026.
    format_date_requete: str = Field(default="%Y-%m-%d", min_length=2)
    #: Gabarit du ticker envoyé à la source. Jetons : ``{ticker}``, ``{pays}``,
    #: ``{pays_bas}``. Exemple : ``{ticker}.{pays_bas}`` donne « SNTS.sn ».
    gabarit_ticker: str = "{ticker}"
    #: Profondeur d'historique demandée en une requête, en jours. Une API qui
    #: plafonne la fenêtre impose sa valeur : relevez-la, ne la supposez pas.
    fenetre_jours: int = Field(default=90, gt=0)
    #: Vrai pour écrire toutes les barres de la fenêtre (rattrapage d'historique),
    #: faux pour ne retenir que la séance visée. Le rattrapage fait remonter des
    #: barres anciennes, que le contrôle de fraîcheur signalera comme périmées :
    #: c'est attendu, et c'est pourquoi ce mode se demande explicitement.
    historique: bool = False
    #: En-têtes supplémentaires constatés nécessaires par VOUS (``Referer``,
    #: ``Origin``…). Jeton accepté : ``{ticker}``. Le ``User-Agent`` n'est pas
    #: surchargeable ici : l'identité annoncée doit rester vraie.
    entetes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valider(self) -> ConfigApi:
        if not self.champs:
            raise ValueError(
                "Aucune correspondance de champs déclarée : décrivez la réponse que "
                "vous avez observée."
            )
        cibles = set(self.champs.values())
        if "ticker" not in cibles and "{ticker}" not in self.gabarit_ticker:
            raise ValueError(
                "Ni champ `ticker` dans la réponse, ni jeton {ticker} dans le gabarit : "
                "les enregistrements ne seraient rattachables à aucune valeur."
            )
        if "date_seance" not in cibles:
            raise ValueError(
                "Aucun champ ne correspond à `date_seance` : une cotation sans séance "
                "n'est pas exploitable."
            )
        if inconnus := cibles - CHAMPS_ANALYSABLES:
            raise ValueError(
                "Champs inconnus dans la correspondance : "
                + ", ".join(sorted(inconnus))
                + ". Champs acceptés : "
                + ", ".join(sorted(CHAMPS_ANALYSABLES))
            )
        if any(nom.lower() == "user-agent" for nom in self.entetes):
            raise ValueError(
                "Le User-Agent est fixé par `ingestion.agent_utilisateur` et ne peut "
                "pas être redéfini par une source."
            )
        return self


class ConfigCsvDistant(_Base):
    """Description d'un dépôt de CSV servis en HTTP, telle que VOUS l'avez observée.

    Un fichier par valeur, une ligne par séance. Le système n'invente aucune
    correspondance de colonne : une colonne mal appariée produirait des cours
    faux sans le dire. Ouvrez un fichier de la source et recopiez ses en-têtes.
    """

    #: En-tête de la colonne portant la date de séance.
    colonne_date: str = Field(min_length=1)
    #: Format de cette date, au sens de `datetime.strptime`. Une date non
    #: conforme n'est jamais réinterprétée : c'est le seul garde-fou entre un
    #: 03/02 et un 02/03.
    format_date: str = Field(default="%Y-%m-%d", min_length=2)
    #: Champ du système → en-tête de colonne dans le fichier. Champs acceptés :
    #: voir CHAMPS_ANALYSABLES.
    colonnes: dict[str, str] = Field(default_factory=dict)
    #: Vrai pour écrire toutes les séances du fichier (rattrapage d'historique),
    #: faux pour ne retenir que la séance visée. Un rattrapage fait remonter des
    #: barres anciennes que le contrôle de fraîcheur signalera comme périmées :
    #: c'est attendu, et c'est pourquoi ce mode se demande explicitement.
    historique: bool = False
    #: Profondeur du rattrapage, en jours. Absent = tout le fichier.
    profondeur_jours: int | None = Field(default=None, gt=0)
    #: Calcule le montant échangé comme ``clôture × volume en titres`` quand la
    #: source publie l'un sans l'autre.
    #:
    #: **N'activez ceci qu'après avoir vérifié que votre source procède ainsi.**
    #: Le montant échangé mesure la profondeur du marché, donc la confiance
    #: accordée à la valeur : le dériver au jugé fausserait tous les classements
    #: sans le dire. Sur un marché de fixing, où une séance se dénoue à un cours
    #: unique, l'égalité est exacte ; sur un marché continu, elle ne l'est pas.
    #:
    #: Le champ dérivé porte la mention de son origine dans le commentaire de la
    #: cotation : un montant calculé ne doit pas se confondre avec un publié.
    volume_xof_depuis_cours: bool = False

    @model_validator(mode="after")
    def _valider_colonnes(self) -> ConfigCsvDistant:
        if not self.colonnes:
            raise ValueError(
                "Aucune correspondance de colonne déclarée : le connecteur ne "
                "saurait pas quelle colonne porte le cours. Recopiez les en-têtes "
                "du fichier réel."
            )
        inconnus = set(self.colonnes) - CHAMPS_ANALYSABLES
        if inconnus:
            raise ValueError(
                "Champs inconnus dans la correspondance de colonnes : "
                + ", ".join(sorted(inconnus))
                + ". Champs acceptés : "
                + ", ".join(sorted(CHAMPS_ANALYSABLES))
            )
        if "cloture" not in self.colonnes:
            raise ValueError(
                "La colonne de clôture est obligatoire : sans elle, aucune barre n'est exploitable."
            )
        return self


class ConfigSource(_Base):
    """Paramétrage d'un connecteur d'ingestion."""

    nom: str = Field(min_length=1)
    #: Identifiant du connecteur à instancier (voir la couche ingestion).
    type: str = Field(min_length=1)
    actif: bool
    #: Ordre de préférence lorsqu'une même séance est servie par plusieurs sources.
    priorite: int = Field(ge=1)
    #: URL de base. Obligatoire pour un connecteur réseau : le système ne devine
    #: aucune adresse et aucune structure de page qu'il n'a pas vérifiée.
    url_base: str | None = None
    #: Chemin local, pour un connecteur fichier de secours.
    chemin_fichier: Path | None = None
    timeout_s: int = Field(gt=0)
    tentatives_max: int = Field(ge=1)
    backoff_initial_s: Decimal = Field(gt=0)
    backoff_facteur: Decimal = Field(ge=1)
    respecter_robots: bool
    cache_minutes: int = Field(ge=0)
    #: Au-delà de cet âge, la donnée servie par cette source est signalée périmée.
    age_max_minutes: int = Field(gt=0)
    #: Structure de la page, constatée par vous. Absent = source non analysable.
    analyseur: ConfigAnalyseur | None = None
    #: Schéma de l'API, constaté par vous. Requis pour une source de type api_json.
    api: ConfigApi | None = None
    #: Colonnes du dépôt CSV, constatées par vous. Requis pour csv_distant.
    csv_distant: ConfigCsvDistant | None = None

    @model_validator(mode="after")
    def _valider_cible(self) -> ConfigSource:
        # Contrôle limité aux sources actives : une source peut rester déclarée et
        # inactive tant que son adresse n'a pas été vérifiée par l'utilisateur.
        if self.actif and self.url_base is None and self.chemin_fichier is None:
            raise ValueError(
                f"La source {self.nom!r} est active mais ne désigne ni url_base ni "
                "chemin_fichier : renseignez l'adresse vérifiée de la source, ou le "
                "fichier de secours."
            )
        return self


class ConfigLigneFrais(_Base):
    """Une ligne du barème, telle qu'elle figure sur la grille tarifaire de la SGI."""

    libelle: str = Field(min_length=1)
    base_calcul: BaseFrais
    #: Ordre d'application. Une ligne assise sur le total des commissions (TVA)
    #: doit porter un ordre supérieur aux lignes qu'elle taxe.
    ordre: int = Field(ge=1)
    applicable_a: Literal["ACHAT", "VENTE", "LES_DEUX"]
    #: Obligatoire sauf pour une ligne forfaitaire.
    taux: Taux | None = None
    #: Obligatoire pour une ligne forfaitaire.
    montant_fixe: int | None = Field(default=None, ge=0)
    #: Minimum de perception éventuel, en XOF.
    minimum_perception: int | None = Field(default=None, ge=0)
    #: Plafond éventuel, en XOF.
    maximum_perception: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valider_ligne(self) -> ConfigLigneFrais:
        if self.base_calcul is BaseFrais.MONTANT_FIXE:
            if self.montant_fixe is None:
                raise ValueError(
                    f"La ligne {self.libelle!r} est forfaitaire : renseignez montant_fixe "
                    "d'après la grille tarifaire de votre SGI."
                )
            if self.taux is not None:
                raise ValueError(
                    f"La ligne {self.libelle!r} est forfaitaire et ne doit pas porter de taux."
                )
        else:
            if self.taux is None:
                raise ValueError(
                    f"La ligne {self.libelle!r} est calculée sur {self.base_calcul.value} : "
                    "renseignez son taux d'après la grille tarifaire de votre SGI. Aucune "
                    "valeur par défaut n'est fournie par le système."
                )
            if self.montant_fixe is not None:
                raise ValueError(
                    f"La ligne {self.libelle!r} porte un taux et ne doit pas porter de "
                    "montant_fixe."
                )
        if (
            self.minimum_perception is not None
            and self.maximum_perception is not None
            and self.minimum_perception > self.maximum_perception
        ):
            raise ValueError(
                f"Ligne {self.libelle!r} : minimum de perception supérieur au plafond."
            )
        return self

    def concerne(self, sens: SensOperation) -> bool:
        return self.applicable_a in ("LES_DEUX", sens.value)


class ConfigFraisPeriodique(_Base):
    """Frais récurrent, indépendant des ordres passés.

    Droits de garde et tenue de compte ne se déclenchent pas à l'achat : ils
    courent tant que la ligne est détenue. Les omettre sous-estime le coût réel
    de détention — souvent de plusieurs points de pourcentage par an sur un
    petit portefeuille.
    """

    libelle: str = Field(min_length=1)
    #: ENCOURS : taux appliqué à la valeur des titres détenus.
    #: FORFAIT : montant fixe par période, quelle que soit la taille du portefeuille.
    base_calcul: Literal["ENCOURS", "FORFAIT"]
    periodicite: Periodicite
    #: Taux annuel, pour une assiette ENCOURS.
    taux: Taux | None = None
    #: Montant par période, pour un FORFAIT.
    montant_fixe: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valider(self) -> ConfigFraisPeriodique:
        if self.base_calcul == "ENCOURS":
            if self.taux is None:
                raise ValueError(
                    f"Le frais périodique {self.libelle!r} est assis sur l'encours : "
                    "renseignez son taux annuel d'après la grille tarifaire de votre SGI."
                )
            if self.montant_fixe is not None:
                raise ValueError(
                    f"{self.libelle!r} porte un taux et ne doit pas porter de montant_fixe."
                )
        else:
            if self.montant_fixe is None:
                raise ValueError(
                    f"Le frais périodique {self.libelle!r} est forfaitaire : renseignez "
                    "montant_fixe, le montant perçu à chaque période."
                )
            if self.taux is not None:
                raise ValueError(f"{self.libelle!r} est forfaitaire et ne doit pas porter de taux.")
        return self


class ConfigFrais(_Base):
    """Barème complet, à recopier depuis la grille tarifaire de votre SGI."""

    #: Traçabilité obligatoire : nom de la SGI et date de la grille utilisée.
    #: Un barème sans provenance n'est pas auditable.
    source_bareme: str = Field(min_length=3)
    lignes: tuple[ConfigLigneFrais, ...] = Field(min_length=1)
    #: Frais récurrents : droits de garde, tenue de compte. Leur absence est
    #: signalée au démarrage, car elle sous-estime le coût de détention.
    periodiques: tuple[ConfigFraisPeriodique, ...] = ()
    #: Minimum de perception global sur l'ensemble des frais d'un ordre, si la SGI
    #: en applique un.
    minimum_perception_global: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valider_bareme(self) -> ConfigFrais:
        ordres = [ligne.ordre for ligne in self.lignes]
        if len(set(ordres)) != len(ordres):
            raise ValueError(
                "Deux lignes de frais portent le même ordre d'application : l'assiette "
                "d'une TVA deviendrait ambiguë."
            )
        for ligne in self.lignes:
            if ligne.base_calcul is BaseFrais.TOTAL_COMMISSIONS:
                anterieures = [
                    autre
                    for autre in self.lignes
                    if autre.ordre < ligne.ordre
                    and autre.base_calcul is not BaseFrais.TOTAL_COMMISSIONS
                ]
                if not anterieures:
                    raise ValueError(
                        f"La ligne {ligne.libelle!r} est assise sur le total des "
                        "commissions mais aucune commission ne la précède "
                        "(ordre trop faible)."
                    )
        return self


class ConfigFiscalite(_Base):
    """Fiscalité applicable, selon votre pays de résidence fiscale."""

    pays_residence: Pays
    #: Traçabilité obligatoire : texte ou avis d'où les taux sont tirés.
    source_reference: str = Field(min_length=3)
    #: Retenue à la source sur les dividendes, en fraction. Aucune valeur par défaut.
    retenue_dividendes: Taux
    #: Les plus-values de cession sont-elles imposables dans votre situation ?
    plus_values_imposables: bool
    #: Taux applicable si elles le sont.
    plus_values_taux: Taux | None = None
    #: Abattement éventuel pour durée de détention, en nombre de mois au-delà
    #: duquel la plus-value est exonérée. ``None`` si aucun.
    plus_values_exoneration_mois: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valider(self) -> ConfigFiscalite:
        if self.plus_values_imposables and self.plus_values_taux is None:
            raise ValueError(
                "plus_values_imposables est vrai : renseignez plus_values_taux d'après "
                "le régime applicable à votre résidence fiscale."
            )
        if not self.plus_values_imposables and self.plus_values_taux is not None:
            raise ValueError(
                "plus_values_taux est renseigné alors que les plus-values sont déclarées "
                "non imposables : levez l'ambiguïté."
            )
        return self


class ConfigIndicateurs(_Base):
    """Fenêtres de calcul et garde-fous imposés par l'illiquidité.

    Les fenêtres sont des paramètres, pas des constantes du code : les valeurs
    usuelles (20/50/200, RSI 14, MACD 12/26/9) viennent des marchés liquides et
    n'ont aucune raison d'être optimales sur une valeur qui cote trois fois par
    semaine. Elles se règlent ici et se valident par backtest.
    """

    #: Part minimale de séances **réellement cotées** dans la fenêtre pour qu'un
    #: indicateur soit calculé. En deçà, le système refuse de répondre.
    ratio_minimum_seances_cotees: Fraction
    #: Nombre maximal de séances consécutives que le report de cours (forward fill)
    #: peut combler. Au-delà, le trou reste un trou.
    remplissage_max_seances: int = Field(ge=0)
    #: Fenêtre de calcul du volume moyen quotidien servant au score de confiance.
    fenetre_volume_moyen: int = Field(gt=0)
    #: Taux de remplissage au-delà duquel un résultat est marqué peu fiable.
    taux_remplissage_alerte: Fraction

    # ---------------------------------------------------------------- fenêtres
    fenetre_mm_courte: int = Field(gt=1)
    fenetre_mm_longue: int = Field(gt=1)
    #: Moyenne de fond, dite « ligne de vie ». Rarement calculable sur une valeur
    #: peu liquide : le système le dira plutôt que de l'approximer.
    fenetre_mm_fond: int = Field(gt=1)
    fenetre_rsi: int = Field(gt=1)
    macd_rapide: int = Field(gt=1)
    macd_lente: int = Field(gt=1)
    macd_signal: int = Field(gt=1)
    fenetre_bollinger: int = Field(gt=1)
    #: Nombre d'écarts-types de part et d'autre de la moyenne.
    ecarts_bollinger: Decimal = Field(gt=0)
    fenetre_atr: int = Field(gt=1)
    fenetre_momentum: int = Field(gt=0)
    fenetre_extremes: int = Field(gt=1)

    # -------------------------------------------------------------- seuils RSI
    rsi_survente: Decimal = Field(gt=0, lt=100)
    rsi_surachat: Decimal = Field(gt=0, lt=100)

    # ------------------------------------------------- références de liquidité
    #: Largeur de fourchette achat/vente au-delà de laquelle la liquidité est
    #: jugée mauvaise, en fraction du milieu de fourchette.
    fourchette_reference: Fraction
    #: Montant échangé quotidien à partir duquel la liquidité est jugée
    #: suffisante, en XOF. Sert à normaliser le score de confiance.
    volume_reference_xof: int = Field(gt=0)

    @model_validator(mode="after")
    def _valider(self) -> ConfigIndicateurs:
        if self.fenetre_mm_courte >= self.fenetre_mm_longue:
            raise ValueError(
                "fenetre_mm_courte doit être strictement inférieure à fenetre_mm_longue : "
                "un croisement de moyennes n'a autrement aucun sens."
            )
        if self.macd_rapide >= self.macd_lente:
            raise ValueError("macd_rapide doit être strictement inférieure à macd_lente.")
        if self.rsi_survente >= self.rsi_surachat:
            raise ValueError("rsi_survente doit être strictement inférieur à rsi_surachat.")
        return self


class ConfigIngestion(_Base):
    """Politique commune à tous les connecteurs.

    Ces réglages ne décrivent pas une source en particulier : ils fixent la
    manière dont le système se comporte vis-à-vis de n'importe quel serveur
    interrogé, et le seuil à partir duquel une donnée collectée est jugée
    suspecte.
    """

    #: Identité annoncée aux serveurs interrogés, avec un moyen de vous joindre.
    #: Obligatoire : un robot anonyme est une impolitesse, et souvent une
    #: violation des conditions d'utilisation.
    agent_utilisateur: str = Field(min_length=10)
    repertoire_cache: Path
    #: Délai minimal entre deux requêtes vers une même source.
    delai_entre_requetes_s: Decimal = Field(ge=0)
    #: Écart relatif toléré entre le montant échangé annoncé et
    #: quantité × cours, avant de signaler une incohérence.
    tolerance_volume_xof: Fraction
    #: Mettre en quarantaine une variation supérieure au seuil réglementaire
    #: déclaré dans `marche.seuil_variation_journaliere`.
    quarantaine_si_variation_hors_seuil: bool
    #: Refuser une cotation datée d'un jour que le calendrier ne reconnaît pas
    #: comme une séance : c'est presque toujours une erreur d'analyse de page.
    refuser_seance_hors_calendrier: bool
    #: Refuser une cotation datée dans le futur.
    refuser_date_future: bool


class ConfigRisque(_Base):
    poids_max_ligne: Fraction
    poids_max_secteur: Fraction
    poids_max_pays: Fraction
    #: Part maximale du volume moyen quotidien qu'une position peut représenter.
    part_max_volume_moyen: Fraction
    fenetre_volume_moyen: int = Field(gt=0)
    #: Multiple d'ATR pour le calcul d'un stop.
    #: Multiple d'ATR pour le calcul d'un stop. La fenêtre de l'ATR est celle
    #: déclarée dans `indicateurs.fenetre_atr` : un seul ATR dans le système.
    multiple_atr_stop: Decimal = Field(gt=0)
    #: Drawdown déclenchant une alerte, en fraction.
    drawdown_alerte: Fraction
    fenetre_volatilite: int = Field(gt=0)
    #: Nombre de séances de bourse dans une année, pour annualiser une
    #: volatilité ou un ratio. Dépend du calendrier réel : à ajuster après une
    #: année complète de collecte plutôt qu'à supposer.
    seances_par_an: int = Field(gt=0)
    #: Nombre minimal de séances réellement cotées en commun pour qu'une
    #: corrélation entre deux valeurs soit calculée.
    seances_minimum_correlation: int = Field(gt=1)
    #: Corrélation au-delà de laquelle deux lignes détenues sont signalées.
    #: [PRÉFÉRENCE] — trois lignes de 15 % qui varient ensemble font une
    #: position de 45 % que le contrôle de poids ne voit pas.
    correlation_alerte: Fraction = Decimal("0.80")
    #: Nombre de séances de débouclage au-delà duquel une ligne est signalée
    #: comme trop grosse pour sa liquidité. Facultatif : aucune valeur par défaut
    #: n'est fournie, parce qu'il n'en existe pas d'objective — le délai tolérable
    #: dépend de votre horizon. Laissé vide, le délai est calculé et affiché mais
    #: ne déclenche aucune alerte.
    seances_max_debouclage: int | None = Field(default=None, gt=0)


class ConfigBornes(_Base):
    """Bornes de normalisation des critères de classement.

    Chaque note de 0 à 1 vient d'une règle linéaire entre deux bornes. Ces bornes
    sont des **jugements**, pas des faits : dire qu'un momentum de +15 % vaut la
    note maximale est un choix, et il vous appartient. Le code n'en contient
    aucune ; elles sont ici, nommées, et se règlent par backtest.
    """

    #: Momentum en deçà duquel la note est nulle, et au-delà duquel elle sature.
    momentum_plancher: Decimal
    momentum_plafond: Decimal
    #: RSI considéré comme le régime normal, et écart toléré de part et d'autre.
    #: Un RSI à 15 comme à 85 s'éloigne autant du régime, et rien ne dit dans
    #: quel sens le cours y reviendra.
    rsi_cible: Decimal = Field(gt=0, lt=100)
    rsi_tolerance: Decimal = Field(gt=0)
    #: Écart au plus haut glissant : 0 = au plus haut, 1 = au plus bas.
    #: Sert au repli sur les creux, et se lit à l'envers selon l'horizon.
    ecart_extreme_plafond: Fraction
    #: Volatilité annualisée au-delà de laquelle la note tombe à zéro.
    volatilite_plafond: Decimal = Field(gt=0)
    #: Rendement du dividende saturant la note. Au-delà, un rendement très élevé
    #: signale plus souvent un cours effondré qu'une aubaine.
    rendement_dividende_plafond: Taux
    #: PER en deçà duquel la note sature, au-delà duquel elle s'annule.
    per_plancher: Decimal = Field(gt=0)
    per_plafond: Decimal = Field(gt=0)
    #: Cours / actif net comptable, mêmes bornes.
    price_book_plancher: Decimal = Field(gt=0)
    price_book_plafond: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def _valider(self) -> ConfigBornes:
        if self.momentum_plafond <= self.momentum_plancher:
            raise ValueError("momentum_plafond doit dépasser momentum_plancher.")
        if self.per_plafond <= self.per_plancher:
            raise ValueError("per_plafond doit dépasser per_plancher.")
        if self.price_book_plafond <= self.price_book_plancher:
            raise ValueError("price_book_plafond doit dépasser price_book_plancher.")
        return self


class ConfigHorizon(_Base):
    """Un profil de classement : ce qui compte, et combien.

    Deux profils sont attendus — court terme et long terme — mais rien n'empêche
    d'en déclarer d'autres. Les poids vous appartiennent : ce sont eux qui disent
    si vous classez sur la tendance ou sur le rendement.
    """

    libelle: str = Field(min_length=1)
    #: Ce que ce profil mesure, en une phrase, affichée à côté du classement.
    description: str = Field(min_length=1)
    #: Nom du critère → poids. Un critère absent de cette table n'entre pas dans
    #: le score de ce profil.
    poids: dict[str, Decimal] = Field(min_length=1)
    #: Part minimale des critères pondérés qui doit être mesurable pour qu'une
    #: valeur soit classée. En deçà, elle apparaît en « non classable », avec la
    #: liste de ce qui manque.
    couverture_minimale: Fraction
    #: Confiance de la donnée en deçà de laquelle la valeur n'est pas classée.
    #: Sur cette place, c'est le garde-fou principal.
    confiance_minimale: Fraction
    #: Vrai si ce profil exige des données fondamentales. Un profil long terme
    #: sans fondamentaux ne classe rien et le dit, plutôt que de retomber sur le
    #: seul prix.
    exige_fondamentaux: bool = False

    @field_validator("poids")
    @classmethod
    def _valider_poids(cls, valeur: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(poids < 0 for poids in valeur.values()):
            raise ValueError("Un poids ne peut pas être négatif.")
        if sum(valeur.values()) <= 0:
            raise ValueError("La somme des poids doit être strictement positive.")
        # Un poids portant un nom inconnu ne pèserait sur rien et passerait
        # inaperçu : le classement serait silencieusement établi sur autre chose
        # que ce que l'utilisateur croit avoir déclaré.
        if inconnus := set(valeur) - CRITERES_CONNUS:
            raise ValueError(
                "Critères inconnus dans les poids : "
                + ", ".join(sorted(inconnus))
                + ". Critères disponibles : "
                + ", ".join(sorted(CRITERES_CONNUS))
            )
        return valeur

    @model_validator(mode="after")
    def _valider_coherence(self) -> ConfigHorizon:
        fondamentaux_ponderes = set(self.poids) & CRITERES_FONDAMENTAUX
        if self.exige_fondamentaux and not fondamentaux_ponderes:
            raise ValueError(
                f"Le profil {self.libelle!r} exige des fondamentaux mais n'en "
                "pondère aucun. Ajoutez au moins un critère parmi : "
                + ", ".join(sorted(CRITERES_FONDAMENTAUX))
            )
        if fondamentaux_ponderes and not self.exige_fondamentaux:
            raise ValueError(
                f"Le profil {self.libelle!r} pondère des critères fondamentaux "
                + ", ".join(sorted(fondamentaux_ponderes))
                + " sans les exiger. Les valeurs sans comptes saisis seraient "
                "classées sur une couverture réduite et compareraient mal. "
                "Passez `exige_fondamentaux` à true."
            )
        return self


class ConfigAnalyse(_Base):
    """Criblage de la cote : bornes de notation et profils de classement."""

    #: Fichier CSV des données fondamentales, renseigné par vous depuis les
    #: rapports annuels. Absent, les profils qui en dépendent s'abstiennent.
    fichier_fondamentaux: Path
    bornes: ConfigBornes
    horizons: dict[str, ConfigHorizon] = Field(min_length=1)
    #: Nombre de valeurs présentées en tête de chaque classement.
    taille_classement: int = Field(gt=0)


class ConfigAllocation(_Base):
    """Contraintes de construction d'un portefeuille.

    L'allocateur ne choisit rien : il applique vos limites, dans l'ordre, et dit
    laquelle a mordu sur chaque ligne. Les limites de concentration viennent de
    `risque` — elles ne sont pas redéclarées ici, pour qu'il n'y ait qu'un seul
    endroit où elles vivent.
    """

    #: Nombre maximal de lignes proposées. Au-delà, les frais fixes et le suivi
    #: coûtent plus que la diversification ne rapporte.
    lignes_max: int = Field(gt=0)
    #: Part du capital laissée en liquidités.
    part_liquidites: Fraction
    #: Montant minimal d'une ligne. En deçà, les frais fixes rendent l'opération
    #: absurde ; le seuil dépend du barème de VOTRE SGI.
    montant_minimum_ligne: int = Field(gt=0)
    #: Part des frais dans le montant d'un ordre au-delà de laquelle l'ordre est
    #: signalé comme coûteux.
    frais_alerte: Fraction


class ConfigBacktest(_Base):
    capital_initial: int = Field(gt=0)
    #: Glissement appliqué au cours d'exécution, en fraction.
    slippage: Taux
    #: Part maximale du volume de la séance qu'un ordre simulé peut consommer.
    part_max_volume_seance: Fraction
    #: Seule hypothèse d'exécution retenue : à l'ouverture de la barre suivante.
    execution: Literal["OUVERTURE_BARRE_SUIVANTE"]
    #: Que faire quand la source ne publie pas de cours d'ouverture.
    #: REFUSER : aucune exécution — le backtest est plus pauvre mais rigoureux.
    #: COURS_PRECEDENT : exécuter à la clôture de la veille, qui est connue avant
    #: l'ouverture. C'est une approximation qui ignore les écarts d'ouverture,
    #: fréquents sur une valeur qui n'a pas coté depuis plusieurs séances.
    execution_sans_ouverture: Literal["REFUSER", "COURS_PRECEDENT"]
    #: Découpage walk-forward : longueurs en nombre de séances.
    walk_forward_apprentissage: int = Field(gt=0)
    walk_forward_validation: int = Field(gt=0)
    #: Taux sans risque annuel utilisé par le ratio de Sharpe, en fraction.
    #: Zéro est un choix, pas une absence de choix : le déclarer évite de
    #: comparer une performance à un placement sans risque imaginaire.
    taux_sans_risque: Taux


class ConfigCanalAlerte(_Base):
    nom: str = Field(min_length=1)
    type: Literal["fichier", "email", "webhook"]
    actif: bool
    #: Paramètres propres au canal (chemin, destinataires, URL…).
    parametres: dict[str, str] = Field(default_factory=dict)


class ConfigAlertes(_Base):
    canaux: tuple[ConfigCanalAlerte, ...] = ()
    #: Âge de donnée déclenchant une alerte de péremption.
    age_donnee_max_minutes: int = Field(gt=0)
    alerter_signal_technique: bool
    alerter_seuil_risque: bool
    alerter_echec_source: bool


class ConfigJournalisation(_Base):
    niveau: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    fichier: Path
    taille_max_octets: int = Field(gt=0)
    nb_sauvegardes: int = Field(ge=0)
    #: Journal structuré en JSON par ligne, pour être relu par une machine.
    format_json: bool


class ConfigOrdonnanceur(_Base):
    actif: bool
    #: Expression cron des collectes, appliquée uniquement les jours de séance.
    #:
    #: **0 = lundi**, comme `date.weekday()` et comme partout ailleurs dans ce
    #: système — et non 0 = dimanche comme dans certains cron Unix. Les jours
    #: ouvrés s'écrivent donc ``1-5``… non : ``0-4``. C'est exactement le genre
    #: d'erreur qui ne produit aucun message, seulement une séance jamais
    #: collectée le lundi ; l'expression est donc analysée dès le chargement.
    cron_collecte: str = Field(min_length=1)
    fuseau_horaire: str = Field(min_length=1)

    @field_validator("cron_collecte")
    @classmethod
    def _valider_cron(cls, valeur: str) -> str:
        # Analysée maintenant plutôt qu'au premier réveil : une expression fautive
        # découverte à 16h00 un jour de séance est découverte trop tard.
        Cron.analyser(valeur)
        return valeur


class Configuration(_Base):
    """Racine du fichier de configuration."""

    general: ConfigGeneral
    marche: ConfigMarche
    calendrier: ConfigCalendrier
    sources: tuple[ConfigSource, ...] = Field(min_length=1)
    frais: ConfigFrais
    fiscalite: ConfigFiscalite
    ingestion: ConfigIngestion
    indicateurs: ConfigIndicateurs
    analyse: ConfigAnalyse
    allocation: ConfigAllocation
    risque: ConfigRisque
    backtest: ConfigBacktest
    alertes: ConfigAlertes
    journalisation: ConfigJournalisation
    ordonnanceur: ConfigOrdonnanceur

    @model_validator(mode="after")
    def _valider_ensemble(self) -> Configuration:
        noms = [source.nom for source in self.sources]
        if len(set(noms)) != len(noms):
            raise ValueError("Deux sources portent le même nom.")
        if not any(source.actif for source in self.sources):
            raise ValueError("Aucune source active : le système n'aurait aucune donnée à ingérer.")
        priorites = [source.priorite for source in self.sources if source.actif]
        if len(set(priorites)) != len(priorites):
            raise ValueError(
                "Deux sources actives partagent la même priorité : l'arbitrage entre "
                "sources concurrentes serait indéterminé."
            )
        return self

    def sources_actives(self) -> tuple[ConfigSource, ...]:
        return tuple(
            sorted(
                (source for source in self.sources if source.actif),
                key=lambda source: source.priorite,
            )
        )

    def avertissements(self) -> list[str]:
        """Signalements non bloquants, à afficher au démarrage."""
        messages: list[str] = []
        if self.marche.pays_place != self.fiscalite.pays_residence:
            messages.append(
                f"Place de cotation ({self.marche.pays_place.value}) et résidence fiscale "
                f"({self.fiscalite.pays_residence.value}) diffèrent : vérifiez qu'une "
                "convention fiscale ne modifie pas la retenue sur dividendes."
            )
        if not self.frais.periodiques:
            messages.append(
                "Aucun frais périodique déclaré (droits de garde, tenue de compte) : le "
                "coût de détention affiché sera sous-estimé. Complétez frais.periodiques "
                "dès que vous connaissez les taux exacts de votre SGI."
            )
        elif not any(frais.base_calcul == "ENCOURS" for frais in self.frais.periodiques):
            messages.append(
                "Aucun droit de garde assis sur l'encours n'est déclaré. C'est le frais "
                "récurrent qui croît avec le portefeuille : si votre SGI en perçoit un, "
                "son absence sous-estime le coût de détention d'autant plus que le "
                "portefeuille grossit."
            )
        # Le seuil de repli est déclaré, mais aucun calcul ne peut s'y comparer :
        # mesurer le repli d'un portefeuille exige un historique de ses
        # valorisations, que le système n'enregistre pas encore. Le dire vaut
        # mieux que de laisser croire à une surveillance qui n'existe pas.
        messages.append(
            f"Seuil de repli déclaré ({self.risque.drawdown_alerte:.0%}) mais inopérant : "
            "aucune alerte de repli ne peut se déclencher tant que le système "
            "n'enregistre pas l'historique de valorisation du portefeuille. Le "
            "repli est calculé et testé, il n'a simplement rien à quoi se comparer."
        )
        if self.indicateurs.remplissage_max_seances == 0:
            messages.append(
                "Le report de cours est désactivé (remplissage_max_seances = 0) : sur une "
                "valeur peu liquide, beaucoup d'indicateurs refuseront de se calculer."
            )
        return messages
