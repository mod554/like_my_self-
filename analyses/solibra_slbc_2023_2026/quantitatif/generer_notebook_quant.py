#!/usr/bin/env python3
"""Convertit analyse_quantitative_solibra.py (cellules séparées par '# %%') en notebook .ipynb."""
import os
import nbformat as nbf

ICI = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(ICI, "analyse_quantitative_solibra.py"), encoding="utf-8").read().splitlines()
cellules, courant, genre = [], [], None

def fermer():
    global courant, genre
    if genre is None:
        return
    texte = "\n".join(courant).strip("\n")
    if genre == "markdown":
        lignes = [l[2:] if l.startswith("# ") else (l[1:] if l.startswith("#") else l) for l in texte.splitlines()]
        cellules.append(nbf.v4.new_markdown_cell("\n".join(lignes)))
    elif texte.strip():
        cellules.append(nbf.v4.new_code_cell(texte))
    courant = []

for l in src:
    if l.startswith("# %%"):
        fermer()
        genre = "markdown" if "[markdown]" in l else "code"
        continue
    if genre is None:
        continue
    courant.append(l)
fermer()
nb = nbf.v4.new_notebook()
nb.cells = cellules
nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
               "language_info": {"name": "python"}, "colab": {"provenance": []}}
nbf.write(nb, os.path.join(ICI, "ANALYSE_QUANTITATIVE_SOLIBRA_2023_2026.ipynb"))
print("cellules :", len(cellules))
