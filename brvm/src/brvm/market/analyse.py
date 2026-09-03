"""Analyse d'une valeur : tous les critères mesurables, et les autres nommés.

Cette couche ne classe pas. Elle mesure — et dit, critère par critère, ce qui
n'a pas pu l'être et pourquoi. Le classement, c'est :mod:`brvm.market.horizons`,
qui pondère ces mêmes critères selon un profil déclaré.

La séparation compte : les mesures sont les mêmes pour tout le monde, les poids
appartiennent à l'utilisateur. Mélanger les deux rendrait impossible de savoir
si une valeur monte dans un classement parce qu'elle a changé ou parce que les
poids ont changé.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext

from brvm.config.modeles import (
    CRITERES_FONDAMENTAUX,
    ConfigBornes,
    Configuration,
)
from brvm.domain.modeles import Instrument
from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.resultats import ResultatIndicateur
from brvm.indicators.serie import OrigineValeur, SerieTechnique
from brvm.market.criteres import (
    Critere,
    note_centree,
    note_croissante,
    note_decroissante,
)
from brvm.market.fondamentaux import (
    Fondamentaux,
    Ratios,
    calculer_ratios,
    regularite_dividende,
)
from brvm.risk.controles import dimensionner
from brvm.risk.mesures import calculer_volatilite

#: Les noms de critères vivent dans la configuration : c'est elle qui refuse un
#: poids portant un nom inconnu, et il ne peut y avoir qu'une seule liste.


@dataclass(frozen=True, slots=True)
class AnalyseValeur:
    """Tout ce que le système sait dire d'une valeur, à un instant donné."""

    ticker: str
    instrument: Instrument | None
    cours: int | None
    date_cours: date | None
    #: Confiance de la donnée : assiduité × profondeur × étroitesse.
    confiance: Decimal
    niveau_confiance: str
    seances_cotees: int
    seances_attendues: int
    #: Quantité maximale tenable au regard du volume échangé.
    taille_tenable: int
    motif_taille: str | None
    #: Composantes de la confiance, qui est leur produit. Les porter séparément
    #: permet de nommer celle qui borne : dire « série trouée » quand c'est le
    #: montant échangé qui manque enverrait chercher au mauvais endroit.
    profondeur: Decimal = Decimal(0)
    etroitesse: Decimal = Decimal(0)
    criteres: Mapping[str, Critere] = field(default_factory=dict)
    ratios: Ratios | None = None
    exercice: Fondamentaux | None = None
    avertissements: tuple[str, ...] = ()

    @property
    def assiduite(self) -> Decimal:
        if not self.seances_attendues:
            return Decimal(0)
        return Decimal(self.seances_cotees) / Decimal(self.seances_attendues)

    def critere(self, nom: str) -> Critere:
        return self.criteres.get(nom, Critere.absent(nom, nom, "critère non produit par l'analyse"))


def dernier_cours_cote(serie: SerieTechnique) -> int | None:
    """Dernier cours provenant d'une séance **réellement cotée**.

    Pas le dernier cours de la série : celui-ci peut être un report, et fonder
    un ratio ou une note dessus reviendrait à mesurer un cours qui n'a jamais
    été échangé.
    """
    for barre in reversed(serie.barres):
        if barre.origine is OrigineValeur.COTEE and barre.cloture is not None:
            return int(barre.cloture)
    return None


def _derniere_valeur(resultat: ResultatIndicateur) -> tuple[Decimal | None, str | None]:
    """Dernier point d'un indicateur, ou le motif de son refus de se calculer.

    Le type est explicite et non `object` : une lecture par ``getattr`` sur un
    attribut mal nommé rendrait un critère silencieusement absent, sans qu'aucun
    outil ne le signale. C'est exactement ce qui était arrivé au critère de repli.
    """
    dernier = resultat.dernier
    if dernier is None:
        return None, "aucun point calculé"
    if dernier.valeur is None:
        return None, dernier.motif_refus or "indicateur non disponible sur la fenêtre"
    valeur: Decimal = dernier.valeur
    return valeur, None


def _critere_momentum(indicateurs: Indicateurs, bornes: ConfigBornes) -> Critere:
    valeur, motif = _derniere_valeur(indicateurs.momentum())
    if valeur is None:
        return Critere.absent("momentum", "Momentum", motif or "non calculable")
    return Critere(
        nom="momentum",
        libelle="Momentum",
        valeur=valeur,
        unite="fraction",
        note=note_croissante(valeur, bornes.momentum_plancher, bornes.momentum_plafond),
    )


def _critere_tendance(indicateurs: Indicateurs, serie: SerieTechnique) -> Critere:
    """Position du cours par rapport à sa moyenne longue.

    Note binaire adoucie : le rapport cours / moyenne, ramené entre 0.8 et 1.2.
    Un cours 20 % au-dessus de sa moyenne longue sature ; au-delà, l'écart
    signale surtout un emballement.
    """
    moyenne, motif = _derniere_valeur(
        indicateurs.moyenne_simple(indicateurs.reglages.fenetre_mm_longue)
    )
    cours = dernier_cours_cote(serie)
    if moyenne is None or moyenne <= 0:
        return Critere.absent("tendance", "Tendance", motif or "moyenne non calculable")
    if cours is None:
        return Critere.absent(
            "tendance", "Tendance", "aucune séance réellement cotée dans la série"
        )
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        rapport = Decimal(cours) / moyenne
    return Critere(
        nom="tendance",
        libelle="Cours / moyenne longue",
        valeur=rapport,
        unite="×",
        note=note_croissante(rapport, Decimal("0.8"), Decimal("1.2")),
    )


def _critere_rsi(indicateurs: Indicateurs, bornes: ConfigBornes) -> Critere:
    valeur, motif = _derniere_valeur(indicateurs.rsi())
    if valeur is None:
        return Critere.absent("regime_rsi", "Régime RSI", motif or "non calculable")
    return Critere(
        nom="regime_rsi",
        libelle="Régime RSI",
        valeur=valeur,
        unite="",
        note=note_centree(valeur, bornes.rsi_cible, bornes.rsi_tolerance),
    )


def _critere_repli(
    indicateurs: Indicateurs, serie: SerieTechnique, bornes: ConfigBornes
) -> Critere:
    """Écart au plus haut glissant. Plus le cours est bas dans son canal, mieux
    il est noté — c'est un critère de point d'entrée, pas de qualité."""
    plus_haut, motif = _derniere_valeur(indicateurs.extremes().plus_haut)
    cours = dernier_cours_cote(serie)
    if plus_haut is None:
        return Critere.absent("repli", "Écart au plus haut", motif or "extrêmes non calculables")
    if cours is None:
        return Critere.absent("repli", "Écart au plus haut", "aucune séance réellement cotée")
    if plus_haut <= 0:
        return Critere.absent("repli", "Écart au plus haut", "plus-haut nul")
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        ecart = (plus_haut - Decimal(cours)) / plus_haut
    return Critere(
        nom="repli",
        libelle="Écart au plus haut",
        valeur=ecart,
        unite="fraction",
        note=note_croissante(ecart, Decimal(0), bornes.ecart_extreme_plafond),
    )


def _critere_volatilite(
    serie: SerieTechnique, configuration: Configuration, bornes: ConfigBornes
) -> Critere:
    # La fenêtre déclarée est passée explicitement : sans elle, la volatilité se
    # mesurait sur tout l'historique disponible, et le réglage de l'utilisateur
    # ne faisait rien — sans le moindre message.
    mesure = calculer_volatilite(
        serie,
        configuration.risque.seances_par_an,
        fenetre=configuration.risque.fenetre_volatilite,
    )
    if mesure.valeur is None:
        return Critere.absent(
            "volatilite", "Volatilité", mesure.motif_indisponible or "non calculable"
        )
    annualisee = mesure.annualisee if mesure.annualisee is not None else mesure.valeur
    return Critere(
        nom="volatilite",
        libelle="Volatilité annualisée",
        valeur=annualisee,
        unite="fraction",
        note=note_decroissante(annualisee, Decimal(0), bornes.volatilite_plafond),
    )


def _critere_volume(serie: SerieTechnique, configuration: Configuration) -> Critere:
    """Montant moyen échangé par séance, rapporté au minimum d'une ligne.

    Une valeur qui échange moins que le montant minimal d'une ligne ne peut pas
    accueillir une position : la note tombe à zéro, ce qui n'est pas un jugement
    mais une impossibilité pratique.
    """
    fenetre = configuration.indicateurs.fenetre_volume_moyen
    montant = serie.montant_moyen_xof(fenetre)
    if montant <= 0:
        return Critere.absent(
            "volume",
            "Montant échangé",
            "aucun montant échangé sur la fenêtre",
        )
    minimum = Decimal(configuration.allocation.montant_minimum_ligne)
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        rapport = montant / minimum
    return Critere(
        nom="volume",
        libelle="Montant échangé / ligne minimale",
        valeur=rapport,
        unite="×",
        note=note_croissante(rapport, Decimal(0), Decimal(10)),
    )


def _criteres_fondamentaux(
    ratios: Ratios | None,
    exercices: Sequence[Fondamentaux],
    bornes: ConfigBornes,
) -> dict[str, Critere]:
    absent = "aucune donnée fondamentale saisie pour cette valeur"
    if ratios is None:
        return {
            nom: Critere.absent(nom, nom.replace("_", " ").capitalize(), absent)
            for nom in CRITERES_FONDAMENTAUX
        }

    criteres: dict[str, Critere] = {}

    if ratios.rendement_dividende is None:
        criteres["rendement_dividende"] = Critere.absent(
            "rendement_dividende",
            "Rendement du dividende",
            "dividende par action non renseigné",
        )
    else:
        criteres["rendement_dividende"] = Critere(
            nom="rendement_dividende",
            libelle="Rendement du dividende",
            valeur=ratios.rendement_dividende,
            unite="fraction",
            note=note_croissante(
                ratios.rendement_dividende, Decimal(0), bornes.rendement_dividende_plafond
            ),
        )

    if ratios.per is None:
        criteres["per"] = Critere.absent("per", "PER", "résultat par action absent, nul ou négatif")
    else:
        criteres["per"] = Critere(
            nom="per",
            libelle="PER",
            valeur=ratios.per,
            unite="×",
            note=note_decroissante(ratios.per, bornes.per_plancher, bornes.per_plafond),
        )

    if ratios.price_book is None:
        criteres["price_book"] = Critere.absent(
            "price_book", "Cours / actif net", "capitaux propres par action absents"
        )
    else:
        criteres["price_book"] = Critere(
            nom="price_book",
            libelle="Cours / actif net",
            valeur=ratios.price_book,
            unite="×",
            note=note_decroissante(
                ratios.price_book, bornes.price_book_plancher, bornes.price_book_plafond
            ),
        )

    verses, renseignes = regularite_dividende(exercices)
    if renseignes < 2:
        criteres["regularite_dividende"] = Critere.absent(
            "regularite_dividende",
            "Régularité du dividende",
            f"{renseignes} exercice(s) renseigné(s) : deux au minimum pour mesurer une régularité",
        )
    else:
        with localcontext() as contexte:
            contexte.prec = PRECISION_INTERNE
            part = Decimal(verses) / Decimal(renseignes)
        criteres["regularite_dividende"] = Critere(
            nom="regularite_dividende",
            libelle=f"Dividende versé {verses} exercice(s) sur {renseignes}",
            valeur=part,
            unite="fraction",
            note=part,
        )
    return criteres


def analyser(
    ticker: str,
    serie: SerieTechnique,
    indicateurs: Indicateurs,
    configuration: Configuration,
    instrument: Instrument | None = None,
    exercices: Sequence[Fondamentaux] = (),
    annee_courante: int | None = None,
) -> AnalyseValeur:
    """Mesure tous les critères d'une valeur, sans en pondérer aucun."""
    bornes = configuration.analyse.bornes
    cours = dernier_cours_cote(serie)
    derniere_cotee = next(
        (b for b in reversed(serie.barres) if b.origine is OrigineValeur.COTEE), None
    )
    confiance = indicateurs.confiance

    ratios: Ratios | None = None
    exercice = exercices[0] if exercices else None
    if exercice is not None and cours is not None:
        ratios = calculer_ratios(
            exercice,
            cours,
            annee_courante
            or (derniere_cotee.date_seance.year if derniere_cotee else exercice.exercice),
        )

    criteres: dict[str, Critere] = {
        "momentum": _critere_momentum(indicateurs, bornes),
        "tendance": _critere_tendance(indicateurs, serie),
        "regime_rsi": _critere_rsi(indicateurs, bornes),
        "repli": _critere_repli(indicateurs, serie, bornes),
        "volatilite": _critere_volatilite(serie, configuration, bornes),
        "volume": _critere_volume(serie, configuration),
    }
    criteres.update(_criteres_fondamentaux(ratios, exercices, bornes))

    tenable, motif_taille = dimensionner(serie, configuration)

    avertissements = list(serie.avertissements)
    avertissements.extend(confiance.commentaires)
    if ratios is not None:
        avertissements.extend(ratios.avertissements)
    if exercice is None:
        avertissements.append(
            "Aucune donnée fondamentale : tout classement de long terme "
            "s'abstiendra pour cette valeur."
        )

    return AnalyseValeur(
        ticker=ticker,
        instrument=instrument,
        cours=cours,
        date_cours=derniere_cotee.date_seance if derniere_cotee else None,
        confiance=confiance.valeur,
        niveau_confiance=confiance.niveau,
        seances_cotees=confiance.seances_cotees,
        seances_attendues=confiance.seances_attendues,
        taille_tenable=tenable,
        motif_taille=motif_taille,
        profondeur=confiance.profondeur,
        etroitesse=confiance.etroitesse,
        criteres=criteres,
        ratios=ratios,
        exercice=exercice,
        avertissements=tuple(dict.fromkeys(avertissements)),
    )
