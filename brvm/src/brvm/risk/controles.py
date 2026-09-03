"""Contrôles de risque : concentration, liquidité, stops.

Ces contrôles ne bloquent rien. Ils constatent, chiffrent et expliquent. La
décision reste à l'utilisateur, qui est le seul à connaître son horizon et sa
tolérance.

La contrainte de liquidité est celle qui mérite le plus d'attention sur ce
marché : une position peut être parfaitement dimensionnée en pourcentage du
portefeuille et rester impossible à déboucler en moins de trois semaines. Le
contrôle chiffre ce délai.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from enum import StrEnum
from itertools import combinations
from typing import Final

from brvm.config.modeles import Configuration
from brvm.domain.modeles import Instrument
from brvm.domain.monnaie import PRECISION_INTERNE, format_xof
from brvm.indicators.resultats import ResultatIndicateur
from brvm.indicators.serie import SerieTechnique
from brvm.portfolio.valorisation import Portefeuille
from brvm.risk.mesures import ResultatCorrelation, calculer_correlation

_DECIMALES: Final[Decimal] = Decimal("0.000001")


class Dimension(StrEnum):
    """Axe selon lequel la concentration est mesurée."""

    LIGNE = "ligne"
    SECTEUR = "secteur"
    PAYS = "pays"


@dataclass(frozen=True, slots=True)
class ConstatConcentration:
    """Poids d'un regroupement, comparé à sa limite."""

    dimension: Dimension
    cle: str
    poids: Decimal
    limite: Decimal
    valeur: int

    @property
    def respecte(self) -> bool:
        return self.poids <= self.limite

    @property
    def depassement(self) -> Decimal:
        return max(Decimal(0), self.poids - self.limite)

    def resume(self) -> str:
        etat = "respecté" if self.respecte else f"DÉPASSÉ de {self.depassement:.2%}"
        return (
            f"{self.dimension.value} {self.cle} : {self.poids:.2%} "
            f"(limite {self.limite:.2%}) — {etat}"
        )


@dataclass(frozen=True, slots=True)
class ConstatLiquidite:
    """Dimensionnement d'une ligne au regard de ce qui s'échange réellement."""

    ticker: str
    quantite_detenue: int
    #: Volume quotidien moyen, sur les seules séances cotées.
    volume_moyen: Decimal
    #: Séances réellement cotées dans la fenêtre observée.
    seances_cotees: int
    seances_observees: int
    part_max_volume: Decimal
    #: Nombre de titres cessibles par séance sans peser sur le marché.
    debit_quotidien: Decimal
    #: Séances nécessaires pour solder la ligne à ce rythme.
    seances_pour_deboucler: Decimal | None
    motif_indisponible: str | None = None

    @property
    def mesurable(self) -> bool:
        return self.seances_pour_deboucler is not None

    def resume(self) -> str:
        if not self.mesurable:
            return f"{self.ticker} : liquidité non mesurable — {self.motif_indisponible}"
        return (
            f"{self.ticker} : {self.quantite_detenue} titres, volume moyen "
            f"{self.volume_moyen:.0f}/séance, débit tenable "
            f"{self.debit_quotidien:.0f}/séance → environ "
            f"{self.seances_pour_deboucler:.1f} séance(s) pour solder la ligne"
        )


@dataclass(frozen=True, slots=True)
class StopAtr:
    """Niveau de stop adossé à la volatilité réelle, et son exécutabilité."""

    ticker: str
    cours_reference: int
    atr: Decimal | None
    multiple: Decimal
    niveau: int | None
    #: Distance du stop au cours, en fraction.
    distance: Decimal | None
    anciennete_atr: int
    motif_indisponible: str | None = None
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    def resume(self) -> str:
        if self.niveau is None:
            return f"{self.ticker} : stop non calculable — {self.motif_indisponible}"
        return (
            f"{self.ticker} : stop à {format_xof(self.niveau)} "
            f"({self.distance:.2%} sous {format_xof(self.cours_reference)}, "
            f"{self.multiple}× ATR)"
        )


@dataclass(frozen=True, slots=True)
class RapportRisque:
    """Ce que les contrôles ont constaté, sans jugement ni blocage."""

    concentrations: tuple[ConstatConcentration, ...] = ()
    liquidites: tuple[ConstatLiquidite, ...] = ()
    stops: tuple[StopAtr, ...] = ()
    #: Corrélations entre lignes détenues. Deux lignes qui montent et descendent
    #: ensemble ne diversifient rien : la limite de concentration par ligne est
    #: alors respectée à la lettre et contournée en fait.
    correlations: tuple[ResultatCorrelation, ...] = ()
    avertissements: tuple[str, ...] = ()

    def depassements(self) -> tuple[ConstatConcentration, ...]:
        return tuple(constat for constat in self.concentrations if not constat.respecte)

    def resume(self) -> str:
        lignes: list[str] = ["Concentration :"]
        lignes += [f"  {constat.resume()}" for constat in self.concentrations]
        if self.liquidites:
            lignes.append("Liquidité :")
            lignes += [f"  {constat.resume()}" for constat in self.liquidites]
        if self.stops:
            lignes.append("Stops :")
            lignes += [f"  {stop.resume()}" for stop in self.stops]
        if self.correlations:
            lignes.append("Corrélations entre lignes détenues :")
            lignes += [
                f"  {c.ticker_a}/{c.ticker_b} : "
                + (
                    f"{c.valeur:.2f} sur {c.seances_communes} séances communes"
                    if c.valeur is not None
                    else f"non mesurable — {c.motif_indisponible}"
                )
                for c in self.correlations
            ]
        if self.avertissements:
            lignes.append("Avertissements :")
            lignes += [f"  • {message}" for message in self.avertissements]
        return "\n".join(lignes)


def controler_concentration(
    portefeuille: Portefeuille,
    instruments: Mapping[str, Instrument],
    configuration: Configuration,
) -> tuple[tuple[ConstatConcentration, ...], tuple[str, ...]]:
    """Mesure le poids de chaque ligne, secteur et pays.

    Une valeur absente du référentiel n'est rattachée à aucun secteur ni pays :
    elle est signalée plutôt que rangée dans une catégorie inventée.
    """
    reglages = configuration.risque
    valorisees = [ligne for ligne in portefeuille.lignes if ligne.valeur is not None]
    total = sum(ligne.valeur or 0 for ligne in valorisees)
    avertissements: list[str] = []
    if total <= 0:
        return (), ("Portefeuille non valorisé : la concentration n'est pas mesurable.",)

    constats: list[ConstatConcentration] = []
    par_secteur: dict[str, int] = {}
    par_pays: dict[str, int] = {}

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for ligne in valorisees:
            valeur = ligne.valeur or 0
            constats.append(
                ConstatConcentration(
                    dimension=Dimension.LIGNE,
                    cle=ligne.ticker,
                    poids=(Decimal(valeur) / Decimal(total)).quantize(_DECIMALES),
                    limite=reglages.poids_max_ligne,
                    valeur=valeur,
                )
            )
            instrument = instruments.get(ligne.ticker)
            if instrument is None:
                avertissements.append(
                    f"{ligne.ticker} absent du référentiel : sa ligne est mesurée, mais "
                    "elle n'entre dans aucun secteur ni pays. Les poids sectoriels et "
                    "géographiques sont donc incomplets."
                )
                continue
            if instrument.secteur:
                par_secteur[instrument.secteur] = par_secteur.get(instrument.secteur, 0) + valeur
            else:
                avertissements.append(
                    f"{ligne.ticker} : aucun secteur renseigné dans le référentiel."
                )
            par_pays[instrument.pays.value] = par_pays.get(instrument.pays.value, 0) + valeur

        for secteur, valeur in sorted(par_secteur.items()):
            constats.append(
                ConstatConcentration(
                    dimension=Dimension.SECTEUR,
                    cle=secteur,
                    poids=(Decimal(valeur) / Decimal(total)).quantize(_DECIMALES),
                    limite=reglages.poids_max_secteur,
                    valeur=valeur,
                )
            )
        for pays, valeur in sorted(par_pays.items()):
            constats.append(
                ConstatConcentration(
                    dimension=Dimension.PAYS,
                    cle=pays,
                    poids=(Decimal(valeur) / Decimal(total)).quantize(_DECIMALES),
                    limite=reglages.poids_max_pays,
                    valeur=valeur,
                )
            )

    return tuple(constats), tuple(dict.fromkeys(avertissements))


def controler_liquidite(
    ticker: str,
    quantite_detenue: int,
    serie: SerieTechnique,
    configuration: Configuration,
) -> ConstatLiquidite:
    """Estime en combien de séances la ligne pourrait être soldée.

    Le débit tenable est la part configurée du volume quotidien moyen : au-delà,
    l'ordre pèse sur le cours et l'exécution se dégrade. Le volume moyen ne
    compte que les séances réellement cotées.
    """
    reglages = configuration.risque
    fenetre = reglages.fenetre_volume_moyen
    barres = serie.barres[-fenetre:]
    cotees = sum(1 for barre in barres if barre.cotee)
    volume_moyen = serie.volume_moyen(fenetre)

    if cotees == 0 or volume_moyen <= 0:
        return ConstatLiquidite(
            ticker=ticker,
            quantite_detenue=quantite_detenue,
            volume_moyen=volume_moyen,
            seances_cotees=cotees,
            seances_observees=len(barres),
            part_max_volume=reglages.part_max_volume_moyen,
            debit_quotidien=Decimal(0),
            seances_pour_deboucler=None,
            motif_indisponible=(
                f"aucun volume échangé sur les {len(barres)} dernières séances : la "
                "ligne pourrait n'être cessible à aucun prix raisonnable"
            ),
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        debit = volume_moyen * reglages.part_max_volume_moyen
        seances = (
            (Decimal(quantite_detenue) / debit).quantize(Decimal("0.1")) if debit > 0 else None
        )

    return ConstatLiquidite(
        ticker=ticker,
        quantite_detenue=quantite_detenue,
        volume_moyen=volume_moyen.quantize(Decimal("0.01")),
        seances_cotees=cotees,
        seances_observees=len(barres),
        part_max_volume=reglages.part_max_volume_moyen,
        debit_quotidien=debit.quantize(Decimal("0.01")),
        seances_pour_deboucler=seances,
    )


def calculer_stop_atr(
    ticker: str,
    cours_reference: int,
    atr: ResultatIndicateur,
    liquidite: ConstatLiquidite | None,
    configuration: Configuration,
) -> StopAtr:
    """Place un stop à N fois l'ATR sous le cours de référence.

    Le niveau est calculé ; son exécutabilité, elle, ne l'est pas. Sur une valeur
    qui ne cote pas tous les jours, un stop peut n'être franchi qu'à
    l'ouverture, plusieurs séances après le seuil, et à un cours bien plus bas.
    L'avertissement accompagne systématiquement le chiffre.
    """
    multiple = configuration.risque.multiple_atr_stop
    dernier = atr.dernier
    avertissements: list[str] = [
        "Un stop est difficilement exécutable sur une valeur peu liquide : il peut "
        "n'être franchi qu'à l'ouverture d'une séance ultérieure, à un cours "
        "sensiblement inférieur au seuil. Considérez ce niveau comme un signal de "
        "révision, pas comme une protection acquise."
    ]

    if dernier is None or dernier.valeur is None:
        return StopAtr(
            ticker=ticker,
            cours_reference=cours_reference,
            atr=None,
            multiple=multiple,
            niveau=None,
            distance=None,
            anciennete_atr=0,
            motif_indisponible=(
                dernier.motif_refus
                if dernier is not None and dernier.motif_refus
                else "ATR indisponible"
            ),
            avertissements=tuple(avertissements),
        )

    if dernier.anciennete > 0:
        avertissements.append(
            f"L'ATR retenu date de {dernier.anciennete} séance(s) : la volatilité "
            "actuelle peut avoir changé sans qu'aucune transaction ne l'ait révélé."
        )
    if (
        liquidite is not None
        and liquidite.seances_pour_deboucler is not None
        and liquidite.seances_pour_deboucler > 1
    ):
        avertissements.append(
            f"Solder la ligne demanderait environ "
            f"{liquidite.seances_pour_deboucler:.1f} séances : un stop touché ne "
            "peut pas être exécuté d'un bloc."
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        distance_absolue = multiple * dernier.valeur
        niveau = int((Decimal(cours_reference) - distance_absolue).to_integral_value())
        niveau = max(1, niveau)
        distance = (
            (Decimal(cours_reference - niveau) / Decimal(cours_reference)).quantize(_DECIMALES)
            if cours_reference > 0
            else None
        )

    return StopAtr(
        ticker=ticker,
        cours_reference=cours_reference,
        atr=dernier.valeur,
        multiple=multiple,
        niveau=niveau,
        distance=distance,
        anciennete_atr=dernier.anciennete,
        avertissements=tuple(avertissements),
    )


def controler(
    portefeuille: Portefeuille,
    instruments: Mapping[str, Instrument],
    series: Mapping[str, SerieTechnique],
    configuration: Configuration,
    atr_par_ticker: Mapping[str, ResultatIndicateur] | None = None,
) -> RapportRisque:
    """Passe tous les contrôles disponibles sur un portefeuille valorisé."""
    concentrations, avertissements = controler_concentration(
        portefeuille, instruments, configuration
    )
    liquidites: list[ConstatLiquidite] = []
    stops: list[StopAtr] = []
    manquantes: list[str] = []

    for ligne in portefeuille.lignes:
        serie = series.get(ligne.ticker)
        if serie is None:
            manquantes.append(ligne.ticker)
            continue
        constat = controler_liquidite(ligne.ticker, ligne.quantite, serie, configuration)
        liquidites.append(constat)
        atr = (atr_par_ticker or {}).get(ligne.ticker)
        if atr is not None and ligne.cours is not None:
            stops.append(calculer_stop_atr(ligne.ticker, ligne.cours, atr, constat, configuration))

    if manquantes:
        avertissements = (
            *avertissements,
            "Aucune série de cours pour : "
            + ", ".join(sorted(manquantes))
            + ". Leur liquidité et leurs stops ne sont pas évalués.",
        )

    correlations, avertissements_correlation = controler_correlations(
        portefeuille, series, configuration
    )

    return RapportRisque(
        concentrations=concentrations,
        liquidites=tuple(liquidites),
        stops=tuple(stops),
        correlations=correlations,
        avertissements=tuple(avertissements)
        + avertissements_correlation
        + portefeuille.avertissements,
    )


def controler_correlations(
    portefeuille: Portefeuille,
    series: Mapping[str, SerieTechnique],
    configuration: Configuration,
) -> tuple[tuple[ResultatCorrelation, ...], tuple[str, ...]]:
    """Corrélations deux à deux des lignes détenues.

    Une limite de concentration par ligne se contourne sans le vouloir : trois
    lignes de 15 % qui varient ensemble font une position de 45 %, et aucun
    contrôle de poids ne le voit. On mesure donc, et on signale les couples
    au-delà du seuil déclaré.

    Rien n'est calculé sous ``seances_minimum_correlation`` séances **communes** :
    apparier deux valeurs qui ne cotent pas les mêmes jours mesurerait le
    calendrier, pas le marché.
    """
    tickers = sorted(ligne.ticker for ligne in portefeuille.lignes if ligne.ticker in series)
    resultats = [
        calculer_correlation(series[a], series[b], configuration.risque.seances_minimum_correlation)
        for a, b in combinations(tickers, 2)
    ]
    seuil = configuration.risque.correlation_alerte
    eleves = [c for c in resultats if c.valeur is not None and c.valeur >= seuil]
    avertissements: tuple[str, ...] = ()
    if eleves:
        detail = ", ".join(f"{c.ticker_a}/{c.ticker_b} à {c.valeur:.2f}" for c in eleves)
        avertissements = (
            f"Lignes fortement corrélées (au-delà de {seuil:.2f}) : {detail}. "
            "Leurs poids individuels respectent peut-être vos limites, mais elles "
            "varient ensemble : la diversification est moindre que le tableau ne "
            "le laisse croire.",
        )
    return tuple(resultats), avertissements


def dimensionner(serie: SerieTechnique, configuration: Configuration) -> tuple[int, str | None]:
    """Taille maximale d'une position, en titres, au regard de la liquidité.

    Returns:
        La quantité tenable et, le cas échéant, le motif d'indisponibilité.
    """
    reglages = configuration.risque
    volume_moyen = serie.volume_moyen(reglages.fenetre_volume_moyen)
    if volume_moyen <= 0:
        return 0, (
            "aucun volume échangé sur la fenêtre : aucune taille de position n'est défendable"
        )
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        tenable = volume_moyen * reglages.part_max_volume_moyen
    return int(tenable.to_integral_value(rounding="ROUND_FLOOR")), None
