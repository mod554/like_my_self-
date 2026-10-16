import ast
import base64
import datetime as dt
import html
import io
import os
import re
import shutil
import sys
import tempfile
import tokenize

import markdown as mdlib
import nbclient
import nbformat
import platform

ICI = os.path.dirname(os.path.abspath(__file__))
SRC = "/root/.claude/uploads/44df76f8-2e9e-57b0-9740-d4e1ca4f6b6b/20150d97-ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026_COLAB_1.ipynb"
DONNEES = os.path.join(ICI, "..", "colab_pret")
NB_PROPRE = os.path.join(ICI, "ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026.ipynb")
NB_EXEC = os.path.join(ICI, "ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026_EXECUTE.ipynb")
PDF = os.path.join(ICI, "ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026.pdf")
TITRE = "Analyse quantitative de SOLIBRA (SLBC.CI), 01/01/2023 - 15/10/2026"
AUTEUR = "Yolou Ahoua Marius Tresor"
FONCTION = "Trader commodities and currency"
DATE_TEXTE = "16 octobre 2026"

TEXTES = {
    "## Configuration": "Les paramètres de l'étude sont regroupés dans une seule cellule : période, dates des événements, "
                        "fenêtres de calcul et nombre de répliques du bootstrap.",
    "## A.": "L'étude décrit le cours, le volume et le risque historique de SOLIBRA entre le 1er janvier 2023 et le "
             "15 octobre 2026. Elle porte sur les données publiées par la source retenue, et non sur les cotations officielles "
             "de la BRVM.",
    "## B.": "Les fichiers sont lus selon leur contenu réel. Un fichier CSV renommé en .zip est accepté ; une archive "
             "corrompue ou tronquée provoque une erreur explicite au lieu d'un plantage incompréhensible.",
    "## C.": "Les dates, les nombres, les doublons, les valeurs manquantes et les volumes sont contrôlés. Les effectifs "
             "annuels et trimestriels sont donnés, ainsi que la part des jours ouvrés portant une observation.",
    "### C.2": "Chaque observation exclue figure avec sa date, ses valeurs, sa raison et sa référence. Les jours ouvrés "
               "sans observation sont listés sans être comblés.",
    "## D.": "Les événements sur titre sont tirés des documents fournis : suspension, levée de suspension, fractionnement "
             "et dividendes.",
    "### D.2": "Les cours publiés ne sont pas ajustés du fractionnement de 2024. Tout calcul qui traverse la date du "
               "fractionnement est donc bloqué.",
    "### D.3": "Trois séries sont conservées séparément : la série source, l'absence de série ajustée et l'échantillon "
               "retenu pour chaque analyse.",
    "## E.": "Cette partie décrit l'évolution des cours, la performance, les baisses maximales et la distribution des "
             "rendements.",
    "### E.2": "Chaque jour ouvré civil est classé : observation retenue, observation exclue, suspension, retrait par la "
               "source ou absence non expliquée.",
    "### E.3": "La performance est la variation du cours entre le premier et le dernier point observés dans chaque segment. "
               "Elle ne tient pas compte des dividendes.",
    "### E.4": "Le drawdown mesure la baisse depuis le plus haut précédent. Le tableau donne les dates du sommet et du creux, "
               "et la date de récupération lorsqu'elle est observée.",
    "### E.5": "Les statistiques portent sur les rendements admissibles, c'est-à-dire ceux entre deux séances consécutives "
               "sans lacune et hors suspension ou fractionnement.",
    "## F.": "Cette partie porte sur la volatilité, le risque historique et les volumes publiés.",
    "### F.2": "La volatilité glissante est calculée sur 20 et 60 rendements, à l'intérieur de chaque segment.",
    "### F.3": "Les pertes historiques à 95 % et 99 % sont calculées à un jour. Les intervalles de confiance utilisent un "
               "bootstrap par blocs, qui conserve la dépendance entre observations voisines.",
    "### F.4": "Les volumes publiés sont comparés uniquement à l'intérieur d'un même régime d'unités d'action, avant ou "
               "après le fractionnement.",
    "## G.": "Cette partie teste la normalité, la dépendance temporelle et la stationnarité, puis vérifie la sensibilité des "
             "résultats à l'échantillon.",
    "### G.2": "Les tests d'autocorrélation, d'effet ARCH et de stationnarité sont appliqués séparément à chaque segment.",
    "### G.3": "Les intervalles de confiance sont obtenus par bootstrap par blocs pour tenir compte de la dépendance temporelle.",
    "### G.4": "Les statistiques et les VaR sont recalculées sur plusieurs échantillons pour mesurer leur sensibilité.",
    "### G.5": "Le tableau de robustesse est lu variante par variante. Aucune observation n'est retirée pour améliorer un résultat.",
    "## H.": "Le titre est comparé à l'indice BRVM Composite sur les dates communes.",
    "### H.2": "Les rendements sont appariés sur les mêmes paires de dates consécutives. Les dates non appariées sont listées.",
    "### H.3": "Les corrélations sont mesurées par Pearson et Spearman. La régression utilise des erreurs standards HAC.",
    "### H.4": "Les performances des cours sont comparées sur les mêmes bornes que le titre.",
}

TITRES_AJOUTES = {
    "ev = evenements.copy()": "### D.1 Événements documentés\n\nLes dates des événements sont reprises telles qu'elles figurent dans les documents.",
    "fig, ax = plt.subplots(figsize=(10, 4.5))": "### E.1 Évolution des cours\n\nLe cours publié est tracé segment par segment. Les segments ne sont pas reliés entre eux.",
    "vol_obs = {": "### F.1 Volatilité à la fréquence observée\n\nL'écart-type est calculé par observation, sans annualisation faute de calendrier officiel.",
    "x = R_Q.r_log.values": "### G.1 Distribution des rendements\n\nL'histogramme, la fonction de répartition et le graphique quantile-quantile sont tracés pour les rendements logarithmiques.",
    "ind = indice_brut.copy()": "### H.1 Couverture de l'indice\n\nL'indice BRVM Composite est restreint à la période d'étude et vérifié avant tout appariement.",
}

OPTIQUE = (
    "Le notebook charge les fichiers produits par la collecte : cours et volumes, journal des exclusions, calendrier, "
    "dividendes, événements et indice BRVM Composite. Il contrôle d'abord les données, puis sépare les rendements "
    "admissibles de ceux qui franchissent une lacune, une suspension ou le fractionnement. Il calcule ensuite la "
    "performance, le drawdown, la volatilité, la VaR et l'Expected Shortfall, les diagnostics statistiques, la robustesse "
    "et la comparaison à l'indice. Chaque étape affiche son effectif. Aucune donnée n'est comblée, interpolée ni ajustée."
)

BLOC_TITRE = (
    f"# {TITRE}\n\n"
    f"**{AUTEUR}**, {FONCTION}\n\n"
    f"{DATE_TEXTE}\n\n"
    "## Optique du code\n\n" + OPTIQUE
)


def retirer_commentaires(code):
    lignes = code.split("\n")
    try:
        arbre = ast.parse(code)
    except SyntaxError:
        return code
    a_supprimer = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.FunctionDef, ast.ClassDef)) and noeud.body:
            premier = noeud.body[0]
            if isinstance(premier, ast.Expr) and isinstance(getattr(premier, "value", None), ast.Constant) \
                    and isinstance(premier.value.value, str):
                for k in range(premier.lineno - 1, premier.end_lineno):
                    a_supprimer.add(k)
    lignes = [l for i, l in enumerate(lignes) if i not in a_supprimer]
    texte = "\n".join(lignes)
    sortie = io.StringIO()
    jetons = list(tokenize.generate_tokens(io.StringIO(texte).readline))
    coupes = {}
    for j in jetons:
        if j.type == tokenize.COMMENT:
            coupes[j.start[0] - 1] = j.start[1]
    nouvelles = []
    for i, l in enumerate(texte.split("\n")):
        if i in coupes:
            l = l[: coupes[i]].rstrip()
            if not l.strip():
                continue
        nouvelles.append(l.rstrip())
    resultat = "\n".join(nouvelles)
    resultat = re.sub(r"\n{3,}", "\n\n", resultat).strip("\n")
    compile(resultat, "<cellule>", "exec")
    return resultat


def construire_notebook_propre():
    nb = nbformat.read(SRC, as_version=4)
    cellules = []
    for c in nb.cells:
        premiere = c.source.strip().splitlines()[0] if c.source.strip() else ""
        if premiere.startswith("## I. ") or premiere.startswith("## J. "):
            break
        if c.cell_type == "markdown":
            if premiere.startswith("# Analyse quantitative"):
                cellules.append(nbformat.v4.new_markdown_cell(BLOC_TITRE))
                continue
            cle = next((k for k in TEXTES if premiere.startswith(k)), None)
            if cle is not None:
                entete = premiere
                cellules.append(nbformat.v4.new_markdown_cell(f"{entete}\n\n{TEXTES[cle]}"))
                continue
            cellules.append(c)
            continue
        code = retirer_commentaires(c.source)
        cellules.append(nbformat.v4.new_code_cell(code))
    propre = nbformat.v4.new_notebook()
    propre.cells = cellules
    propre.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"}, "colab": {"provenance": []}}
    nbformat.write(propre, NB_PROPRE)
    return propre


def executer(propre):
    travail = tempfile.mkdtemp()
    for f in os.listdir(DONNEES):
        if f.endswith((".csv", ".json")):
            shutil.copy(os.path.join(DONNEES, f), travail)
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(
        "import types, sys, os, glob\n"
        "_m = types.ModuleType('google.colab'); _f = types.ModuleType('google.colab.files')\n"
        "_f.upload = lambda: {p: open(p,'rb').read() for p in glob.glob('*.csv')+glob.glob('*.json')}\n"
        "_m.files = _f; sys.modules['google.colab'] = _m; sys.modules['google.colab.files'] = _f\n"
        "os.environ['MPLBACKEND'] = 'module://matplotlib_inline.backend_inline'\n")] + propre.cells
    cl = nbclient.NotebookClient(nb, timeout=1800, kernel_name="python3",
                                 resources={"metadata": {"path": travail}}, allow_errors=True)
    cl.execute()
    erreurs = [(i, o.ename, o.evalue[:200]) for i, c in enumerate(nb.cells) if c.cell_type == "code"
               for o in c.get("outputs", []) if o.output_type == "error"]
    nb.cells = nb.cells[1:]
    nbformat.write(nb, NB_EXEC)
    return nb, travail, erreurs


def sortie_html(sortie):
    if sortie.output_type == "stream":
        return f'<pre class="sortie">{html.escape(sortie.text)}</pre>'
    if sortie.output_type in ("execute_result", "display_data"):
        d = sortie.data
        if "image/png" in d:
            return f'<figure><img src="data:image/png;base64,{d["image/png"]}"/></figure>'
        if "text/html" in d:
            return f'<div class="tableau">{d["text/html"]}</div>'
        if "text/plain" in d:
            return f'<pre class="sortie">{html.escape(d["text/plain"])}</pre>'
    return ""


def versions():
    import matplotlib, numpy, pandas, scipy, seaborn, statsmodels
    return {"Python": platform.python_version(), "pandas": pandas.__version__, "numpy": numpy.__version__,
            "matplotlib": matplotlib.__version__, "seaborn": seaborn.__version__, "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__}


def html_document(nb):
    corps = []
    for c in nb.cells:
        if c.cell_type == "markdown":
            if c.source.startswith("# "):
                corps.append(f'<div class="titre"><h1>{TITRE}</h1>'
                             + mdlib.markdown("\n".join(c.source.splitlines()[2:]), extensions=["extra"]) + '</div>')
                continue
            corps.append(mdlib.markdown(c.source, extensions=["extra"]))
        elif c.cell_type == "code":
            sorties = "".join(sortie_html(o) for o in c.get("outputs", []))
            corps.append(f'<pre class="code">{html.escape(c.source)}</pre>{sorties}')
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{TITRE}</title>
<style>
@page {{ size: A4; margin: 2cm; }}
body {{ font-family: "Georgia", "Times New Roman", serif; font-size: 10.5pt; line-height: 1.45; color: #111; }}
.titre {{ margin-bottom: 0.6cm; border-bottom: 1px solid #999; padding-bottom: 0.4cm; }}
.titre h1 {{ font-size: 18pt; margin: 0.2cm 0 0.3cm 0; }}
h2 {{ font-size: 14pt; margin-top: 0.9cm; border-bottom: 1px solid #ddd; padding-bottom: 0.15cm; page-break-after: avoid; }}
h3 {{ font-size: 11.5pt; margin-top: 0.6cm; page-break-after: avoid; }}
p {{ text-align: justify; margin: 0.2cm 0; }}
pre.code {{ font-family: "Courier New", monospace; font-size: 7.2pt; background: #f4f6f8; border-left: 3px solid #7a8a99; padding: 0.2cm; white-space: pre-wrap; word-break: break-word; page-break-inside: avoid; }}
pre.sortie {{ font-family: "Courier New", monospace; font-size: 7.2pt; background: #fbfbfb; border: 1px solid #e5e5e5; padding: 0.2cm; white-space: pre-wrap; word-break: break-word; }}
figure {{ margin: 0.3cm 0; text-align: center; page-break-inside: avoid; }}
figure img {{ width: 100%; }}
.tableau {{ overflow: hidden; }}
.tableau table {{ border-collapse: collapse; font-family: "Helvetica", sans-serif; font-size: 7.2pt; margin: 0.2cm auto; }}
.tableau th, .tableau td {{ border-bottom: 1px solid #ccc; padding: 2px 5px; text-align: right; }}
.tableau th {{ font-weight: bold; }}
</style></head><body>
{''.join(corps)}
</body></html>"""


def generer_pdf(html_texte):
    from playwright.sync_api import sync_playwright
    chemin_html = os.path.join(ICI, "publication.html")
    open(chemin_html, "w", encoding="utf-8").write(html_texte)
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
        page = nav.new_page()
        page.goto("file://" + chemin_html, wait_until="load")
        page.pdf(path=PDF, format="A4", print_background=True,
                 margin={"top": "2cm", "bottom": "2cm", "left": "2cm", "right": "2cm"},
                 display_header_footer=True,
                 header_template="<span></span>",
                 footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#777;font-family:Georgia">'
                                 '<span class="pageNumber"></span></div>')
        nav.close()


if __name__ == "__main__":
    propre = construire_notebook_propre()
    nb, travail, erreurs = executer(propre)
    print("erreurs d'exécution :", erreurs)
    print("cellules :", len(nb.cells), "| code :", sum(c.cell_type == "code" for c in nb.cells))
    generer_pdf(html_document(nb))
    print("PDF :", PDF, os.path.getsize(PDF))
