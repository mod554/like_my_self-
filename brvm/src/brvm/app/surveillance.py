"""Ce qui mérite une alerte, et rien d'autre.

Ce module ne connaît ni le réseau, ni les canaux, ni l'ordonnanceur : il prend
l'état constaté du système et rend une liste d'alertes. Cette séparation est ce
qui rend la règle « quand alerter » testable sans envoyer un seul message.

Quatre familles de constats, chacune activable en configuration :

* **échec de source** — une collecte en échec, ou servie depuis un cache périmé ;
* **donnée périmée** — un cours plus vieux que le seuil déclaré ;
* **seuil de risque** — une limite de concentration ou de liquidité dépassée ;
* **signal technique** — un franchissement constaté, avec sa date d'exécution.

Un signal technique est un **constat**, pas un conseil : l'alerte le rappelle
dans son texte, et n'exprime jamais d'attente de gain.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from brvm.app.alertes import Alerte, CategorieAlerte, NiveauAlerte
from brvm.config.modeles import Configuration
from brvm.domain.enums import GraviteAnomalie, StatutCollecte
from brvm.domain.modeles import Anomalie, Valorisation
from brvm.domain.monnaie import format_xof
from brvm.indicators.signaux import Signal
from brvm.ingestion.orchestrateur import BilanIngestion
from brvm.portfolio.historique import serie_actif_total
from brvm.portfolio.valorisation import Portefeuille
from brvm.risk.controles import Dimension, RapportRisque
from brvm.risk.mesures import calculer_drawdown

#: Mention ajoutée à toute alerte portant sur un signal technique. Le système
#: constate un franchissement ; il ne prédit rien et ne promet aucun rendement.
MENTION_SIGNAL: str = (
    "Constat technique, pas une recommandation : le système ne prédit aucun cours "
    "et ne promet aucun rendement."
)


def _minutes(valeur: Decimal) -> str:
    return f"{valeur:.0f}"


def depuis_ingestion(
    bilans: Sequence[BilanIngestion], configuration: Configuration, maintenant: datetime
) -> list[Alerte]:
    """Alerte sur les collectes en échec et sur les données servies du cache."""
    if not configuration.alertes.alerter_echec_source:
        return []
    alertes: list[Alerte] = []
    for bilan in bilans:
        if bilan.statut is StatutCollecte.ECHEC:
            alertes.append(
                Alerte(
                    categorie=CategorieAlerte.ECHEC_SOURCE,
                    niveau=NiveauAlerte.CRITIQUE,
                    titre=f"Source {bilan.source} en échec",
                    message=(
                        f"{bilan.message or 'Aucune donnée collectée.'} "
                        "Les autres sources ont été traitées normalement."
                    ),
                    emise_le=maintenant,
                    contexte={"source": bilan.source, "statut": bilan.statut.value},
                )
            )
        elif bilan.statut is StatutCollecte.DEGRADE:
            alertes.append(
                Alerte(
                    categorie=CategorieAlerte.ECHEC_SOURCE,
                    niveau=NiveauAlerte.AVERTISSEMENT,
                    titre=f"Source {bilan.source} servie depuis le cache",
                    message=(
                        "La source était injoignable : les données proviennent du cache "
                        "local et leur âge est à vérifier avant toute décision."
                    ),
                    emise_le=maintenant,
                    contexte={"source": bilan.source, "statut": bilan.statut.value},
                )
            )
        elif bilan.statut is StatutCollecte.PARTIEL:
            alertes.append(
                Alerte(
                    categorie=CategorieAlerte.ECHEC_SOURCE,
                    niveau=NiveauAlerte.AVERTISSEMENT,
                    titre=f"Source {bilan.source} partiellement collectée",
                    message=(
                        f"{bilan.lignes_rejetees} ligne(s) rejetée(s) sur "
                        f"{bilan.lignes_lues} lue(s). Les rejets sont consultables en "
                        "quarantaine avec leur donnée brute."
                    ),
                    emise_le=maintenant,
                    contexte={"source": bilan.source, "rejetees": str(bilan.lignes_rejetees)},
                )
            )
    return alertes


def depuis_anomalies(
    anomalies: Sequence[Anomalie], configuration: Configuration, maintenant: datetime
) -> list[Alerte]:
    """Une anomalie bloquante non résolue est un constat à remonter.

    Les anomalies sont regroupées par type : dix lignes illisibles dans la même
    page sont un seul problème, et dix alertes le rendraient invisible.
    """
    if not configuration.alertes.alerter_echec_source:
        return []
    bloquantes = [
        anomalie
        for anomalie in anomalies
        if anomalie.gravite is GraviteAnomalie.BLOQUANTE and not anomalie.resolue
    ]
    par_type: dict[tuple[str, str], list[Anomalie]] = {}
    for anomalie in bloquantes:
        par_type.setdefault((anomalie.source, anomalie.type_anomalie), []).append(anomalie)

    return [
        Alerte(
            categorie=CategorieAlerte.ECHEC_SOURCE,
            niveau=NiveauAlerte.CRITIQUE,
            titre=f"{len(lot)} cotation(s) en quarantaine — {type_anomalie}",
            message=(
                f"Source {source}. Exemple : {lot[0].message} "
                "Ces cotations sont écrites en base pour investigation et exclues de "
                "tous les calculs."
            ),
            emise_le=maintenant,
            contexte={"source": source, "type": type_anomalie, "nombre": str(len(lot))},
        )
        for (source, type_anomalie), lot in sorted(par_type.items())
    ]


def depuis_fraicheur(
    portefeuille: Portefeuille, configuration: Configuration, maintenant: datetime
) -> list[Alerte]:
    """Alerte quand la donnée la plus ancienne dépasse le seuil déclaré.

    Le seuil porte sur la donnée **la plus ancienne** du portefeuille, pas sur une
    moyenne : c'est elle qui détermine ce sur quoi on peut décider.
    """
    seuil = configuration.alertes.age_donnee_max_minutes
    alertes: list[Alerte] = []

    for ligne in portefeuille.lignes:
        age = ligne.age_minutes(maintenant)
        if age is None or age <= seuil:
            continue
        alertes.append(
            Alerte(
                categorie=CategorieAlerte.DONNEE_PERIMEE,
                niveau=NiveauAlerte.AVERTISSEMENT,
                titre=f"Cours de {ligne.ticker} âgé de {_minutes(age)} minutes",
                message=(
                    f"Au-delà des {seuil} minutes tolérées. La ligne reste valorisée "
                    "à ce cours : c'est le dernier connu, pas un cours actuel."
                ),
                emise_le=maintenant,
                ticker=ligne.ticker,
                horodatage_donnee=ligne.horodatage_cours,
                contexte={"age_minutes": _minutes(age), "seuil_minutes": str(seuil)},
            )
        )

    for ligne in portefeuille.lignes_non_valorisees:
        alertes.append(
            Alerte(
                categorie=CategorieAlerte.DONNEE_PERIMEE,
                niveau=NiveauAlerte.CRITIQUE,
                titre=f"{ligne.ticker} n'est pas valorisée",
                message=(
                    f"{ligne.motif_indisponible or 'Aucun cours disponible.'} "
                    "Cette ligne n'est pas comptée pour zéro : le total du portefeuille "
                    "est incomplet."
                ),
                emise_le=maintenant,
                ticker=ligne.ticker,
                contexte={"quantite": str(ligne.quantite)},
            )
        )
    return alertes


def depuis_risque(
    rapport: RapportRisque, configuration: Configuration, maintenant: datetime
) -> list[Alerte]:
    """Alerte sur les limites de concentration et de liquidité dépassées."""
    if not configuration.alertes.alerter_seuil_risque:
        return []
    alertes: list[Alerte] = [
        Alerte(
            categorie=CategorieAlerte.SEUIL_RISQUE,
            niveau=NiveauAlerte.AVERTISSEMENT,
            titre=f"Concentration dépassée — {constat.dimension.value} {constat.cle}",
            message=constat.resume(),
            emise_le=maintenant,
            ticker=constat.cle if constat.dimension is Dimension.LIGNE else None,
            contexte={
                "dimension": constat.dimension.value,
                "poids": f"{constat.poids:.4f}",
                "limite": f"{constat.limite:.4f}",
            },
        )
        for constat in rapport.depassements()
    ]

    # Une liquidité non mesurable n'est pas une bonne nouvelle : elle veut dire
    # que le dimensionnement de la ligne ne peut pas être vérifié du tout.
    alertes += [
        Alerte(
            categorie=CategorieAlerte.SEUIL_RISQUE,
            niveau=NiveauAlerte.AVERTISSEMENT,
            titre=f"Liquidité non mesurable — {constat.ticker}",
            message=(
                f"{constat.resume()} Le délai de sortie de cette ligne ne peut pas "
                "être estimé : ne le supposez pas court."
            ),
            emise_le=maintenant,
            ticker=constat.ticker,
            contexte={"seances_cotees": str(constat.seances_cotees)},
        )
        for constat in rapport.liquidites
        if not constat.mesurable
    ]

    # Le seuil de débouclage est facultatif : sans valeur déclarée, le délai est
    # calculé et affiché, mais rien n'est signalé. Aucun seuil « raisonnable »
    # n'est supposé à la place de l'utilisateur.
    seuil = configuration.risque.seances_max_debouclage
    if seuil is not None:
        alertes += [
            Alerte(
                categorie=CategorieAlerte.SEUIL_RISQUE,
                niveau=NiveauAlerte.AVERTISSEMENT,
                titre=f"Débouclage lent — {constat.ticker}",
                message=(
                    f"{constat.resume()} Au-delà des {seuil} séance(s) que vous avez "
                    "déclarées comme acceptables."
                ),
                emise_le=maintenant,
                ticker=constat.ticker,
                contexte={
                    "seances_pour_deboucler": f"{constat.seances_pour_deboucler:.1f}",
                    "seuil": str(seuil),
                },
            )
            for constat in rapport.liquidites
            if constat.seances_pour_deboucler is not None and constat.seances_pour_deboucler > seuil
        ]
    return alertes


def depuis_signaux(
    signaux: Sequence[Signal], configuration: Configuration, maintenant: datetime
) -> list[Alerte]:
    """Alerte sur les franchissements constatés, avec leur date d'exécution.

    La date d'exécution figure dans le message : un signal constaté à la clôture
    n'était pas exécutable pendant la séance qui l'a produit, et l'oublier fausse
    toute lecture des performances.
    """
    if not configuration.alertes.alerter_signal_technique:
        return []
    return [
        Alerte(
            categorie=CategorieAlerte.SIGNAL_TECHNIQUE,
            niveau=NiveauAlerte.INFORMATION,
            titre=f"{signal.sens.value} {signal.ticker} — {signal.regle}",
            message=(
                f"{signal.explication} Constaté sur la séance du "
                f"{signal.date_constat.isoformat()}, exécutable au plus tôt le "
                f"{signal.date_execution.isoformat()}. "
                f"Confiance de la donnée : {signal.confiance.niveau}. "
                + (" ".join(signal.avertissements) + " " if signal.avertissements else "")
                + MENTION_SIGNAL
            ),
            emise_le=maintenant,
            ticker=signal.ticker,
            contexte={
                "regle": signal.regle,
                "sens": signal.sens.value,
                "date_constat": signal.date_constat.isoformat(),
                "date_execution": signal.date_execution.isoformat(),
                "confiance": f"{signal.confiance.valeur:.4f}",
            },
        )
        for signal in signaux
    ]


def rassembler(
    configuration: Configuration,
    maintenant: datetime,
    bilans: Sequence[BilanIngestion] = (),
    anomalies: Sequence[Anomalie] = (),
    portefeuille: Portefeuille | None = None,
    rapport: RapportRisque | None = None,
    signaux: Sequence[Signal] = (),
    valorisations: Sequence[Valorisation] = (),
) -> list[Alerte]:
    """Réunit tous les constats du cycle, du plus grave au moins grave."""
    alertes: list[Alerte] = []
    alertes += depuis_ingestion(bilans, configuration, maintenant)
    alertes += depuis_anomalies(anomalies, configuration, maintenant)
    if portefeuille is not None:
        alertes += depuis_fraicheur(portefeuille, configuration, maintenant)
    if rapport is not None:
        alertes += depuis_risque(rapport, configuration, maintenant)
    alertes += depuis_signaux(signaux, configuration, maintenant)
    alertes += depuis_repli(valorisations, configuration, maintenant)
    return sorted(
        alertes,
        key=lambda alerte: (
            -alerte.niveau.rang,
            alerte.categorie.value,
            alerte.ticker or "",
            alerte.titre,
        ),
    )


def depuis_repli(
    valorisations: Sequence[Valorisation],
    configuration: Configuration,
    maintenant: datetime,
) -> list[Alerte]:
    """Alerte sur le recul du portefeuille sous son plus-haut.

    Le seuil `risque.drawdown_alerte` était déclaré dans les trois
    configurations livrées et ne pouvait se comparer à rien : aucune
    valorisation n'était conservée. Il est désormais opérant.

    Deux abstentions volontaires. Une **série incomplète** ne produit pas
    d'alerte approchée : sans espèces connues, un repli mesuré sur les seuls
    titres afficherait 100 % dès qu'une ligne est soldée. Et un historique trop
    court ne produit rien non plus — un repli se mesure contre un plus-haut
    antérieur.
    """
    if not configuration.alertes.alerter_seuil_risque:
        return []

    serie, motif = serie_actif_total(valorisations)
    if motif is not None:
        # L'impossibilité de mesurer est elle-même un constat : sans elle,
        # l'utilisateur croirait que son portefeuille ne recule pas.
        if not valorisations:
            return []
        return [
            Alerte(
                categorie=CategorieAlerte.CONFIGURATION,
                niveau=NiveauAlerte.INFORMATION,
                titre="Repli du portefeuille non mesurable",
                message=motif,
                emise_le=maintenant,
                contexte={"valorisations": str(len(valorisations))},
            )
        ]

    resultat = calculer_drawdown(serie)
    seuil = configuration.risque.drawdown_alerte
    if resultat.drawdown_courant < seuil:
        return []

    plus_haut = resultat.points[-1].plus_haut_atteint
    return [
        Alerte(
            categorie=CategorieAlerte.REPLI_PORTEFEUILLE,
            niveau=(
                NiveauAlerte.CRITIQUE
                if resultat.drawdown_courant >= seuil * 2
                else NiveauAlerte.AVERTISSEMENT
            ),
            titre=f"Repli de {resultat.drawdown_courant:.1%} sous le plus-haut",
            message=(
                f"L'actif total est à {format_xof(resultat.points[-1].valeur)}, contre un "
                f"plus-haut de {format_xof(plus_haut)}. Le seuil que vous avez déclaré est "
                f"{seuil:.0%}. Repli maximum observé sur la période : "
                f"{resultat.drawdown_maximum:.1%}"
                + (
                    f" le {resultat.date_du_maximum.isoformat()}"
                    if resultat.date_du_maximum
                    else ""
                )
                + f". {resultat.seances_sous_le_sommet} séance(s) sous le sommet."
            ),
            emise_le=maintenant,
            contexte={
                "repli_courant": f"{resultat.drawdown_courant:.4f}",
                "repli_maximum": f"{resultat.drawdown_maximum:.4f}",
                "seuil": f"{seuil:.4f}",
                "plus_haut": str(plus_haut),
            },
        )
    ]
