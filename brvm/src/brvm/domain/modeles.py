"""Modèles du domaine, validés par pydantic.

Ces classes sont le contrat de données à chaque frontière du système : une
donnée qui ne les satisfait pas ne rentre pas. La couche d'ingestion attrape les
``ValidationError`` et met l'enregistrement en quarantaine ; elle ne « répare »
jamais silencieusement.

Toutes les instances sont immuables (``frozen=True``) : une cotation corrigée
donne un nouvel enregistrement de révision supérieure, pas une mutation en place.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Final

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from brvm.domain.enums import (
    BaseFrais,
    Devise,
    GraviteAnomalie,
    Pays,
    SensOperation,
    StatutCollecte,
    StatutFiabilite,
    StatutSeance,
    TypeFluxEspece,
    TypeOst,
)

#: Format de ticker accepté. Volontairement permissif : la BRVM utilise des codes
#: courts alphanumériques, mais certaines sources les suffixent d'un code pays
#: (``SNTS.SN``). Le système ne présume d'aucune liste fermée ; il impose
#: seulement des majuscules, pour qu'une même valeur ne soit jamais enregistrée
#: sous deux clés différant par la casse.
MOTIF_TICKER: Final[str] = r"^[A-Z0-9][A-Z0-9.\-]{1,15}$"

#: ISO 6166 : 2 lettres de pays, 9 caractères alphanumériques, 1 chiffre de contrôle.
MOTIF_ISIN: Final[str] = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"

Ticker = Annotated[str, Field(pattern=MOTIF_TICKER)]
MontantXof = Annotated[int, Field(ge=0)]
CoursXof = Annotated[int, Field(gt=0)]
Quantite = Annotated[int, Field(gt=0)]


def _serialiser(valeur: Any) -> Any:
    if isinstance(valeur, (date, datetime)):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        return str(valeur)
    raise TypeError(f"Type non sérialisable pour l'empreinte : {type(valeur)!r}")


class ModeleBrvm(BaseModel):
    """Base commune : immuable, sans champ surnuméraire toléré."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


def _exiger_aware(valeur: datetime, nom: str) -> datetime:
    """Contrôle un horodatage fourni hors validation pydantic (argument de méthode).

    Les champs de modèle sont typés ``AwareDatetime`` et sont déjà contrôlés par
    pydantic ; cette fonction sert aux dates passées en argument.
    """
    if valeur.tzinfo is None or valeur.utcoffset() is None:
        raise ValueError(
            f"{nom} doit porter un fuseau horaire explicite. Un horodatage naïf rend "
            "l'âge de la donnée incalculable."
        )
    return valeur


# --------------------------------------------------------------------- instrument


def isin_conforme(isin: str) -> bool:
    """Vérifie le chiffre de contrôle ISO 6166 (algorithme de Luhn sur l'alphabet étendu).

    Chaque lettre est remplacée par sa position dans l'alphabet + 9 (A=10 … Z=35),
    puis Luhn est appliqué sur la chaîne de chiffres obtenue.
    """
    if len(isin) != 12:
        return False
    chiffres = ""
    for caractere in isin[:11]:
        if caractere.isdigit():
            chiffres += caractere
        elif caractere.isalpha():
            chiffres += str(ord(caractere.upper()) - ord("A") + 10)
        else:
            return False
    total = 0
    # Luhn : on double un chiffre sur deux en partant de la droite de la base.
    for position, caractere in enumerate(reversed(chiffres)):
        valeur = int(caractere)
        if position % 2 == 0:
            valeur *= 2
            if valeur > 9:
                valeur -= 9
        total += valeur
    controle = (10 - (total % 10)) % 10
    return controle == int(isin[11])


class Instrument(ModeleBrvm):
    """Valeur cotée suivie par le système."""

    ticker: Ticker
    nom: str = Field(min_length=1)
    isin: str | None = Field(default=None, pattern=MOTIF_ISIN)
    pays: Pays
    secteur: str | None = None
    compartiment: str | None = None
    devise: Devise = Devise.XOF
    actif: bool = True
    nombre_titres: int | None = Field(default=None, gt=0)
    date_maj: AwareDatetime | None = None

    @field_validator("isin")
    @classmethod
    def _valider_isin(cls, valeur: str | None) -> str | None:
        if valeur is not None and not isin_conforme(valeur):
            raise ValueError(
                f"Chiffre de contrôle ISIN invalide pour {valeur!r} : la saisie comporte "
                "probablement une faute de frappe."
            )
        return valeur


# ---------------------------------------------------------------------- cotation


class Cotation(ModeleBrvm):
    """Cotation d'une valeur pour une séance, telle que fournie par une source.

    Série **non ajustée** : c'est la donnée brute, conservée telle quelle.
    L'ajustement des dividendes et des divisions est calculé séparément
    (:mod:`brvm.domain.ajustement`).
    """

    ticker: Ticker
    date_seance: date
    source: str = Field(min_length=1)
    statut_seance: StatutSeance

    ouverture: CoursXof | None = None
    plus_haut: CoursXof | None = None
    plus_bas: CoursXof | None = None
    cloture: CoursXof | None = None
    #: Cours de référence de la séance précédente, tel que publié par la source.
    cours_precedent: CoursXof | None = None

    volume_titres: MontantXof = 0
    volume_xof: MontantXof | None = None
    nb_transactions: int | None = Field(default=None, ge=0)

    #: Meilleure limite à l'achat au carnet (« bid »).
    meilleure_limite_achat: CoursXof | None = None
    #: Meilleure limite à la vente au carnet (« ask »).
    meilleure_limite_vente: CoursXof | None = None

    #: Horodatage de la donnée elle-même, tel qu'annoncé par la source.
    horodatage_donnee: AwareDatetime
    #: Horodatage de la collecte par le système.
    horodatage_collecte: AwareDatetime

    statut_fiabilite: StatutFiabilite = StatutFiabilite.FIABLE
    revision: int = Field(default=1, ge=1)
    commentaire: str | None = None

    @model_validator(mode="after")
    def _valider_coherence(self) -> Cotation:
        if self.horodatage_donnee > self.horodatage_collecte:
            raise ValueError(
                "horodatage_donnee est postérieur à horodatage_collecte : une donnée ne peut "
                "pas avoir été collectée avant d'exister."
            )

        cours_presents = [
            valeur
            for valeur in (self.ouverture, self.plus_haut, self.plus_bas, self.cloture)
            if valeur is not None
        ]
        if (
            self.plus_haut is not None
            and self.plus_bas is not None
            and self.plus_haut < self.plus_bas
        ):
            raise ValueError(
                f"plus_haut ({self.plus_haut}) inférieur à plus_bas ({self.plus_bas})."
            )
        if self.plus_haut is not None and cours_presents and self.plus_haut < max(cours_presents):
            raise ValueError(
                f"plus_haut ({self.plus_haut}) inférieur à l'ouverture ou à la clôture."
            )
        if self.plus_bas is not None and cours_presents and self.plus_bas > min(cours_presents):
            raise ValueError(f"plus_bas ({self.plus_bas}) supérieur à l'ouverture ou à la clôture.")

        match self.statut_seance:
            case StatutSeance.COTEE:
                if self.cloture is None:
                    raise ValueError("Une séance déclarée COTEE doit porter un cours de clôture.")
                if self.volume_titres <= 0:
                    raise ValueError(
                        "Une séance déclarée COTEE doit porter un volume strictement positif. "
                        "Sans transaction, utilisez SANS_TRANSACTION."
                    )
            case StatutSeance.SANS_TRANSACTION:
                if self.volume_titres != 0:
                    raise ValueError("Une séance SANS_TRANSACTION ne peut pas porter de volume.")
                if self.nb_transactions not in (None, 0):
                    raise ValueError(
                        "Une séance SANS_TRANSACTION ne peut pas porter de transactions."
                    )
            case StatutSeance.FERMEE:
                if cours_presents or self.volume_titres != 0:
                    raise ValueError("Une séance FERMEE ne peut porter ni cours ni volume.")
        return self

    # ------------------------------------------------------------------ dérivés

    @property
    def cle(self) -> tuple[str, date, str]:
        """Clé d'idempotence : ticker + date de séance + source."""
        return (self.ticker, self.date_seance, self.source)

    @property
    def cours_effectivement_traite(self) -> int | None:
        """Cours issu d'une transaction réelle, ``None`` sinon.

        C'est ce que doivent consommer les indicateurs : un cours de référence
        reconduit faute de transaction n'est pas un prix de marché.
        """
        return self.cloture if self.statut_seance is StatutSeance.COTEE else None

    @property
    def fourchette_relative(self) -> Decimal | None:
        """Largeur de la fourchette achat/vente rapportée à son milieu.

        Indicateur de liquidité : plus elle est large, moins le cours affiché est
        exécutable. ``None`` si le carnet n'est pas renseigné par la source.
        """
        if self.meilleure_limite_achat is None or self.meilleure_limite_vente is None:
            return None
        milieu = Decimal(self.meilleure_limite_achat + self.meilleure_limite_vente) / 2
        if milieu <= 0:
            return None
        ecart = Decimal(self.meilleure_limite_vente - self.meilleure_limite_achat)
        return ecart / milieu

    def age_minutes(self, reference: datetime) -> Decimal:
        """Âge de la donnée en minutes à l'instant ``reference``."""
        _exiger_aware(reference, "reference")
        secondes = (reference - self.horodatage_donnee).total_seconds()
        return Decimal(str(secondes)) / Decimal(60)

    #: Champs qui décrivent la donnée de marché elle-même. Les métadonnées de
    #: collecte (horodatages, révision, fiabilité) en sont exclues : deux
    #: collectes successives d'une même séance inchangée doivent produire la même
    #: empreinte, sinon chaque passage créerait une fausse « correction de cote ».
    CHAMPS_EMPREINTE: ClassVar[tuple[str, ...]] = (
        "ticker",
        "date_seance",
        "source",
        "statut_seance",
        "ouverture",
        "plus_haut",
        "plus_bas",
        "cloture",
        "cours_precedent",
        "volume_titres",
        "volume_xof",
        "nb_transactions",
        "meilleure_limite_achat",
        "meilleure_limite_vente",
    )

    def empreinte(self) -> str:
        """Empreinte stable du contenu de marché, pour détecter une correction."""
        charge = {champ: getattr(self, champ) for champ in self.CHAMPS_EMPREINTE}
        texte = json.dumps(charge, sort_keys=True, default=_serialiser, ensure_ascii=False)
        return hashlib.sha256(texte.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- opération sur titre


class OperationSurTitre(ModeleBrvm):
    """Événement affectant la continuité de la série de cours ou le nombre de titres.

    Convention de ratio, uniforme pour toutes les opérations sur le nombre de
    titres : ``ratio_numerateur`` actions **après** pour ``ratio_denominateur``
    actions **avant**.

    * division 1 action → 5 actions : ``5 / 1`` ;
    * regroupement 10 actions → 1 action : ``1 / 10`` ;
    * attribution d'1 action gratuite pour 10 détenues : ``11 / 10``.
    """

    identifiant: str = Field(min_length=1)
    ticker: Ticker
    type_ost: TypeOst
    #: Première séance où le titre cote sans le droit attaché.
    date_ex: date
    date_paiement: date | None = None
    montant_brut_par_action: MontantXof | None = None
    ratio_numerateur: int | None = Field(default=None, gt=0)
    ratio_denominateur: int | None = Field(default=None, gt=0)
    source: str = Field(min_length=1)
    commentaire: str | None = None

    @model_validator(mode="after")
    def _valider_coherence(self) -> OperationSurTitre:
        a_ratio = self.ratio_numerateur is not None and self.ratio_denominateur is not None
        if (self.ratio_numerateur is None) != (self.ratio_denominateur is None):
            raise ValueError(
                "Ratio incomplet : renseignez ratio_numerateur et ratio_denominateur ensemble."
            )
        match self.type_ost:
            case TypeOst.DIVIDENDE:
                if not self.montant_brut_par_action:
                    raise ValueError(
                        "Un dividende doit porter un montant brut par action strictement positif."
                    )
            case TypeOst.DIVISION | TypeOst.REGROUPEMENT | TypeOst.ATTRIBUTION_GRATUITE:
                if not a_ratio:
                    raise ValueError(
                        f"Une opération {self.type_ost.value} doit porter un ratio "
                        "(nombre d'actions après / nombre d'actions avant)."
                    )
        if self.date_paiement is not None and self.date_paiement < self.date_ex:
            raise ValueError("date_paiement antérieure à date_ex.")
        return self

    @property
    def facteur_titres(self) -> Decimal:
        """Multiplicateur du nombre de titres détenus (1 si l'opération n'en crée pas)."""
        if self.ratio_numerateur is None or self.ratio_denominateur is None:
            return Decimal(1)
        return Decimal(self.ratio_numerateur) / Decimal(self.ratio_denominateur)


# ------------------------------------------------------------------- transactions


class LigneFrais(ModeleBrvm):
    """Une ligne du décompte de frais, telle qu'elle figure sur l'avis d'opéré."""

    libelle: str = Field(min_length=1)
    base_calcul: BaseFrais
    #: Taux appliqué à l'assiette. ``None`` pour un forfait.
    taux: Decimal | None = Field(default=None, ge=0)
    #: Assiette retenue, en XOF.
    assiette: MontantXof
    #: Montant de la ligne, arrondi à l'unité XOF.
    montant: MontantXof

    @model_validator(mode="after")
    def _valider_coherence(self) -> LigneFrais:
        if self.base_calcul is BaseFrais.MONTANT_FIXE and self.taux is not None:
            raise ValueError("Une ligne forfaitaire ne porte pas de taux.")
        if self.base_calcul is not BaseFrais.MONTANT_FIXE and self.taux is None:
            raise ValueError(
                f"La ligne {self.libelle!r} est calculée sur {self.base_calcul.value} "
                "et doit porter un taux."
            )
        return self


class Transaction(ModeleBrvm):
    """Achat ou vente de titres exécuté sur le portefeuille."""

    identifiant: str = Field(min_length=1)
    ticker: Ticker
    date_operation: date
    date_reglement: date | None = None
    sens: SensOperation
    quantite: Quantite
    cours_unitaire: CoursXof
    frais: tuple[LigneFrais, ...] = ()
    reference_sgi: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _valider_dates(self) -> Transaction:
        if self.date_reglement is not None and self.date_reglement < self.date_operation:
            raise ValueError("date_reglement antérieure à date_operation.")
        return self

    @property
    def montant_brut(self) -> int:
        """Quantité × cours, hors frais."""
        return self.quantite * self.cours_unitaire

    @property
    def total_frais(self) -> int:
        """Somme des lignes de frais, chacune déjà arrondie à l'unité."""
        return sum(ligne.montant for ligne in self.frais)

    @property
    def montant_net(self) -> int:
        """Décaissement pour un achat, encaissement pour une vente."""
        if self.sens is SensOperation.ACHAT:
            return self.montant_brut + self.total_frais
        return self.montant_brut - self.total_frais


class FluxEspece(ModeleBrvm):
    """Mouvement d'espèces hors achat/vente : apport, retrait, dividende, frais de garde."""

    identifiant: str = Field(min_length=1)
    date_flux: date
    type_flux: TypeFluxEspece
    #: Renseigné pour un dividende ; absent pour un apport ou un retrait.
    ticker: Ticker | None = None
    montant_brut: MontantXof
    retenue_fiscale: MontantXof = 0
    frais: MontantXof = 0
    source: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _valider_coherence(self) -> FluxEspece:
        if self.type_flux is TypeFluxEspece.DIVIDENDE and self.ticker is None:
            raise ValueError("Un dividende doit être rattaché à une valeur (ticker).")
        if self.retenue_fiscale + self.frais > self.montant_brut:
            raise ValueError("Retenue et frais dépassent le montant brut du flux.")
        return self

    @property
    def montant_net(self) -> int:
        return self.montant_brut - self.retenue_fiscale - self.frais


class Valorisation(ModeleBrvm):
    """Photographie du portefeuille pour une séance, telle qu'elle sera relue.

    Sans cette série, ni la performance ni le repli ne se mesurent : c'est elle
    qui manquait, et qui rendait `risque.drawdown_alerte` inopérant.

    `especes` et `actif_total` sont **facultatifs**. Sans apport déclaré, le
    solde n'est pas connaissable, et l'écrire à zéro serait une affirmation
    fausse. Le motif accompagne alors l'absence. Une valorisation sans espèces
    reste utile : elle mesure les titres.
    """

    date_seance: date
    valeur_titres: MontantXof
    cout_total: MontantXof
    plus_value_brute: int
    nb_lignes: int = Field(ge=0)
    nb_non_valorisees: int = Field(default=0, ge=0)
    horodatage_calcul: AwareDatetime
    especes: int | None = None
    actif_total: int | None = None
    motif_especes: str | None = None

    @model_validator(mode="after")
    def _valider_coherence(self) -> Valorisation:
        if self.nb_non_valorisees > self.nb_lignes:
            raise ValueError(
                "Plus de lignes non valorisées que de lignes : "
                f"{self.nb_non_valorisees} sur {self.nb_lignes}."
            )
        if (self.especes is None) != (self.actif_total is None):
            raise ValueError(
                "Espèces et actif total vont ensemble : l'actif total est la somme "
                "des titres et des espèces, il n'a pas de sens sans elles."
            )
        if self.especes is None and self.motif_especes is None:
            raise ValueError(
                "Un solde d'espèces absent doit porter son motif : une absence sans "
                "raison ne se distingue pas d'un oubli."
            )
        if self.actif_total is not None and self.actif_total != self.valeur_titres + (
            self.especes or 0
        ):
            raise ValueError(
                "L'actif total ne correspond pas à la somme des titres et des espèces."
            )
        return self


# ------------------------------------------------------------- journal et anomalies


class Anomalie(ModeleBrvm):
    """Anomalie détectée à l'ingestion. Journalisée, jamais corrigée en silence."""

    identifiant: str = Field(min_length=1)
    source: str = Field(min_length=1)
    type_anomalie: str = Field(min_length=1)
    gravite: GraviteAnomalie
    message: str = Field(min_length=1)
    ticker: str | None = None
    date_seance: date | None = None
    #: Donnée brute fautive, conservée telle quelle pour investigation.
    charge_utile: dict[str, Any] = Field(default_factory=dict)
    detectee_le: AwareDatetime
    resolue: bool = False


class JournalCollecte(ModeleBrvm):
    """Trace d'un cycle d'ingestion, pour l'audit et le suivi de fraîcheur."""

    identifiant: str = Field(min_length=1)
    source: str = Field(min_length=1)
    debut: AwareDatetime
    fin: AwareDatetime | None = None
    statut: StatutCollecte
    nb_lignes_lues: int = Field(default=0, ge=0)
    nb_lignes_ecrites: int = Field(default=0, ge=0)
    nb_anomalies: int = Field(default=0, ge=0)
    message: str | None = None

    @model_validator(mode="after")
    def _valider_dates(self) -> JournalCollecte:
        if self.fin is not None and self.fin < self.debut:
            raise ValueError("La fin de collecte précède son début.")
        return self
