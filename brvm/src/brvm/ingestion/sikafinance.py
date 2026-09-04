"""Notes de vérification pour une collecte depuis Sika Finance.

Ce module ne contient **aucun sélecteur, aucune URL de page de cote et aucune
hypothèse de mise en page**. Rien de tel n'a pu être constaté : l'environnement
dans lequel ce connecteur a été écrit n'avait pas accès au site. Écrire des
sélecteurs sans les avoir vus produirait des cours faux sans le signaler, ce qui
est le pire résultat possible pour un outil de suivi de portefeuille.

Ce qui est établi
-----------------
* Sika Finance est un **portail d'information** sur les marchés de la BRVM et de
  l'UEMOA : cotations, actualités, données de sociétés.
* Il publie une page comparative des SGI de la BRVM, où figurent notamment des
  frais de courtage. C'est une **piste** pour retrouver la grille de votre SGI,
  pas une source à recopier telle quelle dans la configuration : le barème qui
  fait foi est celui que votre SGI vous applique, tel qu'il figure sur votre
  convention de compte et sur vos avis d'opéré.
* Seules les SGI sont habilitées à acheminer un ordre en Bourse. Un portail
  d'information n'exécute pas d'ordre. **Le barème de frais à renseigner dans
  `config.yaml` est donc celui de la SGI qui tient votre compte-titres**, même si
  vous suivez le marché ailleurs.

Ce qui reste à vérifier avant d'activer la source
-------------------------------------------------
Voir :data:`PLAN_DE_VERIFICATION`. Tant que ces points ne sont pas tranchés, la
source reste inactive et le connecteur de secours
(:mod:`brvm.ingestion.fichier`) fait tourner tout le reste du système.

Si la page charge ses cotations en JavaScript
---------------------------------------------
L'analyseur de tableaux HTML travaille sur le document servi par le serveur. Si
les cours sont injectés après coup par du script, il ne verra rien — et le dira,
plutôt que de renvoyer un tableau vide silencieusement. Dans ce cas : chercher
une réponse de données exploitable et documentée, ou rester sur le fichier
manuel. Aucun contournement n'est fourni ici.
"""

from __future__ import annotations

from typing import Final

from brvm.config.modeles import ConfigSource, Configuration
from brvm.ingestion.web import Analyseur, AnalyseurNonVerifie

#: Nom de source recommandé dans la configuration.
NOM_SOURCE: Final[str] = "sikafinance"

PLAN_DE_VERIFICATION: Final[tuple[str, ...]] = (
    "1. Lire les conditions d'utilisation du site et vérifier qu'une collecte "
    "automatisée pour un usage personnel y est admise. En cas de doute, demander.",
    "2. Lire https://www.sikafinance.com/robots.txt et vérifier que la page visée n'y "
    "est pas interdite. Le connecteur le revérifie à chaque exécution et s'abstient "
    "si le fichier est illisible, mais la décision d'ensemble vous revient.",
    "3. Relever l'URL exacte de la page de cote que vous consultez et la reporter "
    "dans `sources[].url_base`.",
    "4. Capturer la page : `python -m brvm.ingestion.capture --config config/config.yaml "
    "--source sikafinance`.",
    "5. Lister les tableaux de la capture : `python -m brvm.ingestion.capture "
    "--lister-tableaux <fichier capturé>`. Repérer le rang du tableau des cotations.",
    "6. Reporter dans `sources[].analyseur` le rang du tableau et la correspondance "
    "entre chaque en-tête de colonne du site et le champ du système.",
    "7. Lancer une collecte, puis lire les anomalies : un ticker inconnu, une variation "
    "hors seuil ou une séance hors calendrier signalent presque toujours une colonne "
    "mal associée, pas un incident de marché.",
    "8. Comparer une dizaine de cours collectés avec ce qu'affiche la page. Tant que "
    "cette vérification n'a pas été faite, considérer la source comme non validée.",
    "9. Conserver la capture : elle sert de témoin de la structure du jour où "
    "l'analyseur a été écrit, et permet de constater une évolution du site.",
)

#: Message servi tant qu'aucune structure de page n'a été décrite en configuration.
INSTRUCTIONS: Final[str] = (
    "Aucune structure de page n'a été décrite pour cette source, et le système n'en "
    "invente pas. Renseignez le bloc `analyseur` de la source dans config.yaml après "
    "avoir capturé et inspecté une page réelle. Marche à suivre détaillée dans "
    "brvm.ingestion.sikafinance.PLAN_DE_VERIFICATION."
)


def construire_analyseur(source: ConfigSource, configuration: Configuration) -> Analyseur:
    """Analyseur de la source, ou refus explicite si sa structure n'est pas décrite."""
    if source.analyseur is None or source.analyseur.type == "non_verifie":
        return AnalyseurNonVerifie(source.nom, INSTRUCTIONS)
    # Import tardif : l'analyseur de tableaux dépend de ce module pour ses messages.
    from brvm.ingestion.analyseurs import AnalyseurTableauHtml

    return AnalyseurTableauHtml(source.nom, source.analyseur, configuration)


def plan_de_verification() -> str:
    """Rend le plan de vérification affichable en clair."""
    return "\n".join(PLAN_DE_VERIFICATION)
