"""Score de confiance fondé sur la liquidité.

Sur un marché où une valeur peut ne pas coter pendant une semaine, la question
n'est pas seulement « que dit l'indicateur ? » mais « cet indicateur a-t-il eu de
quoi dire quelque chose ? ». Le score répond à la seconde.

Il combine trois composantes, toutes ramenées à l'intervalle [0, 1] et toutes
rapportées séparément — un score agrégé qu'on ne peut pas décomposer n'apprend
rien :

* **assiduité** : part de séances réellement cotées dans la fenêtre ;
* **profondeur** : montant quotidien moyen échangé, rapporté au montant que la
  configuration considère comme suffisant ;
* **étroitesse** : largeur moyenne de la fourchette achat/vente, rapportée à la
  largeur que la configuration considère comme acceptable.

Le score est leur **produit**, non leur moyenne : une valeur qui cote tous les
jours mais qu'on ne peut acheter qu'avec 20 % d'écart au carnet n'est pas
« moyennement liquide », elle est illiquide. Une composante proche de zéro doit
tirer le tout vers zéro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Final

from brvm.config.modeles import Configuration
from brvm.domain.monnaie import PRECISION_INTERNE

if TYPE_CHECKING:  # pragma: no cover - uniquement pour le typage
    from brvm.indicators.serie import SerieTechnique

#: Seuils d'affichage du niveau de confiance. Bornes de présentation, sans effet
#: sur le calcul : elles servent à ce qu'un écran ne montre pas « 0.41 » sans dire
#: ce que 0,41 vaut.
SEUIL_ELEVEE: Final[Decimal] = Decimal("0.66")
SEUIL_MOYENNE: Final[Decimal] = Decimal("0.33")

_DECIMALES: Final[Decimal] = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ScoreConfiance:
    """Confiance accordée à un calcul, et ce qui la compose."""

    valeur: Decimal
    assiduite: Decimal
    profondeur: Decimal
    etroitesse: Decimal
    seances_cotees: int
    seances_attendues: int
    montant_moyen_xof: Decimal
    fourchette_moyenne: Decimal | None
    commentaires: tuple[str, ...] = field(default_factory=tuple)

    @property
    def niveau(self) -> str:
        if self.valeur >= SEUIL_ELEVEE:
            return "élevée"
        if self.valeur >= SEUIL_MOYENNE:
            return "moyenne"
        return "faible"

    def resume(self) -> str:
        return (
            f"confiance {self.niveau} ({self.valeur}) — assiduité {self.assiduite}, "
            f"profondeur {self.profondeur}, étroitesse {self.etroitesse} "
            f"[{self.seances_cotees}/{self.seances_attendues} séances cotées]"
        )


def _borner(valeur: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), valeur)).quantize(_DECIMALES)


def evaluer_confiance(
    serie: SerieTechnique, configuration: Configuration, fenetre: int | None = None
) -> ScoreConfiance:
    """Évalue la liquidité de la fenêtre la plus récente d'une série.

    Args:
        serie: série technique de la valeur.
        configuration: fournit les références de volume et de fourchette.
        fenetre: nombre de séances considérées. Par défaut, celle configurée pour
            le volume moyen.
    """
    reglages = configuration.indicateurs
    taille = fenetre if fenetre is not None else reglages.fenetre_volume_moyen
    barres = serie.barres[-taille:] if taille else serie.barres
    attendues = len(barres)
    cotees = sum(1 for barre in barres if barre.cotee)
    commentaires: list[str] = []

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        assiduite = _borner(Decimal(cotees) / Decimal(attendues)) if attendues else Decimal(0)
        if attendues == 0:
            commentaires.append("Fenêtre vide : aucune séance à évaluer.")

        montant = serie.montant_moyen_xof(taille)
        if montant == 0:
            profondeur = Decimal(0)
            commentaires.append(
                "Aucun montant échangé publié sur la fenêtre : la profondeur du marché "
                "est inconnue et comptée comme nulle, faute de pouvoir l'estimer."
            )
        else:
            profondeur = _borner(montant / Decimal(reglages.volume_reference_xof))

        fourchette = serie.fourchette_moyenne(taille)
        if fourchette is None:
            etroitesse = Decimal(1)
            commentaires.append(
                "Fourchette achat/vente non publiée par la source : elle n'entre pas "
                "dans le score, qui est donc optimiste. La largeur du carnet est ce qui "
                "sépare un cours affiché d'un cours exécutable."
            )
        elif fourchette <= reglages.fourchette_reference:
            etroitesse = Decimal(1)
        else:
            etroitesse = _borner(Decimal(reglages.fourchette_reference) / fourchette)

        valeur = _borner(assiduite * profondeur * etroitesse)

    if assiduite < reglages.ratio_minimum_seances_cotees:
        commentaires.append(
            f"Seulement {cotees} séance(s) cotée(s) sur {attendues} : sous le seuil "
            f"configuré ({reglages.ratio_minimum_seances_cotees:.0%}), les indicateurs "
            "refuseront de se calculer."
        )

    return ScoreConfiance(
        valeur=valeur,
        assiduite=assiduite,
        profondeur=profondeur,
        etroitesse=etroitesse,
        seances_cotees=cotees,
        seances_attendues=attendues,
        montant_moyen_xof=montant,
        fourchette_moyenne=fourchette,
        commentaires=tuple(commentaires),
    )
