"""Sérialisation de l'état pour l'interface web.

L'interface ne recalcule rien : elle affiche ce que cette couche lui remet. C'est
la même règle qu'entre le tableau de bord et l'export — une seule lecture, servie
à toutes les sorties — étendue au navigateur.

Trois traits guident la mise en forme :

* **rien n'est arrondi ni reformaté ici.** Les montants partent en entiers de XOF,
  les dates en ISO. Le formatage est un choix d'affichage, il appartient à la vue ;
* **une valeur absente reste absente.** ``null`` traverse la sérialisation ; jamais
  de zéro de remplacement, qui se lirait comme une mesure ;
* **la trame de séances accompagne chaque valeur.** C'est la donnée qui dit combien
  de séances ont réellement coté derrière un cours, et elle voyage avec lui.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final

from brvm.app.etat import EtatSysteme
from brvm.domain.enums import MethodeValorisation
from brvm.indicators.serie import BarreTechnique, OrigineValeur, SerieTechnique
from brvm.market.allocation import LigneProposee, Proposition
from brvm.market.analyse import AnalyseValeur
from brvm.market.criblage import Criblage
from brvm.market.criteres import Critere
from brvm.market.horizons import Classement, Rang

#: Profondeur de la trame de séances affichée, en séances.
TRAME_SEANCES: Final[int] = 30

#: Profondeur de la courbe de cours, en séances.
COURBE_SEANCES: Final[int] = 120

#: Mention accompagnant toute sortie de la couche marché. Elle voyage avec la
#: donnée plutôt que d'être posée une fois dans un coin de la page : un tableau
#: recopié ailleurs doit rester lisible pour ce qu'il est.
MENTION_MARCHE: Final[str] = (
    "Classement mécanique de critères déclarés, sur données passées. Aucune "
    "prévision, aucune recommandation, aucune promesse de rendement."
)


def _nombre(valeur: Decimal | None, decimales: int = 4) -> float | None:
    """Un Decimal devient un nombre JSON, ou reste absent.

    La conversion est faite ici, une fois, plutôt que dispersée dans la vue : le
    JSON n'a pas de type décimal, et laisser chaque appelant improviser
    produirait des arrondis différents d'un écran à l'autre.
    """
    return None if valeur is None else round(float(valeur), decimales)


def _marque(barre: BarreTechnique) -> dict[str, Any]:
    """Une séance de la trame : son état, et le cours s'il a été observé."""
    return {
        "date": barre.date_seance.isoformat(),
        "origine": barre.origine.value,
        "cotee": barre.origine is OrigineValeur.COTEE,
        "cloture": _nombre(barre.cloture, 0),
        "volume": barre.volume,
    }


def trame(serie: SerieTechnique, profondeur: int = TRAME_SEANCES) -> dict[str, Any]:
    """Texture des dernières séances : ce qui a coté, ce qui a été reporté.

    C'est la signature de cette interface. Un cours vu douze fois sur vingt
    séances ne vaut pas le même cours vu deux fois sur vingt, et rien dans un
    montant seul ne le dit.
    """
    barres = serie.barres[-profondeur:]
    cotees = sum(1 for barre in barres if barre.origine is OrigineValeur.COTEE)
    derniere = next((b for b in reversed(serie.barres) if b.origine is OrigineValeur.COTEE), None)
    return {
        "seances": [_marque(barre) for barre in barres],
        "cotees": cotees,
        "attendues": len(barres),
        "derniere_cotee": derniere.date_seance.isoformat() if derniere else None,
        "anciennete": serie.barres[-1].anciennete if serie.barres else None,
    }


def courbe(serie: SerieTechnique, profondeur: int = COURBE_SEANCES) -> list[dict[str, Any]]:
    """Points de cours, chacun sachant s'il a été observé ou reporté.

    Les cours reportés sont transmis mais **marqués** : la vue les trace en trait
    interrompu plutôt qu'en trait plein. Les lisser silencieusement dessinerait
    une tendance qui n'a pas eu lieu.
    """
    return [
        {
            "date": barre.date_seance.isoformat(),
            "cloture": _nombre(barre.cloture, 0),
            "cotee": barre.origine is OrigineValeur.COTEE,
        }
        for barre in serie.barres[-profondeur:]
        if barre.cloture is not None
    ]


def _ligne(etat: EtatSysteme, ligne: Any) -> dict[str, Any]:
    valeur = etat.valeurs.get(ligne.ticker)
    age = ligne.age_minutes(etat.instant)
    return {
        "ticker": ligne.ticker,
        "quantite": ligne.quantite,
        "cout_total": ligne.cout_total,
        "prix_revient_unitaire": _nombre(ligne.prix_revient_unitaire, 2),
        "cours": ligne.cours,
        "date_cours": ligne.date_cours.isoformat() if ligne.date_cours else None,
        "age_minutes": _nombre(age, 0),
        "valeur": ligne.valeur,
        "poids": _nombre(ligne.poids),
        "plus_value_brute": ligne.plus_value_latente_brute,
        "plus_value_nette": ligne.plus_value_latente_nette,
        "frais_cession": ligne.frais_cession_estimes,
        "impot_estime": ligne.impot_estime,
        "dividendes_nets": ligne.dividendes_nets,
        "valorisee": ligne.valorisee,
        "motif_indisponible": ligne.motif_indisponible,
        # Le cours de référence est-il celui d'une séance réellement cotée ?
        # C'est ce qui autorise, ou non, l'affichage d'une variation.
        "cours_observe": _cours_observe(valeur),
        "trame": trame(valeur.serie) if valeur is not None else None,
        "confiance": _nombre(valeur.confiance) if valeur is not None else None,
    }


def _cours_observe(valeur: Any) -> bool:
    """Vrai si la dernière barre de la série provient d'une séance cotée."""
    if valeur is None or not valeur.serie.barres:
        return False
    origine: OrigineValeur = valeur.serie.barres[-1].origine
    return origine is OrigineValeur.COTEE


def _signaux(etat: EtatSysteme) -> list[dict[str, Any]]:
    return [
        {
            "ticker": signal.ticker,
            "sens": signal.sens.value,
            "regle": signal.regle,
            "explication": signal.explication,
            "date_constat": signal.date_constat.isoformat(),
            "date_execution": signal.date_execution.isoformat(),
            "confiance": _nombre(signal.confiance.valeur),
            "niveau_confiance": signal.confiance.niveau,
            "avertissements": list(signal.avertissements),
        }
        for signal in etat.signaux
    ]


def _risque(etat: EtatSysteme) -> dict[str, Any]:
    rapport = etat.risque
    return {
        "concentrations": [
            {
                "dimension": constat.dimension.value,
                "cle": constat.cle,
                "poids": _nombre(constat.poids),
                "limite": _nombre(constat.limite),
                "valeur": constat.valeur,
                "respecte": constat.respecte,
                "depassement": _nombre(constat.depassement),
            }
            for constat in rapport.concentrations
        ],
        "liquidites": [
            {
                "ticker": constat.ticker,
                "quantite": constat.quantite_detenue,
                "volume_moyen": _nombre(constat.volume_moyen, 0),
                "seances_cotees": constat.seances_cotees,
                "seances_observees": constat.seances_observees,
                "debit_quotidien": _nombre(constat.debit_quotidien, 0),
                "seances_pour_deboucler": _nombre(constat.seances_pour_deboucler, 1),
                "mesurable": constat.mesurable,
                "motif_indisponible": constat.motif_indisponible,
            }
            for constat in rapport.liquidites
        ],
        "stops": [
            {
                "ticker": stop.ticker,
                "cours_reference": stop.cours_reference,
                "niveau": stop.niveau,
                "distance": _nombre(stop.distance),
                "multiple": _nombre(stop.multiple, 2),
                "anciennete_atr": stop.anciennete_atr,
                "motif_indisponible": stop.motif_indisponible,
                "avertissements": list(stop.avertissements),
            }
            for stop in rapport.stops
        ],
        "avertissements": list(rapport.avertissements),
    }


def _plus_values_realisees(etat: EtatSysteme) -> dict[str, int]:
    """Plus-values réalisées par méthode. Les deux, jamais une seule."""
    resultats: dict[str, int] = {}
    for methode in (MethodeValorisation.PMP, MethodeValorisation.FIFO):
        suivi = etat.suivis.get(methode)
        if suivi is not None:
            resultats[methode.value] = sum(cession.plus_value_brute for cession in suivi.cessions)
    return resultats


def _performance(etat: EtatSysteme) -> dict[str, Any]:
    """Le rendement, ou la raison de son absence — jamais un zéro de remplacement.

    Le champ était figé à `disponible: False`. Il aurait contredit l'état dès
    que la performance est devenue mesurable.
    """
    resultat = etat.performance
    if resultat is None or resultat.valeur is None:
        return {
            "disponible": False,
            "valeur": None,
            "motif": etat.motif_performance_absente,
            "sous_periodes": [],
        }
    return {
        "disponible": True,
        "valeur": _nombre(resultat.valeur, 6),
        "motif": None,
        "sous_periodes": [
            {
                "debut": periode.debut.isoformat(),
                "fin": periode.fin.isoformat(),
                "rendement": _nombre(periode.rendement, 6),
            }
            for periode in resultat.sous_periodes
        ],
    }


def _tresorerie(etat: EtatSysteme) -> dict[str, Any]:
    """Le compte espèces, décomposé. Un solde inconnu reste ``null``."""
    compte = etat.portefeuille.tresorerie
    return {
        "mesurable": compte.mesurable,
        "solde": compte.solde,
        "motif_indisponible": compte.motif_indisponible,
        "apports": compte.apports,
        "retraits": compte.retraits,
        "dividendes_nets": compte.dividendes_nets,
        "frais_garde": compte.frais_garde,
        "decaissements_achats": compte.decaissements_achats,
        "encaissements_ventes": compte.encaissements_ventes,
        "actif_total": etat.portefeuille.actif_total,
    }


def serialiser(etat: EtatSysteme) -> dict[str, Any]:
    """Transforme l'état assemblé en charge JSON pour l'interface."""
    portefeuille = etat.portefeuille
    age = etat.age_minutes()
    return {
        "instant": etat.instant.isoformat(),
        "fraicheur": {
            "texte": etat.entete_fraicheur(),
            "horodatage": (
                etat.horodatage_le_plus_ancien.isoformat()
                if etat.horodatage_le_plus_ancien
                else None
            ),
            "age_minutes": _nombre(age, 0),
            "seuil_minutes": etat.configuration.alertes.age_donnee_max_minutes,
            "perimee": etat.donnee_perimee(),
        },
        "portefeuille": {
            "cout_total": portefeuille.cout_total,
            "valeur_totale": portefeuille.valeur_totale,
            "plus_value_brute": portefeuille.plus_value_latente_brute,
            "plus_value_nette": portefeuille.plus_value_latente_nette,
            "dividendes_nets": portefeuille.dividendes_nets_encaisses,
            "lignes": [_ligne(etat, ligne) for ligne in portefeuille.lignes],
            "non_valorisees": [ligne.ticker for ligne in portefeuille.lignes_non_valorisees],
        },
        "plus_values_realisees": _plus_values_realisees(etat),
        "methode": etat.configuration.general.methode_valorisation.value,
        "performance": _performance(etat),
        "tresorerie": _tresorerie(etat),
        "signaux": _signaux(etat),
        "risque": _risque(etat),
        "courbes": {ticker: courbe(valeur.serie) for ticker, valeur in etat.valeurs.items()},
        "anomalies": [
            {
                "detectee_le": anomalie.detectee_le.isoformat(),
                "gravite": anomalie.gravite.value,
                "source": anomalie.source,
                "type": anomalie.type_anomalie,
                "ticker": anomalie.ticker,
                "date_seance": (anomalie.date_seance.isoformat() if anomalie.date_seance else None),
                "message": anomalie.message,
            }
            for anomalie in etat.anomalies
        ],
        "collectes": list(etat.journal_collectes),
        "avertissements": list(etat.avertissements),
    }


# --------------------------------------------------------------------- marché


def _critere_json(critere: Critere) -> dict[str, Any]:
    """Un critère, mesuré ou non — et jamais un zéro à la place d'une absence."""
    return {
        "nom": critere.nom,
        "libelle": critere.libelle,
        "valeur": _nombre(critere.valeur),
        "unite": critere.unite,
        "note": _nombre(critere.note),
        "mesurable": critere.mesurable,
        "motif_absent": critere.motif_absent,
    }


def _analyse_json(analyse: AnalyseValeur) -> dict[str, Any]:
    return {
        "ticker": analyse.ticker,
        "nom": analyse.instrument.nom if analyse.instrument else None,
        "secteur": analyse.instrument.secteur if analyse.instrument else None,
        "pays": analyse.instrument.pays.value if analyse.instrument else None,
        "cours": analyse.cours,
        "date_cours": analyse.date_cours.isoformat() if analyse.date_cours else None,
        "confiance": _nombre(analyse.confiance),
        "niveau_confiance": analyse.niveau_confiance,
        "assiduite": _nombre(analyse.assiduite),
        "profondeur": _nombre(analyse.profondeur),
        "etroitesse": _nombre(analyse.etroitesse),
        "seances_cotees": analyse.seances_cotees,
        "seances_attendues": analyse.seances_attendues,
        "taille_tenable": analyse.taille_tenable,
        "motif_taille": analyse.motif_taille,
        "exercice": analyse.exercice.exercice if analyse.exercice else None,
        "source_fondamentaux": analyse.exercice.source if analyse.exercice else None,
        "criteres": [_critere_json(c) for c in analyse.criteres.values()],
        "avertissements": list(analyse.avertissements),
    }


def _rang_json(rang: Rang) -> dict[str, Any]:
    """Une place dans un classement, avec de quoi la contester."""
    return {
        "ticker": rang.ticker,
        "nom": rang.analyse.instrument.nom if rang.analyse.instrument else None,
        "score": _nombre(rang.valeur),
        "couverture": _nombre(rang.score.couverture),
        "motif_absent": rang.score.motif_absent,
        "cours": rang.analyse.cours,
        "date_cours": rang.analyse.date_cours.isoformat() if rang.analyse.date_cours else None,
        "confiance": _nombre(rang.analyse.confiance),
        "criteres": [_critere_json(c) for c in rang.score.criteres],
        "portes": [_critere_json(c) for c in rang.score.portes],
        "avertissements": list(rang.score.avertissements),
    }


def _classement_json(classement: Classement) -> dict[str, Any]:
    return {
        "horizon": classement.horizon,
        "libelle": classement.libelle,
        "description": classement.description,
        "couverture_cote": classement.couverture_cote,
        "classes": [_rang_json(rang) for rang in classement.classes],
        "ecartes": [_rang_json(rang) for rang in classement.ecartes],
        "avertissements": list(classement.avertissements),
    }


def _ligne_proposee_json(ligne: LigneProposee) -> dict[str, Any]:
    return {
        "ticker": ligne.ticker,
        "quantite": ligne.quantite,
        "cours": ligne.cours,
        "montant_brut": ligne.montant_brut,
        "frais": ligne.frais,
        "montant_net": ligne.montant_net,
        "part_frais": _nombre(ligne.part_frais),
        "poids_vise": _nombre(ligne.poids_vise),
        "poids_obtenu": _nombre(ligne.poids_obtenu),
        "score": _nombre(ligne.score),
        "contrainte": ligne.contrainte,
        "secteur": ligne.secteur,
        "pays": ligne.pays,
        "avertissements": list(ligne.avertissements),
    }


def proposition_json(proposition: Proposition) -> dict[str, Any]:
    """Une répartition proposée. La contrainte qui a borné chaque ligne voyage
    avec elle : c'est elle qui rend la proposition discutable."""
    return {
        "horizon": proposition.horizon,
        "capital": proposition.capital,
        "investi": proposition.investi,
        "part_investie": _nombre(proposition.part_investie),
        "liquidites": proposition.liquidites,
        "frais_totaux": proposition.frais_totaux,
        "lignes": [_ligne_proposee_json(ligne) for ligne in proposition.lignes],
        "ecartes": [
            {"ticker": e.ticker, "score": _nombre(e.score), "motif": e.motif}
            for e in proposition.ecartes
        ],
        "avertissements": list(proposition.avertissements),
    }


def serialiser_criblage(
    criblage: Criblage, propositions: Mapping[str, Proposition] | None = None
) -> dict[str, Any]:
    """La cote entière, telle que l'interface la reçoit.

    Les valeurs écartées partent avec leur raison, au même titre que les
    analysées : sur cette place elles sont souvent la majorité, et les faire
    disparaître d'un tableau donnerait de la cote une image fausse.
    """
    return {
        "instant": criblage.instant.isoformat(),
        "jusqu_a": criblage.jusqu_a.isoformat(),
        "fraicheur": {
            "entete": criblage.entete_fraicheur(),
            "horodatage_le_plus_ancien": (
                criblage.horodatage_le_plus_ancien.isoformat()
                if criblage.horodatage_le_plus_ancien
                else None
            ),
            "age_minutes": _nombre(criblage.age_minutes(), 1),
        },
        "univers": criblage.univers,
        "analysees": len(criblage.analyses),
        "fondamentaux_renseignes": criblage.fondamentaux_renseignes,
        "valeurs": [_analyse_json(analyse) for analyse in criblage.analyses],
        "classements": {
            nom: _classement_json(classement) for nom, classement in criblage.classements.items()
        },
        "ecartees": [{"ticker": e.ticker, "motif": e.motif} for e in criblage.ecartees],
        "couverture_criteres": dict(criblage.couverture_criteres()),
        "propositions": {
            nom: proposition_json(proposition) for nom, proposition in (propositions or {}).items()
        },
        "avertissements": list(criblage.avertissements),
        "mention": MENTION_MARCHE,
    }


def resume_json(etat: EtatSysteme) -> dict[str, Any]:
    """Alias explicite, pour les appelants qui ne veulent que la charge."""
    return serialiser(etat)


__all__ = [
    "COURBE_SEANCES",
    "MENTION_MARCHE",
    "TRAME_SEANCES",
    "courbe",
    "proposition_json",
    "resume_json",
    "serialiser",
    "serialiser_criblage",
    "trame",
]
