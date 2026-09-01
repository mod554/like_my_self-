"""Validation walk-forward : mesurer sur ce qui n'a pas servi à régler.

Optimiser des paramètres sur tout l'historique puis présenter le résultat comme
une performance est la faute la plus commune de l'analyse technique. Avec assez
de paramètres, on trouve toujours une combinaison qui aurait fonctionné ; elle ne
dit rien de la suivante.

Le walk-forward découpe l'historique en fenêtres successives. Sur chaque fenêtre,
les paramètres sont choisis sur la partie **apprentissage**, puis appliqués tels
quels à la partie **validation**, qui n'a pas servi au choix. Seuls les résultats
de validation comptent — l'écart entre les deux mesure exactement ce que
l'optimisation avait d'illusoire.

Un écart important n'invalide pas la stratégie : il dit que ses paramètres ne
sont pas stables, ce qui est une information en soi.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.indicators.serie import SerieTechnique
from brvm.portfolio.frais import MoteurFrais
from brvm.utils.erreurs import ErreurDonneesInsuffisantes

from .metriques import Metriques, calculer_metriques
from .moteur import MoteurBacktest
from .strategie import Strategie

#: Une fabrique reçoit un jeu de paramètres et rend une stratégie neuve.
FabriqueStrategie = Callable[[Mapping[str, int]], Strategie]


@dataclass(frozen=True, slots=True)
class Fenetre:
    """Un découpage apprentissage / validation."""

    numero: int
    debut_apprentissage: date
    fin_apprentissage: date
    debut_validation: date
    fin_validation: date


@dataclass(frozen=True, slots=True)
class ResultatFenetre:
    """Ce qu'a donné une fenêtre, des deux côtés de la cloison."""

    fenetre: Fenetre
    parametres_retenus: Mapping[str, int]
    metriques_apprentissage: Metriques
    metriques_validation: Metriques

    @property
    def ecart_de_rendement(self) -> Decimal:
        """Écart entre le rendement optimisé et celui réellement obtenu ensuite.

        Positif : l'apprentissage promettait davantage que la validation n'a tenu.
        """
        return (
            self.metriques_apprentissage.rendement_total - self.metriques_validation.rendement_total
        )


@dataclass(frozen=True, slots=True)
class ResultatWalkForward:
    """Synthèse d'une validation walk-forward."""

    fenetres: tuple[ResultatFenetre, ...]
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rendement_valide(self) -> Decimal | None:
        """Rendement composé des seules périodes de validation."""
        if not self.fenetres:
            return None
        cumul = Decimal(1)
        for resultat in self.fenetres:
            cumul *= Decimal(1) + resultat.metriques_validation.rendement_total
        return (cumul - Decimal(1)).quantize(Decimal("0.000001"))

    @property
    def rendement_optimise(self) -> Decimal | None:
        """Rendement composé des périodes d'apprentissage. À ne jamais présenter seul."""
        if not self.fenetres:
            return None
        cumul = Decimal(1)
        for resultat in self.fenetres:
            cumul *= Decimal(1) + resultat.metriques_apprentissage.rendement_total
        return (cumul - Decimal(1)).quantize(Decimal("0.000001"))

    @property
    def parametres_stables(self) -> bool:
        """Vrai si toutes les fenêtres ont retenu les mêmes paramètres.

        Des paramètres qui changent à chaque fenêtre signalent un réglage qui suit
        le bruit plutôt qu'une régularité.
        """
        if len(self.fenetres) < 2:
            return True
        premier = dict(self.fenetres[0].parametres_retenus)
        return all(dict(f.parametres_retenus) == premier for f in self.fenetres[1:])

    def resume(self) -> str:
        lignes = [
            f"{len(self.fenetres)} fenêtre(s) de validation",
            f"Rendement en validation{'':.<26}{self.rendement_valide:>15.2%}"
            if self.rendement_valide is not None
            else "Rendement en validation : non mesuré",
            f"Rendement en apprentissage (à titre indicatif){'':.<4}"
            f"{self.rendement_optimise:>15.2%}"
            if self.rendement_optimise is not None
            else "",
            "Paramètres stables d'une fenêtre à l'autre : "
            + ("oui" if self.parametres_stables else "NON — réglage instable"),
        ]
        for resultat in self.fenetres:
            lignes.append(
                f"  fenêtre {resultat.fenetre.numero} "
                f"({resultat.fenetre.debut_validation} → "
                f"{resultat.fenetre.fin_validation}) : "
                f"validation {resultat.metriques_validation.rendement_total:.2%}, "
                f"écart avec l'apprentissage {resultat.ecart_de_rendement:+.2%}, "
                f"paramètres {dict(resultat.parametres_retenus)}"
            )
        return "\n".join(ligne for ligne in lignes if ligne)


def decouper(seances: Sequence[date], apprentissage: int, validation: int) -> list[Fenetre]:
    """Découpe le calendrier en fenêtres glissantes successives.

    Chaque fenêtre avance de la longueur de sa partie validation : les périodes de
    validation se suivent sans se chevaucher, et couvrent l'historique une fois.
    """
    if apprentissage < 2 or validation < 1:
        raise ErreurDonneesInsuffisantes(
            "Fenêtres walk-forward trop courtes pour simuler quoi que ce soit.",
            apprentissage=apprentissage,
            validation=validation,
        )
    fenetres: list[Fenetre] = []
    debut = 0
    numero = 1
    while debut + apprentissage + validation <= len(seances):
        fin_apprentissage = debut + apprentissage - 1
        fin_validation = fin_apprentissage + validation
        fenetres.append(
            Fenetre(
                numero=numero,
                debut_apprentissage=seances[debut],
                fin_apprentissage=seances[fin_apprentissage],
                debut_validation=seances[fin_apprentissage + 1],
                fin_validation=seances[fin_validation],
            )
        )
        debut += validation
        numero += 1
    return fenetres


def valider(
    series: Mapping[str, SerieTechnique],
    fabrique: FabriqueStrategie,
    grille: Sequence[Mapping[str, int]],
    configuration: Configuration,
    moteur_frais: MoteurFrais | None = None,
) -> ResultatWalkForward:
    """Choisit les paramètres sur l'apprentissage, les mesure sur la validation.

    Args:
        series: séries techniques des valeurs simulées.
        fabrique: construit une stratégie neuve à partir d'un jeu de paramètres.
            Elle doit rendre un objet vierge à chaque appel : une stratégie qui
            garde un état d'une simulation à l'autre fausse tout.
        grille: jeux de paramètres à comparer.
        configuration: longueurs des fenêtres, frais, hypothèses d'exécution.

    Raises:
        ErreurDonneesInsuffisantes: historique trop court pour une seule fenêtre,
            ou grille vide.
    """
    if not grille:
        raise ErreurDonneesInsuffisantes("Grille de paramètres vide : il n'y a rien à comparer.")

    moteur = MoteurBacktest(series, configuration, moteur_frais)
    seances = moteur.calendrier_commun
    reglages = configuration.backtest
    fenetres = decouper(
        seances, reglages.walk_forward_apprentissage, reglages.walk_forward_validation
    )

    if not fenetres:
        raise ErreurDonneesInsuffisantes(
            f"Historique de {len(seances)} séances insuffisant pour une fenêtre "
            f"d'apprentissage de {reglages.walk_forward_apprentissage} séances suivie "
            f"d'une validation de {reglages.walk_forward_validation}. Réduisez les "
            "fenêtres, ou collectez davantage d'historique — mais réduire les fenêtres "
            "rend le réglage plus sensible au bruit.",
            seances=len(seances),
        )

    resultats: list[ResultatFenetre] = []
    avertissements: list[str] = []

    for fenetre in fenetres:
        meilleur: tuple[Mapping[str, int], Metriques] | None = None
        for parametres in grille:
            metriques = calculer_metriques(
                moteur.executer(
                    fabrique(parametres),
                    fenetre.debut_apprentissage,
                    fenetre.fin_apprentissage,
                ),
                configuration,
            )
            if meilleur is None or metriques.rendement_total > meilleur[1].rendement_total:
                meilleur = (parametres, metriques)

        assert meilleur is not None  # la grille est non vide
        parametres, metriques_apprentissage = meilleur
        metriques_validation = calculer_metriques(
            moteur.executer(fabrique(parametres), fenetre.debut_validation, fenetre.fin_validation),
            configuration,
        )
        resultats.append(
            ResultatFenetre(
                fenetre=fenetre,
                parametres_retenus=dict(parametres),
                metriques_apprentissage=metriques_apprentissage,
                metriques_validation=metriques_validation,
            )
        )

    resultat = ResultatWalkForward(fenetres=tuple(resultats))
    if not resultat.parametres_stables:
        avertissements.append(
            "Les paramètres retenus changent d'une fenêtre à l'autre : le réglage suit "
            "le bruit plus qu'une régularité. Se fier au dernier jeu retenu revient à "
            "parier qu'il tiendra, ce que l'historique dément."
        )
    optimise = resultat.rendement_optimise
    valide = resultat.rendement_valide
    if optimise is not None and valide is not None and optimise > valide:
        avertissements.append(
            f"L'apprentissage promettait {optimise:.2%}, la validation a donné "
            f"{valide:.2%}. Seul le second chiffre a une valeur ; l'écart mesure ce que "
            "l'optimisation avait d'illusoire."
        )
    return ResultatWalkForward(fenetres=tuple(resultats), avertissements=tuple(avertissements))
