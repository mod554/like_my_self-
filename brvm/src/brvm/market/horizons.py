"""Classement de la cote selon un profil déclaré.

Un classement n'est pas une recommandation. Il ordonne des valeurs selon des
critères que **vous** avez pondérés, sur des données passées. Il ne dit pas ce
qui va monter — rien ici ne le sait — et le vocabulaire s'y tient : on classe,
on ne conseille pas.

Deux garde-fous, tous deux propres à cette place :

* **la confiance de la donnée est une porte, pas un critère.** Une valeur au
  momentum superbe qui cote trois fois par mois n'est pas une demi-occasion :
  elle n'est pas jouable, et son score est annulé plutôt que pondéré ;
* **un profil qui exige des fondamentaux ne classe rien sans eux.** Il ne
  retombe pas sur le prix : classer un horizon de plusieurs années sur la seule
  tendance des cours serait une fabrication déguisée en analyse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from brvm.config.modeles import CRITERES_FONDAMENTAUX, ConfigHorizon, Configuration
from brvm.market.analyse import AnalyseValeur
from brvm.market.criteres import Critere, Score, composer, note_croissante


@dataclass(frozen=True, slots=True)
class Rang:
    """Une valeur dans un classement, avec de quoi contester sa place."""

    ticker: str
    analyse: AnalyseValeur
    score: Score

    @property
    def valeur(self) -> Decimal | None:
        return self.score.valeur


@dataclass(frozen=True, slots=True)
class Classement:
    """Le résultat d'un profil sur toute la cote."""

    horizon: str
    libelle: str
    description: str
    classes: tuple[Rang, ...] = ()
    #: Valeurs écartées, chacune avec la raison. Jamais silencieusement omises :
    #: sur cette place, les écartées sont souvent la majorité, et savoir
    #: pourquoi vaut mieux que de les voir disparaître.
    ecartes: tuple[Rang, ...] = ()
    avertissements: tuple[str, ...] = ()

    @property
    def couverture_cote(self) -> str:
        total = len(self.classes) + len(self.ecartes)
        return f"{len(self.classes)}/{total}"

    def tete(self, combien: int) -> tuple[Rang, ...]:
        return self.classes[:combien]


def cause_confiance_basse(analyse: AnalyseValeur) -> str:
    """Nomme la composante qui tire la confiance vers le bas.

    La confiance est un **produit** de trois facteurs. Attribuer d'office une
    confiance faible à des trous dans la série serait souvent faux : une valeur
    peut coter toutes les séances et rester peu profonde. Envoyer chercher au
    mauvais endroit vaut à peine mieux que de ne rien dire.
    """
    composantes = (
        (
            analyse.assiduite,
            f"assiduité {analyse.assiduite:.0%} — {analyse.seances_cotees} séance(s) "
            f"cotée(s) sur {analyse.seances_attendues}",
        ),
        (
            analyse.profondeur,
            f"profondeur {analyse.profondeur:.0%} — "
            + (
                # « Non publié » et « faible » ne se corrigent pas de la même
                # façon : l'un se règle en changeant de source, l'autre non.
                "la source ne publie aucun montant échangé, et la profondeur du "
                "marché est donc inconnue. Elle est comptée comme nulle faute de "
                "pouvoir l'estimer : ce n'est pas un jugement sur la valeur"
                if not analyse.critere("volume").mesurable
                else "le montant échangé est faible devant le volume de référence "
                "déclaré dans `indicateurs`"
            ),
        ),
        (
            analyse.etroitesse,
            f"étroitesse {analyse.etroitesse:.0%} — la fourchette achat/vente est "
            "large devant la référence déclarée",
        ),
    )
    _, libelle = min(composantes, key=lambda couple: couple[0])
    return f"composante la plus basse : {libelle}"


def _porte_confiance(analyse: AnalyseValeur, profil: ConfigHorizon) -> Critere:
    """La confiance de la donnée, en porte multiplicative.

    En dessous du seuil déclaré, la note est nulle : le score entier s'annule.
    C'est le comportement voulu — un classement fondé sur une donnée peu fiable
    ordonnerait du bruit.
    """
    if analyse.confiance < profil.confiance_minimale:
        return Critere.absent(
            "confiance",
            "Confiance de la donnée",
            f"{analyse.confiance:.0%}, sous le seuil de "
            f"{profil.confiance_minimale:.0%} — {cause_confiance_basse(analyse)}",
        )
    return Critere(
        nom="confiance",
        libelle="Confiance de la donnée",
        valeur=analyse.confiance,
        unite="fraction",
        note=analyse.confiance,
    )


def _porte_liquidite(analyse: AnalyseValeur, configuration: Configuration) -> Critere:
    """Capacité d'accueil d'une ligne, en porte multiplicative.

    Une valeur qui ne peut pas absorber le montant minimal d'une ligne n'entre
    dans aucun classement : ce n'est pas une question de qualité, c'est une
    impossibilité d'exécution.
    """
    if analyse.cours is None or analyse.cours <= 0:
        return Critere.absent("liquidite", "Capacité d'accueil", "aucun cours réellement coté")
    if analyse.taille_tenable <= 0:
        return Critere.absent(
            "liquidite",
            "Capacité d'accueil",
            analyse.motif_taille or "aucune taille de position défendable",
        )
    montant_tenable = Decimal(analyse.taille_tenable * analyse.cours)
    minimum = Decimal(configuration.allocation.montant_minimum_ligne)
    if montant_tenable < minimum:
        return Critere.absent(
            "liquidite",
            "Capacité d'accueil",
            f"une position tenable vaut au plus {montant_tenable:.0f} XOF, sous le "
            f"minimum de {minimum:.0f} XOF que vous avez déclaré pour une ligne",
        )
    return Critere(
        nom="liquidite",
        libelle="Capacité d'accueil",
        valeur=montant_tenable / minimum,
        unite="×",
        note=note_croissante(montant_tenable / minimum, Decimal(0), Decimal(5)),
    )


def classer(
    analyses: Sequence[AnalyseValeur],
    profil: ConfigHorizon,
    horizon: str,
    configuration: Configuration,
) -> Classement:
    """Applique un profil à toute la cote analysée."""
    inconnus = set(profil.poids) - {critere for analyse in analyses for critere in analyse.criteres}
    avertissements: list[str] = []
    if inconnus and analyses:
        avertissements.append(
            "Critères pondérés mais jamais produits par l'analyse : "
            + ", ".join(sorted(inconnus))
            + ". Vérifiez `analyse.horizons` dans la configuration."
        )

    classes: list[Rang] = []
    ecartes: list[Rang] = []

    for analyse in analyses:
        if profil.exige_fondamentaux and analyse.exercice is None:
            ecartes.append(
                Rang(
                    ticker=analyse.ticker,
                    analyse=analyse,
                    score=Score(
                        valeur=None,
                        motif_absent=(
                            "aucune donnée fondamentale saisie. Ce profil ne "
                            "retombe pas sur le prix : classer plusieurs années "
                            "sur la seule tendance des cours n'aurait pas de sens."
                        ),
                    ),
                )
            )
            continue

        ponderes = [(analyse.critere(nom), poids) for nom, poids in profil.poids.items()]
        score = composer(
            ponderes,
            portes=(
                _porte_confiance(analyse, profil),
                _porte_liquidite(analyse, configuration),
            ),
            couverture_minimale=profil.couverture_minimale,
        )
        rang = Rang(ticker=analyse.ticker, analyse=analyse, score=score)
        (classes if score.classable else ecartes).append(rang)

    # Tri décroissant sur le score, puis alphabétique : deux valeurs à score égal
    # ne doivent pas changer de place d'une exécution à l'autre.
    classes.sort(key=lambda rang: (-(rang.valeur or Decimal(0)), rang.ticker))
    ecartes.sort(key=lambda rang: rang.ticker)

    if profil.exige_fondamentaux and not classes:
        avertissements.append(
            "Aucune valeur classée : ce profil exige des données fondamentales, "
            "et le référentiel est vide. Renseignez "
            "`config/fondamentaux.csv` depuis les rapports annuels."
        )

    return Classement(
        horizon=horizon,
        libelle=profil.libelle,
        description=profil.description,
        classes=tuple(classes),
        ecartes=tuple(ecartes),
        avertissements=tuple(avertissements),
    )


def classer_tous(
    analyses: Sequence[AnalyseValeur], configuration: Configuration
) -> dict[str, Classement]:
    """Applique tous les profils déclarés."""
    return {
        nom: classer(analyses, profil, nom, configuration)
        for nom, profil in configuration.analyse.horizons.items()
    }


def criteres_fondamentaux_manquants(analyses: Sequence[AnalyseValeur]) -> list[str]:
    """Valeurs sans aucune donnée fondamentale, pour savoir quoi saisir d'abord."""
    return sorted(
        analyse.ticker
        for analyse in analyses
        if all(not analyse.critere(nom).mesurable for nom in CRITERES_FONDAMENTAUX)
    )


def resume_couverture(analyses: Sequence[AnalyseValeur]) -> Mapping[str, int]:
    """Combien de valeurs mesurent chaque critère. Sert à voir ce qui bloque."""
    compte: dict[str, int] = {}
    for analyse in analyses:
        for nom, critere in analyse.criteres.items():
            compte[nom] = compte.get(nom, 0) + (1 if critere.mesurable else 0)
    return dict(sorted(compte.items()))
