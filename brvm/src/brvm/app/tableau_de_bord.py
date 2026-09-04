"""Tableau de bord Streamlit.

Ce module ne calcule **rien**. Il lit l'état assemblé par :mod:`brvm.app.etat` et
l'affiche. C'est délibéré : un écran qui recalcule pour son compte finit par
montrer un total qui ne correspond ni à l'export, ni aux alertes, et personne ne
sait lequel croire.

Chaque onglet commence par le bandeau de fraîcheur — l'âge de la donnée la plus
ancienne employée. C'est la seule information qui conditionne toutes les autres :
un portefeuille valorisé sur des cours de la semaine dernière n'est pas faux, il
est daté, et le lire comme s'il était d'aujourd'hui l'est.

Lancement ::

    pip install -e '.[tableau]'
    streamlit run src/brvm/app/tableau_de_bord.py -- --config config/config.yaml
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from brvm.app.etat import MOTIF_PERFORMANCE_ABSENTE, EtatSysteme, assembler
from brvm.app.export import MENTION
from brvm.config.chargement import charger_configuration, construire_calendrier_depuis_config
from brvm.domain.monnaie import format_xof
from brvm.storage.base import BaseDonnees
from brvm.utils.erreurs import ErreurBrvm, ErreurConfiguration


def _streamlit() -> Any:
    try:
        import streamlit
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise ErreurConfiguration(
            "Streamlit n'est pas installé : le tableau de bord est indisponible. "
            "Installez l'extra dédié (`pip install -e '.[tableau]'`), ou utilisez "
            "`python -m brvm.app.cli etat` qui affiche la même information en texte.",
        ) from exc
    return streamlit


def charger_etat(chemin_config: Path) -> EtatSysteme:
    """Compose l'état à afficher. Aucune écriture, aucune collecte réseau."""
    configuration = charger_configuration(chemin_config)
    calendrier = construire_calendrier_depuis_config(configuration)
    with BaseDonnees(configuration.general.base_donnees) as base:
        return assembler(base, configuration, calendrier, instant=datetime.now(UTC))


def _bandeau(st: Any, etat: EtatSysteme) -> None:
    """Bandeau de fraîcheur, en tête de chaque onglet. Jamais optionnel."""
    texte = etat.entete_fraicheur()
    if etat.donnee_perimee():
        st.error(
            f"{texte} — au-delà du seuil de "
            f"{etat.configuration.alertes.age_donnee_max_minutes} minutes que vous avez "
            "déclaré. Les chiffres ci-dessous décrivent cette date, pas aujourd'hui."
        )
    else:
        st.info(texte)


def _onglet_portefeuille(st: Any, etat: EtatSysteme) -> None:
    _bandeau(st, etat)
    portefeuille = etat.portefeuille

    colonnes = st.columns(4)
    colonnes[0].metric("Coût engagé", format_xof(portefeuille.cout_total))
    colonnes[1].metric("Valeur", format_xof(portefeuille.valeur_totale))
    colonnes[2].metric(
        "Plus-value latente brute", format_xof(portefeuille.plus_value_latente_brute)
    )
    colonnes[3].metric(
        "Nette de frais et d'impôt", format_xof(portefeuille.plus_value_latente_nette)
    )
    st.caption(MOTIF_PERFORMANCE_ABSENTE)

    if portefeuille.lignes_non_valorisees:
        st.warning(
            "Lignes non valorisées, faute de cours : "
            + ", ".join(ligne.ticker for ligne in portefeuille.lignes_non_valorisees)
            + ". Elles ne sont pas comptées pour zéro — le total ci-dessus est incomplet."
        )

    st.dataframe(
        [
            {
                "Valeur": ligne.ticker,
                "Quantité": ligne.quantite,
                "PRU": f"{ligne.prix_revient_unitaire:.2f}",
                "Cours": format_xof(ligne.cours) if ligne.cours is not None else "—",
                "Séance": ligne.date_cours.isoformat() if ligne.date_cours else "—",
                "Âge (min)": _age(ligne.age_minutes(etat.instant)),
                "Valeur totale": format_xof(ligne.valeur) if ligne.valeur is not None else "—",
                "Poids": f"{ligne.poids:.2%}" if ligne.poids is not None else "—",
                "+/- latente nette": (
                    format_xof(ligne.plus_value_latente_nette)
                    if ligne.plus_value_latente_nette is not None
                    else "—"
                ),
            }
            for ligne in portefeuille.lignes
        ],
        width="stretch",
    )


def _age(valeur: Decimal | None) -> str:
    return f"{valeur:.0f}" if valeur is not None else "—"


def _onglet_signaux(st: Any, etat: EtatSysteme) -> None:
    _bandeau(st, etat)
    st.caption(
        "Constats techniques, pas des recommandations. La colonne « exécutable le » "
        "rappelle qu'un franchissement constaté à la clôture ne pouvait pas être joué "
        "pendant la séance qui l'a produit."
    )
    if not etat.signaux:
        st.write("Aucun signal constaté sur l'historique disponible.")
        return
    st.dataframe(
        [
            {
                "Valeur": signal.ticker,
                "Sens": signal.sens.value,
                "Règle": signal.regle,
                "Constaté le": signal.date_constat.isoformat(),
                "Exécutable le": signal.date_execution.isoformat(),
                "Confiance": signal.confiance.niveau,
                "Avertissements": " ".join(signal.avertissements) or "—",
            }
            for signal in etat.signaux
        ],
        width="stretch",
    )


def _onglet_risque(st: Any, etat: EtatSysteme) -> None:
    _bandeau(st, etat)
    rapport = etat.risque
    depassements = rapport.depassements()
    if depassements:
        st.warning(
            f"{len(depassements)} limite(s) de concentration dépassée(s) : "
            + ", ".join(f"{c.dimension.value} {c.cle}" for c in depassements)
        )
    st.subheader("Concentration")
    st.dataframe(
        [
            {
                "Dimension": constat.dimension.value,
                "Objet": constat.cle,
                "Poids": f"{constat.poids:.2%}",
                "Limite": f"{constat.limite:.2%}",
                "Respecté": "oui" if constat.respecte else "NON",
            }
            for constat in rapport.concentrations
        ],
        width="stretch",
    )
    st.subheader("Liquidité")
    st.caption(
        "Le délai de débouclage suppose que vous ne prenez qu'une part du volume "
        "habituel. Sur une valeur peu échangée, il se compte en semaines."
    )
    st.dataframe(
        [
            {
                "Valeur": constat.ticker,
                "Titres détenus": constat.quantite_detenue,
                "Volume moyen": f"{constat.volume_moyen:.0f}",
                "Séances cotées": f"{constat.seances_cotees}/{constat.seances_observees}",
                "Séances pour solder": (
                    f"{constat.seances_pour_deboucler:.1f}"
                    if constat.seances_pour_deboucler is not None
                    else "non mesurable"
                ),
            }
            for constat in rapport.liquidites
        ],
        width="stretch",
    )
    if rapport.stops:
        st.subheader("Stops ATR")
        for stop in rapport.stops:
            st.write(f"• {stop.resume()}")
            for message in stop.avertissements:
                st.caption(f"⚠ {message}")
    for message in rapport.avertissements:
        st.caption(f"⚠ {message}")


def _onglet_donnees(st: Any, etat: EtatSysteme) -> None:
    _bandeau(st, etat)
    st.subheader("Anomalies ouvertes")
    if etat.anomalies:
        st.caption(
            "Une cotation en quarantaine est écrite en base pour investigation et "
            "exclue de tous les calculs. Rien n'est corrigé en silence."
        )
        st.dataframe(
            [
                {
                    "Détectée le": anomalie.detectee_le.isoformat(),
                    "Gravité": anomalie.gravite.value,
                    "Source": anomalie.source,
                    "Type": anomalie.type_anomalie,
                    "Valeur": anomalie.ticker or "—",
                    "Message": anomalie.message,
                }
                for anomalie in etat.anomalies
            ],
            width="stretch",
        )
    else:
        st.write("Aucune anomalie ouverte.")

    st.subheader("Journal des collectes")
    for ligne in etat.journal_collectes:
        st.text(ligne)

    if etat.avertissements:
        st.subheader("Avertissements")
        for message in etat.avertissements:
            st.caption(f"⚠ {message}")


def afficher(chemin_config: Path) -> None:
    """Point d'entrée Streamlit."""
    st = _streamlit()
    st.set_page_config(page_title="Suivi BRVM", layout="wide")
    st.title("Suivi de portefeuille — BRVM")

    try:
        etat = charger_etat(chemin_config)
    except ErreurBrvm as exc:
        st.error(str(exc))
        return

    onglets = st.tabs(["Portefeuille", "Signaux", "Risque", "Données"])
    with onglets[0]:
        _onglet_portefeuille(st, etat)
    with onglets[1]:
        _onglet_signaux(st, etat)
    with onglets[2]:
        _onglet_risque(st, etat)
    with onglets[3]:
        _onglet_donnees(st, etat)

    st.divider()
    st.caption(MENTION)


def _config_depuis_arguments(arguments: list[str] | None = None) -> Path:
    analyseur = argparse.ArgumentParser(prog="tableau_de_bord")
    analyseur.add_argument("--config", type=Path, required=True)
    connues, _ = analyseur.parse_known_args(arguments)
    chemin: Path = connues.config
    return chemin


if __name__ == "__main__":  # pragma: no cover - exécuté par Streamlit
    afficher(_config_depuis_arguments(sys.argv[1:]))
