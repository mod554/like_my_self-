#!/usr/bin/env python3
"""Génère analyse_solibra_colab.ipynb à partir de analyse_solibra_colab.py
(le code du notebook est exactement celui du script testé)."""
import os

import nbformat as nbf

ICI = os.path.dirname(os.path.abspath(__file__))
code = open(os.path.join(ICI, "analyse_solibra_colab.py"), encoding="utf-8").read()

nb = nbf.v4.new_notebook()
nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3"},
               "language_info": {"name": "python"}, "colab": {"provenance": []}}
c = []
c.append(nbf.v4.new_markdown_cell(
    "# Analyse SOLIBRA (SLBC.CI), 2023 à 2026\n\n"
    "**Entrée** : `SOLIBRA_SLBC_2023_2026_ANALYSE.csv` (`Date,Close,Volume`), ou le ZIP livré qui le contient avec "
    "`CALENDRIER_COUVERTURE_2023_2026.csv` et `METADONNEES_SERIE.json`.\n\n"
    "**Garde-fous**\n"
    "- Aucune ligne n'est supprimée en silence : les lignes écartées sont listées dans `tables/lignes_ecartees.csv`.\n"
    "- Un rendement n'est quotidien que si ses deux dates sont des séances successives du calendrier officiel.\n"
    "- Les rendements qui traversent une suspension ou le fractionnement (cours non ajustés) sont exclus.\n"
    "- Aucun réajustement de cours n'est appliqué.\n"
    "- L'annualisation suit le calendrier officiel ou une hypothèse sourcée. La valeur 252 n'est jamais imposée.\n"
    "- Le bêta, le ratio de Sharpe et le rendement total ne sont calculés que si les données nécessaires sont fournies.\n\n"
    "La réussite de l'exécution ne prouve pas l'exactitude financière des données."))
c.append(nbf.v4.new_markdown_cell("## 1. Code d'analyse\n\nCette cellule écrit le module testé, puis l'importe."))
c.append(nbf.v4.new_code_cell("%%writefile analyse_solibra_colab.py\n" + code))
c.append(nbf.v4.new_code_cell(
    "import importlib, sys\nsys.path.insert(0, '.')\nimport analyse_solibra_colab as A\nimportlib.reload(A)"))
c.append(nbf.v4.new_markdown_cell(
    "## 2. Données\n\nSous Colab, laissez `ENTREE = None` pour téléverser le ZIP ou le CSV. Ailleurs, indiquez le chemin du fichier."))
c.append(nbf.v4.new_code_cell(
    "ENTREE = None  # ex. 'BASE_SOLIBRA_SLBC_2023_2026.zip'\n"
    "if ENTREE is None:\n"
    "    try:\n"
    "        from google.colab import files\n"
    "        ENTREE = next(iter(files.upload()))\n"
    "    except ImportError:\n"
    "        raise SystemExit('Hors Colab : renseignez ENTREE')\n"
    "print('Fichier :', ENTREE)"))
c.append(nbf.v4.new_markdown_cell(
    "## 3. Paramètres\n\n"
    "Toute hypothèse doit être sourcée. Si un paramètre reste à `None`, le module qui en dépend n'est pas exécuté, "
    "et le notebook l'indique."))
c.append(nbf.v4.new_code_cell(
    "PARAM = dict(\n"
    "    sortie='resultats',\n"
    "    calendrier=None,            # si le calendrier n'est pas dans le ZIP\n"
    "    close_ajuste=None,          # None = lu dans METADONNEES_SERIE.json ; sinon 'NON' / 'OUI' / 'INCONNU'\n"
    "    seances_par_an=None, source_annualisation=None,\n"
    "    taux_sans_risque=None, source_taux=None,\n"
    "    indice=None,                # CSV Date,Close de l'indice BRVM, pour le bêta\n"
    "    dividendes=None,            # CSV de dividendes vérifiés\n"
    "    accepter_non_verifie=False, # True : calculs sans calendrier, étiquetés NON VÉRIFIÉ\n"
    ")"))
c.append(nbf.v4.new_markdown_cell("## 4. Exécution des modules"))
c.append(nbf.v4.new_code_cell(
    "rapport = A.executer(ENTREE, afficher=True, **PARAM)"))
c.append(nbf.v4.new_markdown_cell("## 5. Tableaux produits"))
c.append(nbf.v4.new_code_cell(
    "import os, pandas as pd\n"
    "from IPython.display import display\n"
    "t = os.path.join(PARAM['sortie'], 'tables')\n"
    "for f in sorted(os.listdir(t)):\n"
    "    print('==', f)\n"
    "    display(pd.read_csv(os.path.join(t, f)).head(20))"))
c.append(nbf.v4.new_markdown_cell("## 6. État des modules et export"))
c.append(nbf.v4.new_code_cell(
    "import json\n"
    "print(json.dumps(rapport.get('modules', {}), ensure_ascii=False, indent=1))\n"
    "print('Avertissements :', rapport.get('avertissements'))\n"
    "try:\n"
    "    from google.colab import files\n"
    "    files.download(PARAM['sortie'] + '_export.zip')\n"
    "except ImportError:\n"
    "    print('Export :', PARAM['sortie'] + '_export.zip')"))
nb.cells = c
nbf.write(nb, os.path.join(ICI, "analyse_solibra_colab.ipynb"))
print("notebook écrit :", len(c), "cellules")
