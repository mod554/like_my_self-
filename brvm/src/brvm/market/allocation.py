"""Proposition de portefeuille : vos contraintes, appliquées mécaniquement.

L'allocateur ne choisit rien et n'a pas d'avis. Il prend un classement, un
capital, et les limites que vous avez déclarées, puis descend le classement en
s'arrêtant à la première limite qui mord. Pour chaque ligne il dit **laquelle**
a mordu — c'est cette phrase, plus que le montant, qui rend la proposition
utilisable : elle montre ce qu'il faudrait changer pour obtenir autre chose.

Quatre limites s'appliquent, dans cet ordre :

1. **la liquidité** — la quantité tenable au regard du volume réellement échangé.
   Sur cette place, c'est presque toujours elle qui mord la première ;
2. **la concentration** — par ligne, par secteur, par pays, telle que déclarée
   dans `risque` ;
3. **le montant minimal d'une ligne** — en deçà, les frais fixes rendent
   l'opération absurde ;
4. **le nombre de lignes** — au-delà, le suivi coûte plus que la diversification
   ne rapporte.

Rien de tout cela n'est un conseil : ce sont vos propres règles, exécutées.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from brvm.config.modeles import Configuration
from brvm.domain.enums import SensOperation
from brvm.domain.modeles import Instrument
from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.market.horizons import Classement, Rang
from brvm.portfolio.frais import MoteurFrais


@dataclass(frozen=True, slots=True)
class LigneProposee:
    """Une ligne de la proposition, et ce qui a borné sa taille."""

    ticker: str
    quantite: int
    cours: int
    montant_brut: int
    frais: int
    montant_net: int
    poids_vise: Decimal
    poids_obtenu: Decimal
    score: Decimal | None
    #: La limite qui a fixé cette taille, en toutes lettres.
    contrainte: str
    secteur: str | None = None
    pays: str | None = None
    avertissements: tuple[str, ...] = ()

    @property
    def part_frais(self) -> Decimal:
        if self.montant_brut <= 0:
            return Decimal(0)
        return Decimal(self.frais) / Decimal(self.montant_brut)


@dataclass(frozen=True, slots=True)
class Ecarte:
    """Une valeur classée mais non retenue, avec la raison."""

    ticker: str
    score: Decimal | None
    motif: str


@dataclass(frozen=True, slots=True)
class Proposition:
    """Une répartition possible, entièrement traçable."""

    horizon: str
    capital: int
    lignes: tuple[LigneProposee, ...] = ()
    ecartes: tuple[Ecarte, ...] = ()
    liquidites: int = 0
    frais_totaux: int = 0
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def investi(self) -> int:
        return sum(ligne.montant_net for ligne in self.lignes)

    @property
    def part_investie(self) -> Decimal:
        if self.capital <= 0:
            return Decimal(0)
        return Decimal(self.investi) / Decimal(self.capital)

    def resume(self) -> str:
        lignes = [
            f"{len(self.lignes)} ligne(s), {self.investi} XOF investis sur "
            f"{self.capital} XOF, {self.liquidites} XOF en liquidités",
            f"Frais d'entrée : {self.frais_totaux} XOF",
        ]
        lignes += [
            f"  {ligne.ticker:<8} {ligne.quantite:>6} × {ligne.cours:>8} = "
            f"{ligne.montant_net:>10} XOF — {ligne.contrainte}"
            for ligne in self.lignes
        ]
        return "\n".join(lignes)


def _plafond_concentration(capital: Decimal, part: Decimal, deja: Decimal) -> Decimal:
    """Montant restant sous une limite de concentration."""
    return max(Decimal(0), capital * part - deja)


def proposer(
    classement: Classement,
    capital: int,
    configuration: Configuration,
    instruments: Mapping[str, Instrument] | None = None,
    moteur: MoteurFrais | None = None,
) -> Proposition:
    """Descend le classement en appliquant les limites déclarées.

    Args:
        classement: valeurs ordonnées par un profil. Seules les classées entrent.
        capital: montant total disponible, en XOF.
        instruments: référentiel, pour connaître secteur et pays.
    """
    reglages = configuration.allocation
    limites = configuration.risque
    moteur = moteur or MoteurFrais(configuration)
    index = dict(instruments or {})

    avertissements: list[str] = []
    if capital <= 0:
        return Proposition(
            horizon=classement.horizon,
            capital=capital,
            avertissements=("Capital nul : rien à répartir.",),
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        investissable = Decimal(capital) * (Decimal(1) - reglages.part_liquidites)

    lignes: list[LigneProposee] = []
    ecartes: list[Ecarte] = []
    engage = Decimal(0)
    par_secteur: dict[str, Decimal] = {}
    par_pays: dict[str, Decimal] = {}
    frais_totaux = 0

    for rang in classement.classes:
        if len(lignes) >= reglages.lignes_max:
            ecartes.append(
                Ecarte(
                    rang.ticker,
                    rang.valeur,
                    f"limite de {reglages.lignes_max} lignes atteinte",
                )
            )
            continue

        resultat = _dimensionner_ligne(
            rang,
            investissable=investissable,
            engage=engage,
            par_secteur=par_secteur,
            par_pays=par_pays,
            configuration=configuration,
            instrument=index.get(rang.ticker),
            moteur=moteur,
        )
        if isinstance(resultat, Ecarte):
            ecartes.append(resultat)
            continue

        lignes.append(resultat)
        frais_totaux += resultat.frais
        engage += Decimal(resultat.montant_net)
        if resultat.secteur:
            par_secteur[resultat.secteur] = par_secteur.get(resultat.secteur, Decimal(0)) + Decimal(
                resultat.montant_net
            )
        if resultat.pays:
            par_pays[resultat.pays] = par_pays.get(resultat.pays, Decimal(0)) + Decimal(
                resultat.montant_net
            )

    liquidites = capital - int(engage)

    if not lignes:
        avertissements.append(
            "Aucune ligne proposée. Le classement est vide, ou aucune valeur "
            "n'absorbe le montant minimal que vous avez déclaré."
        )
    couteuses = [ligne.ticker for ligne in lignes if ligne.part_frais > reglages.frais_alerte]
    if couteuses:
        avertissements.append(
            "Frais d'entrée au-delà du seuil que vous tolérez sur : "
            + ", ".join(couteuses)
            + ". Sur une petite ligne, le barème fixe pèse lourd."
        )
    if len(lignes) < reglages.lignes_max and classement.ecartes:
        avertissements.append(
            f"{len(classement.ecartes)} valeur(s) de la cote n'ont pas été classées "
            "et ne pouvaient donc pas entrer. Voir le détail du classement."
        )
    avertissements.append(
        "Cette répartition applique vos limites ; elle ne prédit aucun rendement "
        "et ne constitue pas un conseil d'investissement."
    )

    # Le poids obtenu ne se connaît qu'une fois toutes les lignes retenues :
    # il se rapporte à l'investi réel, pas au capital de départ.
    total = engage or Decimal(1)
    lignes = [_avec_poids(ligne, total) for ligne in lignes]

    # Les limites ont été appliquées contre l'enveloppe investissable. Quand
    # celle-ci n'a pas pu être remplie — parce que les autres lignes tombaient
    # sous le montant minimal — les lignes retenues pèsent plus lourd dans le
    # portefeuille RÉEL que dans l'enveloppe. Le dire : sans cela, l'allocateur
    # proposerait un portefeuille que les contrôles de risque signaleraient
    # aussitôt, et l'utilisateur ne saurait pas lequel des deux croire.
    depassements = [ligne for ligne in lignes if ligne.poids_obtenu > limites.poids_max_ligne]
    if depassements:
        detail = ", ".join(f"{ligne.ticker} à {ligne.poids_obtenu:.1%}" for ligne in depassements)
        avertissements.append(
            f"Votre limite de {limites.poids_max_ligne:.0%} par ligne est dépassée "
            f"dans le portefeuille obtenu : {detail}. L'enveloppe investissable "
            "n'a pas pu être remplie — les autres valeurs tombaient sous le "
            f"montant minimal de {reglages.montant_minimum_ligne} XOF. Abaissez ce "
            "minimum, augmentez le capital, ou acceptez la concentration en le "
            "sachant."
        )
    if len(lignes) == 1:
        avertissements.append(
            "Une seule ligne a pu être financée : ce n'est pas un portefeuille, "
            "c'est une position. Toute la diversification déclarée dans `risque` "
            "est inopérante à ce niveau de capital."
        )

    return Proposition(
        horizon=classement.horizon,
        capital=capital,
        lignes=tuple(lignes),
        ecartes=tuple(ecartes),
        liquidites=liquidites,
        frais_totaux=frais_totaux,
        avertissements=tuple(avertissements),
    )


def _avec_poids(ligne: LigneProposee, total: Decimal) -> LigneProposee:
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        poids = Decimal(ligne.montant_net) / total
    return LigneProposee(
        ticker=ligne.ticker,
        quantite=ligne.quantite,
        cours=ligne.cours,
        montant_brut=ligne.montant_brut,
        frais=ligne.frais,
        montant_net=ligne.montant_net,
        poids_vise=ligne.poids_vise,
        poids_obtenu=poids,
        score=ligne.score,
        contrainte=ligne.contrainte,
        secteur=ligne.secteur,
        pays=ligne.pays,
        avertissements=ligne.avertissements,
    )


def _dimensionner_ligne(
    rang: Rang,
    investissable: Decimal,
    engage: Decimal,
    par_secteur: dict[str, Decimal],
    par_pays: dict[str, Decimal],
    configuration: Configuration,
    instrument: Instrument | None,
    moteur: MoteurFrais,
) -> LigneProposee | Ecarte:
    """Taille d'une ligne : la plus petite des limites, et son nom."""
    analyse = rang.analyse
    cours = analyse.cours
    if cours is None or cours <= 0:
        return Ecarte(rang.ticker, rang.valeur, "aucun cours réellement coté")

    reglages = configuration.allocation
    limites = configuration.risque
    secteur = instrument.secteur if instrument else None
    pays = instrument.pays.value if instrument else None

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        # Deux natures de limites, qui ne se mesurent pas dans la même unité et
        # ne se comparent donc pas directement.
        #
        # La LIQUIDITÉ borne un nombre de titres : le marché absorbe une
        # quantité, et les frais n'en consomment aucune. La compter en monnaie
        # frais compris ferait acheter moins de titres que le carnet n'en offre.
        #
        # Les limites de CONCENTRATION et le capital restant bornent un montant,
        # et c'est le décaissement réel — frais compris — qui doit tenir dessous.
        # Une limite de 20 % appliquée au montant brut rend une ligne à 20,3 %,
        # que les contrôles de risque signaleraient aussitôt.
        plafonds: list[tuple[Decimal, str]] = [
            (
                _plafond_concentration(investissable, limites.poids_max_ligne, Decimal(0)),
                f"limite de concentration par ligne ({limites.poids_max_ligne:.0%})",
            ),
            (
                max(Decimal(0), investissable - engage),
                "capital investissable épuisé",
            ),
        ]
        if secteur:
            plafonds.append(
                (
                    _plafond_concentration(
                        investissable,
                        limites.poids_max_secteur,
                        par_secteur.get(secteur, Decimal(0)),
                    ),
                    f"limite de concentration sur le secteur {secteur} "
                    f"({limites.poids_max_secteur:.0%})",
                )
            )
        if pays:
            plafonds.append(
                (
                    _plafond_concentration(
                        investissable,
                        limites.poids_max_pays,
                        par_pays.get(pays, Decimal(0)),
                    ),
                    f"limite de concentration sur le pays {pays} ({limites.poids_max_pays:.0%})",
                )
            )

        plafond_montant, contrainte_montant = min(plafonds, key=lambda couple: couple[0])
        quantite_montant = int(
            (plafond_montant / Decimal(cours)).to_integral_value(rounding="ROUND_FLOOR")
        )
        contrainte_liquidite = (
            f"liquidité : {analyse.taille_tenable} titres tenables au regard du volume échangé"
        )

        if analyse.taille_tenable <= quantite_montant:
            quantite, contrainte = analyse.taille_tenable, contrainte_liquidite
        else:
            quantite, contrainte = quantite_montant, contrainte_montant

        plafond_effectif = min(plafond_montant, Decimal(analyse.taille_tenable) * Decimal(cours))

    if quantite <= 0:
        return Ecarte(rang.ticker, rang.valeur, contrainte)

    # Descente jusqu'à ce que le décaissement RÉEL tienne sous le plafond en
    # montant. La liquidité n'entre pas ici : elle a déjà fixé une quantité.
    decompte = moteur.calculer(SensOperation.ACHAT, quantite, cours)
    frais_ont_mordu = False
    while quantite > 1 and Decimal(decompte.montant_net) > plafond_montant:
        # Réduction proportionnelle, puis une unité à la fois pour finir : la
        # première passe converge en un tour, la seconde garantit la sortie.
        estimation = int(
            (plafond_montant / Decimal(decompte.montant_net) * Decimal(quantite)).to_integral_value(
                rounding="ROUND_FLOOR"
            )
        )
        quantite = min(quantite - 1, max(1, estimation))
        decompte = moteur.calculer(SensOperation.ACHAT, quantite, cours)
        contrainte, frais_ont_mordu = contrainte_montant, True

    if frais_ont_mordu:
        contrainte = f"{contrainte}, frais compris"

    if Decimal(decompte.montant_net) > plafond_montant:
        return Ecarte(
            rang.ticker,
            rang.valeur,
            "même un titre ne tient pas sous la limite qui borne cette ligne "
            f"({contrainte_montant}), frais compris",
        )

    if decompte.montant_net < reglages.montant_minimum_ligne:
        return Ecarte(
            rang.ticker,
            rang.valeur,
            f"ligne de {decompte.montant_net} XOF, sous le minimum de "
            f"{reglages.montant_minimum_ligne} XOF que vous avez déclaré "
            f"(bornée par : {contrainte})",
        )

    avertissements: list[str] = []
    if analyse.confiance < Decimal("0.5"):
        avertissements.append(
            f"Confiance de la donnée à {analyse.confiance:.0%} : "
            f"{analyse.seances_cotees} séances cotées sur {analyse.seances_attendues}."
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        poids_vise = plafond_effectif / investissable if investissable > 0 else Decimal(0)

    return LigneProposee(
        ticker=rang.ticker,
        quantite=quantite,
        cours=cours,
        montant_brut=decompte.montant_brut,
        frais=decompte.total,
        montant_net=decompte.montant_net,
        poids_vise=poids_vise,
        poids_obtenu=Decimal(0),
        score=rang.valeur,
        contrainte=contrainte,
        secteur=secteur,
        pays=pays,
        avertissements=tuple(avertissements),
    )


@dataclass(frozen=True, slots=True)
class Mouvement:
    """Un ordre à passer pour rejoindre une cible."""

    ticker: str
    sens: SensOperation
    quantite: int
    cours: int
    montant_net: int
    frais: int
    motif: str

    @property
    def part_frais(self) -> Decimal:
        brut = Decimal(self.quantite * self.cours)
        return Decimal(self.frais) / brut if brut > 0 else Decimal(0)


def rebalancer(
    detenu: Mapping[str, int],
    proposition: Proposition,
    cours: Mapping[str, int],
    configuration: Configuration,
    moteur: MoteurFrais | None = None,
) -> tuple[tuple[Mouvement, ...], tuple[str, ...]]:
    """Ordres pour passer du portefeuille détenu à la répartition proposée.

    Les frais sont calculés sur chaque ordre, et un ordre dont les frais
    dépassent le seuil déclaré est signalé : sur une petite ligne, rééquilibrer
    coûte parfois plus que l'écart qu'on corrige.
    """
    moteur = moteur or MoteurFrais(configuration)
    seuil = configuration.allocation.frais_alerte
    cible = {ligne.ticker: ligne.quantite for ligne in proposition.lignes}
    mouvements: list[Mouvement] = []
    avertissements: list[str] = []

    for ticker in sorted(set(detenu) | set(cible)):
        actuel = detenu.get(ticker, 0)
        vise = cible.get(ticker, 0)
        ecart = vise - actuel
        if ecart == 0:
            continue
        prix = cours.get(ticker)
        if prix is None or prix <= 0:
            avertissements.append(f"{ticker} : aucun cours disponible, l'ordre n'est pas chiffré.")
            continue

        sens = SensOperation.ACHAT if ecart > 0 else SensOperation.VENTE
        decompte = moteur.calculer(sens, abs(ecart), prix)
        mouvement = Mouvement(
            ticker=ticker,
            sens=sens,
            quantite=abs(ecart),
            cours=prix,
            montant_net=decompte.montant_net,
            frais=decompte.total,
            motif=(
                f"détenu {actuel}, visé {vise}" if vise else f"sortie complète de {actuel} titres"
            ),
        )
        mouvements.append(mouvement)
        if mouvement.part_frais > seuil:
            avertissements.append(
                f"{ticker} : frais à {mouvement.part_frais:.2%} du montant, au-delà "
                f"du seuil de {seuil:.2%}. Rééquilibrer coûte peut-être plus que "
                "l'écart corrigé."
            )

    return tuple(mouvements), tuple(avertissements)
