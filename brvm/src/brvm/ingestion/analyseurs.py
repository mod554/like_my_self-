"""Analyse de pages : extraction de tableaux HTML, pilotée par votre description.

Ce module ne connaît la mise en page d'aucun site. Il sait seulement extraire les
tableaux d'une page et appliquer une **correspondance de colonnes que vous avez
écrite après avoir regardé la page**. C'est la seule façon honnête d'analyser une
source dont personne n'a garanti la structure : le système exécute votre
description, il n'en invente aucune.

Marche à suivre pour activer une source :

1. capturer une page : ``python -m brvm.ingestion.capture --source <nom>`` ;
2. lister ses tableaux : ``python -m brvm.ingestion.capture --lister-tableaux …`` ;
3. reporter dans la configuration le rang du bon tableau et la correspondance
   entre ses en-têtes et les champs du système ;
4. relancer une collecte et vérifier les anomalies signalées.
"""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
from typing import Any, Final
from zoneinfo import ZoneInfo

from brvm.config.modeles import ConfigAnalyseur, Configuration
from brvm.ingestion.web import ContexteAnalyse
from brvm.utils.erreurs import ErreurSource

#: Balises ouvrant une cellule.
CELLULES: Final[frozenset[str]] = frozenset({"td", "th"})

#: Balises dont le contenu textuel n'a rien à faire dans une cellule.
IGNOREES: Final[frozenset[str]] = frozenset({"script", "style"})

Tableau = list[list[str]]


class _ExtracteurTableaux(HTMLParser):
    """Extrait tous les tableaux d'une page sous forme de listes de cellules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tableaux: list[Tableau] = []
        self._pile: list[Tableau] = []
        self._ligne: list[str] | None = None
        self._cellule: list[str] | None = None
        self._ignorer = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in IGNOREES:
            self._ignorer += 1
        elif tag == "table":
            self._pile.append([])
        elif tag == "tr" and self._pile:
            self._cloturer_ligne()
            self._ligne = []
        elif tag in CELLULES and self._pile:
            self._cloturer_cellule()
            self._cellule = []
        elif tag == "br" and self._cellule is not None:
            self._cellule.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in IGNOREES:
            self._ignorer = max(0, self._ignorer - 1)
        elif tag in CELLULES:
            self._cloturer_cellule()
        elif tag == "tr":
            self._cloturer_ligne()
        elif tag == "table":
            self._cloturer_ligne()
            if self._pile:
                self.tableaux.append(self._pile.pop())

    def handle_data(self, data: str) -> None:
        if self._ignorer == 0 and self._cellule is not None:
            self._cellule.append(data)

    def close(self) -> None:
        super().close()
        # Page mal formée : on récupère ce qui a pu être lu plutôt que de tout perdre.
        self._cloturer_ligne()
        while self._pile:
            self.tableaux.append(self._pile.pop())

    def _cloturer_cellule(self) -> None:
        if self._cellule is None:
            return
        texte = " ".join("".join(self._cellule).split())
        if self._ligne is None:
            self._ligne = []
        self._ligne.append(texte)
        self._cellule = None

    def _cloturer_ligne(self) -> None:
        self._cloturer_cellule()
        if self._ligne is not None:
            if self._ligne and self._pile:
                self._pile[-1].append(self._ligne)
            self._ligne = None


def extraire_tableaux(contenu: str) -> list[Tableau]:
    """Renvoie tous les tableaux de la page, dans l'ordre de fermeture des balises."""
    extracteur = _ExtracteurTableaux()
    extracteur.feed(contenu)
    extracteur.close()
    return extracteur.tableaux


def resumer_tableaux(contenu: str, lignes_exemple: int = 3) -> str:
    """Décrit les tableaux d'une page, pour aider à remplir la configuration."""
    tableaux = extraire_tableaux(contenu)
    if not tableaux:
        return "Aucun tableau HTML trouvé dans cette page."
    morceaux: list[str] = [f"{len(tableaux)} tableau(x) trouvé(s).\n"]
    for index, tableau in enumerate(tableaux):
        entetes = tableau[0] if tableau else []
        morceaux.append(f"--- index_tableau: {index}  ({len(tableau)} ligne(s)) ---")
        morceaux.append(f"  en-têtes : {entetes}")
        for ligne in tableau[1 : 1 + lignes_exemple]:
            morceaux.append(f"  exemple  : {ligne}")
        morceaux.append("")
    return "\n".join(morceaux)


def _normaliser(entete: str) -> str:
    return " ".join(entete.split()).casefold()


class AnalyseurTableauHtml:
    """Applique une correspondance de colonnes déclarée en configuration."""

    def __init__(self, nom: str, reglage: ConfigAnalyseur, configuration: Configuration) -> None:
        self.nom = nom
        self.reglage = reglage
        self.configuration = configuration
        self._correspondance = {
            _normaliser(entete): champ for entete, champ in reglage.colonnes.items()
        }

    def url_pour(self, url_base: str, jour: date | None) -> str:
        """L'URL configurée, telle quelle.

        Aucun paramètre de requête n'est ajouté : le système ne connaît pas la
        façon dont un site donné désigne une séance passée. Pour interroger une
        autre date, déclarez une seconde source avec l'URL correspondante.
        """
        return url_base

    def analyser(self, contenu: str, contexte: ContexteAnalyse) -> list[dict[str, Any]]:
        tableaux = extraire_tableaux(contenu)
        if self.reglage.index_tableau >= len(tableaux):
            raise ErreurSource(
                f"La page ne contient que {len(tableaux)} tableau(x), or la configuration "
                f"désigne le tableau d'index {self.reglage.index_tableau}. La structure de "
                "la page a probablement changé : recapturez-la et vérifiez l'index.",
                source=self.nom,
                url=contexte.url,
            )
        tableau = tableaux[self.reglage.index_tableau]
        if len(tableau) < 2:
            raise ErreurSource(
                "Le tableau désigné ne comporte pas de ligne de données sous son en-tête.",
                source=self.nom,
                url=contexte.url,
            )

        entetes = [_normaliser(cellule) for cellule in tableau[0]]
        positions = {
            index: self._correspondance[entete]
            for index, entete in enumerate(entetes)
            if entete in self._correspondance
        }
        attendus = set(self._correspondance.values())
        trouves = set(positions.values())
        if manquants := attendus - trouves:
            raise ErreurSource(
                "En-têtes déclarés introuvables dans le tableau : "
                + ", ".join(sorted(manquants))
                + f". En-têtes réellement présents : {tableau[0]}. La page a changé, ou "
                "l'index de tableau ne désigne pas le bon.",
                source=self.nom,
                url=contexte.url,
            )

        jour_par_defaut = self._jour_par_defaut(contexte)
        lignes: list[dict[str, Any]] = []
        for cellules in tableau[1:]:
            if not any(cellule.strip() for cellule in cellules):
                continue
            brut: dict[str, Any] = {
                champ: cellules[index]
                for index, champ in positions.items()
                if index < len(cellules)
            }
            if not brut.get("ticker"):
                continue
            if self.reglage.date_seance_depuis == "jour_de_collecte":
                brut["date_seance"] = jour_par_defaut.isoformat()
            lignes.append(brut)
        return lignes

    def _jour_par_defaut(self, contexte: ContexteAnalyse) -> date:
        """Séance retenue quand la page ne porte pas la date.

        Priorité à la séance explicitement demandée, puis à la date annoncée par
        le serveur, puis à l'instant de collecte — toutes ramenées au fuseau du
        marché, pas à UTC : une collecte à 23 h à Abidjan ne doit pas être datée
        du lendemain.
        """
        if contexte.jour is not None:
            return contexte.jour
        fuseau = ZoneInfo(self.configuration.general.fuseau_horaire)
        reference = contexte.horodatage_donnee or contexte.horodatage_collecte
        return reference.astimezone(fuseau).date()
