# -*- coding: utf-8 -*-
# %% [markdown]
# # Analyse quantitative de SOLIBRA (SLBC.CI), 01/01/2023 - 15/10/2026
#
# **Périmètre.** Cours et volumes publiés pour SOLIBRA, importés du dépôt public `harzat/brvm-data-public`
# (commit `ed5e3e3`) et contrôlés dans `analyses/solibra_slbc_2023_2026`. L'indice BRVM Composite provient du même dépôt.
#
# **Question.** Quelles caractéristiques descriptives, de risque et de dépendance temporelle peut-on établir
# pour le titre sur cette période, compte tenu de la qualité des données disponibles ?
#
# **Ce que ce notebook ne fait pas.** Il ne reconstruit aucune observation manquante, n'ajuste aucun cours sans preuve,
# ne calcule ni Sharpe ni rendement total sans hypothèse documentée, et ne formule aucune recommandation.
#
# **Statut des données.** Série *non validée* : source secondaire unique, calendrier officiel absent,
# fractionnement 2024 non confirmé dans les cours. Les conclusions sont donc limitées à ce que ces données permettent.

# %% [markdown]
# ## Configuration
# Tous les paramètres sont ici. Modifiez-les seulement en documentant le changement dans la note méthodologique.

# %%
import os, io, sys, json, zipfile, platform, warnings, datetime as dt
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import scipy
from scipy import stats
import statsmodels
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import adfuller, kpss

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*kpss.*")

# --- entrée
ENTREE = "BASE_SOLIBRA_SLBC_2023_2026.zip"       # ZIP des fichiers joints (CSV ou ZIP accepté)
SORTIE = "resultats"                              # dossier de sortie
# --- période d'étude (bornes incluses)
DEBUT, FIN = pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-15")
# --- événements (avis BRVM ; dates lues dans le dépôt, avis PDF non ouverts)
SPLIT_DATE = pd.Timestamp("2024-09-30")          # fractionnement 10 pour 1 annoncé (avis n°242)
SUSP_DEBUT, SUSP_FIN = pd.Timestamp("2024-04-02"), pd.Timestamp("2024-09-10")  # suspension (avis 054, levée avis 227)
SEGMENTS = {                                      # segments de continuité de prix (pas de calcul entre segments)
    "S1 pré-suspension": (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-03-31")),
    "S2 reprise pré-fractionnement": (pd.Timestamp("2024-09-11"), pd.Timestamp("2024-09-29")),
    "S3 post-fractionnement": (SPLIT_DATE, FIN),
}
# --- risque, statistiques
NIVEAUX_VAR = [0.95, 0.99]
MIN_QUEUE = 30                 # en dessous, la queue est jugée trop petite pour une estimation stable
FENETRES_VOL = [20, 60]        # fenêtres glissantes, en nombre de rendements admissibles (non annualisées)
LAGS_LJUNG = [5, 10]
LAGS_ARCH = 5
BLOC = 5                       # longueur de bloc du bootstrap par blocs mobiles (sensibilité : 10)
B_BOOT = 2000
GRAINE = 20261015
# --- rendement sans risque : aucun taux documenté dans les fichiers joints
TAUX_SANS_RISQUE = None        # le Sharpe n'est pas calculé tant que ce paramètre n'est pas renseigné
# --- affichage
dpi_png = 300
sns.set_theme(style="whitegrid", context="paper")
np.random.seed(GRAINE)
os.makedirs(os.path.join(SORTIE, "tables"), exist_ok=True)
os.makedirs(os.path.join(SORTIE, "figures"), exist_ok=True)
os.makedirs(os.path.join(SORTIE, "journal"), exist_ok=True)

# %% [markdown]
# ## A. Objectif et périmètre
# Le notebook suit l'ordre demandé : chargement, audit, préparation des séries, analyses descriptives,
# risque, diagnostics, comparaison à l'indice, robustesse, interprétations et export.
# Chaque cellule de calcul imprime son effectif. Les commentaires qui suivent chaque analyse ne reprennent que des résultats calculés.

# %% [markdown]
# ## B. Chargement des fichiers
# Le chargeur vérifie le type réel (signature binaire) avant d'ouvrir l'archive : un CSV renommé `.zip` est lu comme CSV,
# une archive corrompue ou tronquée est signalée explicitement (pas de `BadZipFile` non traité).

# %%
def type_reel(chemin):
    with open(chemin, "rb") as f:
        tete = f.read(8)
    if tete[:4] == b"PK\x03\x04":
        return "zip"
    if tete[:5] == b"%PDF-":
        return "pdf"
    if tete.lstrip()[:1] == b"<":
        return "html"
    return "texte"


def trouver_entree(nom):
    for racine in [".", "..", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."]:
        p = os.path.join(racine, nom)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{nom} introuvable (cherché dans le dossier courant et le dossier parent)")


def lire_membres(chemin):
    """Retourne {nom_de_base: octets} pour un ZIP vérifié, ou {nom: octets} pour un fichier texte."""
    t = type_reel(chemin)
    if t == "texte":
        return {os.path.basename(chemin): open(chemin, "rb").read()}
    if t != "zip":
        raise ValueError(f"{chemin} : type réel « {t} » ; attendu CSV ou ZIP")
    try:
        z = zipfile.ZipFile(chemin)
    except zipfile.BadZipFile as e:
        raise ValueError(f"{chemin} : signature ZIP présente mais archive illisible ({e})")
    if z.testzip() is not None:
        raise ValueError(f"{chemin} : membre corrompu dans l'archive")
    return {os.path.basename(n): z.read(n) for n in z.namelist() if not n.endswith("/")}


# Google Colab : si le ZIP n'est pas présent, il est demandé à l'utilisateur (téléversement).
if "google.colab" in sys.modules or os.path.exists("/content"):
    if not any(os.path.exists(p) for p in [ENTREE, os.path.join("..", ENTREE)]):
        from google.colab import files as _colab_files
        print("Téléversez BASE_SOLIBRA_SLBC_2023_2026.zip (ou le CSV ANALYSE) :")
        _televerse = _colab_files.upload()
        ENTREE = next(iter(_televerse))

membres = lire_membres(trouver_entree(ENTREE))
print("Fichiers reconnus :", sorted(membres))

def csv_depuis(nom, **kw):
    if nom not in membres:
        raise FileNotFoundError(f"{nom} absent de l'entrée ; présents : {sorted(membres)}")
    return pd.read_csv(io.BytesIO(membres[nom]), **kw)

analyse = csv_depuis("SOLIBRA_SLBC_2023_2026_ANALYSE.csv", dtype=str, keep_default_na=False)
brut = csv_depuis("SOLIBRA_SLBC_2023_2026_BRUT.csv", dtype=str, keep_default_na=False)
journal_src = csv_depuis("JOURNAL_CORRECTIONS_EXCLUSIONS.csv", dtype=str, keep_default_na=False)
calendrier = csv_depuis("CALENDRIER_COUVERTURE_2023_2026.csv", dtype=str, keep_default_na=False)
dividendes = csv_depuis("SOLIBRA_DIVIDENDES_2023_2026.csv", dtype=str, keep_default_na=False)
evenements = csv_depuis("EVENEMENTS_SOLIBRA_2023_2026.csv", dtype=str, keep_default_na=False)
meta = json.loads(membres["METADONNEES_SERIE.json"].decode("utf-8"))
indice_brut = csv_depuis("Indice_BRVMC.csv", sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
rapport_indice = json.loads(membres["indices_report.json"].decode("utf-8")) if "indices_report.json" in membres else None

assert list(analyse.columns) == ["Date", "Close", "Volume"], f"colonnes inattendues : {list(analyse.columns)}"
print(f"ANALYSE : {len(analyse)} lignes ; BRUT : {len(brut)} ; journal : {len(journal_src)} ; indice : {len(indice_brut)} lignes")
print("Calendrier : colonnes", list(calendrier.columns))
print("Statut du calendrier :", "officiel" if "statut_seance_officiel" in calendrier.columns else "NON officiel (aucune colonne de séance établie)")

# %% [markdown]
# ## C. Audit de qualité et couverture
#
# **Points vérifiés :** format des dates et nombres, doublons, valeurs manquantes, cours strictement positifs, volumes entiers
# non négatifs, week-ends, et statut des volumes nuls dans la source. La couverture n'est calculée que si son dénominateur est établi :
# or le calendrier officiel n'est pas établi, donc le taux de couverture des séances n'est **pas** calculable. Seule la part de jours
# civils ouvrés (lundi à vendredi, fériés non connus) portant une observation est donnée, en la nommant comme telle.

# %%
obs = analyse.copy()
obs["Date"] = pd.to_datetime(obs.Date, format="%Y-%m-%d", errors="coerce")
obs["Close"] = pd.to_numeric(obs.Close, errors="coerce")
obs["Volume"] = pd.to_numeric(obs.Volume, errors="coerce")
obs = obs.sort_values("Date").reset_index(drop=True)

# volume FCFA publié, lu dans BRUT (montant publié, non recalculé)
brut_idx = brut.copy()
brut_idx["Date"] = pd.to_datetime(brut_idx.Date, format="%Y-%m-%d", errors="coerce")
brut_idx["Volume_FCFA"] = pd.to_numeric(brut_idx.Volume_FCFA, errors="coerce")
obs = obs.merge(brut_idx[["Date", "Volume_FCFA", "statut_analyse"]], on="Date", how="left")

audit = {
    "lignes_ANALYSE": len(obs),
    "date_min": obs.Date.min().date().isoformat(),
    "date_max": obs.Date.max().date().isoformat(),
    "dates_non_parsees": int(obs.Date.isna().sum()),
    "doublons_de_date": int(obs.Date.duplicated().sum()),
    "close_manquants": int(obs.Close.isna().sum()),
    "volume_manquants": int(obs.Volume.isna().sum()),
    "close_non_positifs": int((obs.Close <= 0).sum()),
    "volume_negatifs": int((obs.Volume < 0).sum()),
    "volume_non_entiers": int((obs.Volume % 1 != 0).sum()),
    "week_ends": int((obs.Date.dt.weekday >= 5).sum()),
    "volumes_nuls": int((obs.Volume == 0).sum()),
    "volumes_nuls_avec_volume_FCFA_nul": int(((obs.Volume == 0) & (obs.Volume_FCFA == 0)).sum()),
    "calendrier_officiel_etabli": "statut_seance_officiel" in calendrier.columns,
    "jours_ouvres_civils_fenetre": int(np.busday_count(DEBUT.date(), (FIN + pd.Timedelta(days=1)).date())),
    "jours_ouvres_civils_avec_observation": int(obs.Date.dt.weekday.lt(5).sum()),
}
audit["part_jours_ouvres_civils_avec_observation"] = round(audit["jours_ouvres_civils_avec_observation"] / audit["jours_ouvres_civils_fenetre"], 4)
audit["note_couverture"] = "dénominateur = jours ouvrés civils, fériés non connus : ce n'est pas un taux de couverture des séances"
for k, v in audit.items():
    print(f"{k:50s} {v}")

par_annee = obs.groupby(obs.Date.dt.year).size().rename("observations")
par_trim = obs.groupby(obs.Date.dt.to_period("Q")).size().rename("observations")
print("\nObservations par année :", par_annee.to_dict())
print("Observations par trimestre :"); print(par_trim.to_string())
pd.DataFrame({"annee": par_annee.index, "observations": par_annee.values}).to_csv(os.path.join(SORTIE, "tables", "effectifs_annuels.csv"), index=False)
par_trim.to_frame().reset_index().rename(columns={"Date": "trimestre"}).assign(trimestre=lambda d: d.trimestre.astype(str)).to_csv(
    os.path.join(SORTIE, "tables", "effectifs_trimestriels.csv"), index=False)
pd.DataFrame([audit]).T.reset_index().rename(columns={"index": "controle", 0: "valeur"}).to_csv(os.path.join(SORTIE, "tables", "audit_qualite.csv"), index=False)

# %% [markdown]
# ### C.2 Séances manquantes, suspensions et exclusions
# Chaque exclusion figure avec sa date, ses valeurs, sa raison et sa référence. Les jours ouvrés sans observation ne sont pas
# comblés : ils sont listés comme *absence non expliquée* (férié ou séance sans cotation, les deux non établis).

# %%
exclus = brut_idx[brut_idx.statut_analyse.str.startswith("EXCLUE")].copy()
exclus_tab = pd.DataFrame({
    "date": exclus.Date.dt.date.astype(str),
    "close": exclus.Close,
    "volume": exclus.Volume,
    "volume_FCFA": exclus.Volume_FCFA,
    "raison": exclus.statut_analyse.str.replace("EXCLUE : ", "", regex=False),
    "reference": "BRUT/SOLIBRA_SLBC_2023_2026_BRUT.csv ligne " + exclus.ligne_source.astype(str),
})
retires = journal_src[journal_src.operation == "exclusion (amont)"].copy()
retires_tab = pd.DataFrame({"date": retires.Date, "close": "", "volume": "", "volume_FCFA": "",
                            "raison": retires.justification, "reference": retires.reference})
exclusions = pd.concat([exclus_tab, retires_tab], ignore_index=True).sort_values("date").reset_index(drop=True)
exclusions.to_csv(os.path.join(SORTIE, "tables", "exclusions_detaillees.csv"), index=False)
print(f"Exclusions détaillées : {len(exclus_tab)} observations de la fenêtre + {len(retires_tab)} retraits amont par le dépôt")
display(exclus_tab) if "display" in globals() else print(exclus_tab.to_string(index=False))

# jours ouvrés civils sans observation
jours_ouvres = pd.bdate_range(DEBUT, FIN)
absents = sorted(set(jours_ouvres) - set(obs.Date))
absents_tab = pd.DataFrame({"date": [d.date().isoformat() for d in absents],
                            "statut": "absence de ligne dans la source ; férié ou absence de cotation non établi"})
absents_tab.to_csv(os.path.join(SORTIE, "tables", "jours_ouvres_sans_observation.csv"), index=False)
print(f"Jours ouvrés civils sans observation retenue : {len(absents)} (dont zones de suspension : "
      f"{sum(SUSP_DEBUT <= d <= SUSP_FIN for d in absents)})")

# %% [markdown]
# ## D. Événements et préparation des séries
#
# ### D.1 Événements documentés
# Suspension et levée, fractionnement, dividendes : tous tirés du dépôt. Les avis PDF cités n'ont pas été ouverts ; ces dates
# sont donc *rapportées* et non vérifiées sur leur source primaire.

# %%
ev = evenements.copy()
ev = ev[ev.categorie.isin(["trading_suspension", "trading_resumed", "theoretical_value_notice", "dividend_ex_date", "dividend_payment"])]
print(ev[["date_evenement", "categorie", "titre"]].to_string(index=False))
print("\nFractionnement : métadonnées =", meta.get("date_effet_fractionnement"), "| source :", meta.get("date_effet_source"))
print("Cours publiés ajustés du fractionnement :", meta.get("close_ajuste_fractionnement"))

# %% [markdown]
# ### D.2 Statut de la base des cours
# Le fichier source ne mentionne pas de base d'ajustement. Le fractionnement 10 pour 1 n'apparaît pas dans les cours (9 500 FCFA
# le 26/09/2024, 10 975 FCFA le 30/09/2024). **La base est donc indéterminée** : aucun ajustement n'est appliqué, et tout calcul
# qui traverse le fractionnement est **bloqué**. Les cours de référence BRVM du dépôt concordent avec la série brute, ce qui
# ne tranche pas la question.

# %%
def bloque_par_split(p, c):
    return (p < SPLIT_DATE) and (c >= SPLIT_DATE)

def bloque_par_suspension(p, c):
    return (p <= SUSP_FIN) and (c >= SUSP_DEBUT)

def jours_ouvres_entre(p, c):
    """Nombre de jours ouvrés civils (lundi-vendredi, fériés non connus) strictement entre p et c."""
    return int(np.busday_count((p + pd.Timedelta(days=1)).date(), c.date()))

paires = []
for i in range(1, len(obs)):
    p, c = obs.loc[i - 1], obs.loc[i]
    gap = jours_ouvres_entre(p.Date, c.Date)
    if bloque_par_split(p.Date, c.Date):
        classe = "bloqué : traverse le fractionnement (base indéterminée)"
    elif bloque_par_suspension(p.Date, c.Date):
        classe = "bloqué : traverse la suspension"
    elif gap == 0:
        classe = "ouvrés consécutifs (continuité non démontrée)"
    else:
        classe = "jours ouvrés absents entre observations"
    paires.append({
        "date_prec": p.Date, "date": c.Date, "close_prec": p.Close, "close": c.Close,
        "volume_prec": p.Volume, "volume": c.Volume,
        "jours_ouvres_absents": gap, "classe": classe,
        "volume_nul_implique": (p.Volume == 0) or (c.Volume == 0),
    })
paires = pd.DataFrame(paires)
paires["r_simple"] = paires.close / paires.close_prec - 1
paires["r_log"] = np.log(paires.close / paires.close_prec)
paires["segment"] = np.select(
    [paires.date.between(*SEGMENTS["S1 pré-suspension"]), paires.date.between(*SEGMENTS["S2 reprise pré-fractionnement"]),
     paires.date.between(*SEGMENTS["S3 post-fractionnement"])],
    list(SEGMENTS.keys()), default="hors segment")

print(paires.classe.value_counts().to_string())
print("\nRendements bloqués :", int(paires.classe.str.startswith("bloqué").sum()))
paires.to_csv(os.path.join(SORTIE, "tables", "paires_successives_toutes.csv"), index=False)

# sous-ensembles retenus pour chaque analyse
R_Q = paires[paires.classe.str.startswith("ouvrés consécutifs")].copy()     # rendements quotidiens admissibles (continuité non démontrée)
R_GAP = paires[paires.classe.str.startswith("jours ouvrés absents")].copy() # franchissent des jours ouvrés absents
R_TOUS = paires[~paires.classe.str.startswith("bloqué")].copy()              # tous les rendements non bloqués
R_Q_SANS_VOL0 = R_Q[~R_Q.volume_nul_implique].copy()                         # sans séance à volume nul
R_Q_SANS_VOL0_SEG = R_Q_SANS_VOL0
print(f"\nEffectifs : quotidiens admissibles {len(R_Q)} | avec lacunes {len(R_GAP)} | tous non bloqués {len(R_TOUS)} | "
      f"quotidiens sans séance à volume nul {len(R_Q_SANS_VOL0)}")
print("Continuité quotidienne démontrée : NON (aucun calendrier officiel)")

# %% [markdown]
# ### D.3 Séries conservées séparément
# *Données sources* : `obs` (Close publié, Volume publié). *Données ajustées* : aucune (pas de preuve de la base).
# *Données retenues par analyse* : `R_Q` pour les rendements quotidiens admissibles, `R_TOUS` ou `R_GAP` pour les tests de robustesse.

# %%
obs.to_csv(os.path.join(SORTIE, "tables", "serie_source_retenue.csv"), index=False)
print("Série source conservée :", len(obs), "observations ; série ajustée : aucune")

# %% [markdown]
# ## E. Cours, performance et rendements
#
# ### E.1 Évolution des cours par segment
# La courbe est tracée segment par segment : une lacune ou une suspension n'est pas reliée visuellement.

# %%
fig, ax = plt.subplots(figsize=(10, 4.5))
couleurs = {"S1 pré-suspension": "#1f4e79", "S2 reprise pré-fractionnement": "#7f7f7f", "S3 post-fractionnement": "#c55a11"}
for nom, (a, b) in SEGMENTS.items():
    s = obs[(obs.Date >= a) & (obs.Date <= b)]
    ax.plot(s.Date, s.Close, marker=".", ms=2.5, lw=0.8, color=couleurs[nom], label=f"{nom} (n={len(s)})")
ax.axvspan(SUSP_DEBUT, SUSP_FIN, color="#dddddd", alpha=0.6, label="suspension (avis 054 - avis 227)")
ax.axvline(SPLIT_DATE, color="black", ls="--", lw=0.8, label="fractionnement annoncé 30/09/2024 (cours non ajustés)")
ax.set_title("SOLIBRA (SLBC) : cours de clôture publiés, par segment de continuité")
ax.set_ylabel("Clôture (FCFA par action, non ajusté)")
ax.set_xlabel("Date")
ax.legend(fontsize=7, loc="upper left")
fig.text(0.01, -0.02, "Note : pas de liaison entre segments ; la série n'est ni ajustée ni validée. Source : dépôt harzat/brvm-data-public.", fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "01_cours_par_segment.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "01_cours_par_segment.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)

# %% [markdown]
# ### E.2 Couverture et périodes absentes

# %%
statut_jour = pd.Series("absence non expliquée", index=pd.bdate_range(DEBUT, FIN))
statut_jour[statut_jour.index.isin(obs.Date)] = "observation retenue"
statut_jour[(statut_jour.index >= SUSP_DEBUT) & (statut_jour.index <= SUSP_FIN)] = "suspension"
statut_jour[statut_jour.index.isin(exclus.Date)] = "observation exclue"
statut_jour[statut_jour.index.isin(pd.to_datetime(retires.Date))] = "retiré en amont par le dépôt"
ordre = {"observation retenue": 0, "observation exclue": 1, "suspension": 2, "retiré en amont par le dépôt": 3, "absence non expliquée": 4}
couv = statut_jour.to_frame("statut")
couv["niveau"] = couv.statut.map(ordre)
couv["annee"] = couv.index.year
couv["jour_annee"] = couv.index.dayofyear
fig, ax = plt.subplots(figsize=(10, 3.2))
palette = {"observation retenue": "#1f4e79", "observation exclue": "#c00000", "suspension": "#7f7f7f",
           "retiré en amont par le dépôt": "#70ad47", "absence non expliquée": "#f4b183"}
for st, col in palette.items():
    s = couv[couv.statut == st]
    ax.scatter(s.index, np.zeros(len(s)), s=4, color=col, label=f"{st} ({len(s)})")
ax.set_yticks([])
ax.set_title("Jours ouvrés civils 2023-2026 : observations, exclusions, suspension, absences")
ax.legend(ncol=4, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12))
fig.text(0.01, -0.2, "Note : 'absence non expliquée' = jour ouvré civil sans ligne ; férié ou absence de cotation non établis.", fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "02_couverture.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "02_couverture.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)
couv_resume = couv.statut.value_counts().rename("jours_ouvres_civils").to_frame()
couv_resume.to_csv(os.path.join(SORTIE, "tables", "couverture_resume.csv"))
print(couv_resume)

# %% [markdown]
# ### E.3 Performance des cours
# Performance = dernier cours / premier cours observés dans le segment − 1 (**cours seulement, hors dividendes**).
# Aucune performance n'est calculée à travers le fractionnement ou la suspension. Le 2026 est partiel (jusqu'au 14/10/2026).

# %%
def perf_segment(nom, a, b):
    s = obs[(obs.Date >= a) & (obs.Date <= b)]
    if len(s) < 2:
        return {"segment": nom, "debut": None, "fin": None, "n": len(s), "performance_cours": np.nan}
    return {"segment": nom, "debut": s.Date.iloc[0].date().isoformat(), "fin": s.Date.iloc[-1].date().isoformat(),
            "n": len(s), "close_debut": s.Close.iloc[0], "close_fin": s.Close.iloc[-1],
            "performance_cours": s.Close.iloc[-1] / s.Close.iloc[0] - 1}

perf_seg = pd.DataFrame([perf_segment(n, a, b) for n, (a, b) in SEGMENTS.items()])
perf_an = pd.DataFrame([
    perf_segment("2023 (année complète présente)", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
    perf_segment("2024 partie S1 (jan-mars)", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-31")),
    perf_segment("2024 partie S3 (sept-déc)", pd.Timestamp("2024-09-30"), pd.Timestamp("2024-12-31")),
    perf_segment("2025 (complète)", pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")),
    perf_segment("2026 PARTIELLE (jusqu'au 14/10)", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31")),
])
perf_seg.to_csv(os.path.join(SORTIE, "tables", "performance_segments.csv"), index=False)
perf_an.to_csv(os.path.join(SORTIE, "tables", "performance_par_annee.csv"), index=False)
print(perf_seg.to_string(index=False)); print()
print(perf_an.to_string(index=False))
print("\nPerformance sur toute la période : NON CALCULÉE (traverse le fractionnement, base indéterminée).")

# %% [markdown]
# ### E.4 Drawdown et récupération
# Maximum drawdown par segment : sommet = maximum antérieur, creux = minimum du drawdown. Durée de récupération observée seulement
# si le cours regagne son sommet à l'intérieur du segment ; sinon elle est notée *non observée*.

# %%
def drawdown_segment(nom, a, b):
    s = obs[(obs.Date >= a) & (obs.Date <= b)].reset_index(drop=True)
    if len(s) < 2:
        return None, None
    pic = s.Close.cummax()
    dd = s.Close / pic - 1
    i_creux = int(dd.idxmin())
    i_sommet = int(s.Close.iloc[: i_creux + 1].idxmax())
    apres = s.iloc[i_creux:]
    rec = apres[apres.Close >= s.Close.iloc[i_sommet]]
    if len(rec):
        j = rec.index[0]
        recup = {"date_recuperation": s.Date.iloc[j].date().isoformat(),
                 "jours_ouvres_recuperation_observe": int(np.busday_count(s.Date.iloc[i_creux].date(), s.Date.iloc[j].date())),
                 "n_observations_recuperation": int(j - i_creux)}
    else:
        recup = {"date_recuperation": "non observée dans le segment", "jours_ouvres_recuperation_observe": np.nan,
                 "n_observations_recuperation": np.nan}
    return {"segment": nom, "max_drawdown": dd.iloc[i_creux], "date_sommet": s.Date.iloc[i_sommet].date().isoformat(),
            "cours_sommet": s.Close.iloc[i_sommet], "date_creux": s.Date.iloc[i_creux].date().isoformat(),
            "cours_creux": s.Close.iloc[i_creux], **recup}, pd.DataFrame({"Date": s.Date, "dd": dd.values})

dd_rows, dd_series = [], {}
for nom, (a, b) in SEGMENTS.items():
    r, dser = drawdown_segment(nom, a, b)
    if r:
        dd_rows.append(r); dd_series[nom] = dser
dd_tab = pd.DataFrame(dd_rows)
dd_tab.to_csv(os.path.join(SORTIE, "tables", "drawdown_par_segment.csv"), index=False)
print(dd_tab.to_string(index=False))

fig, axes = plt.subplots(len(dd_series), 1, figsize=(10, 2.6 * len(dd_series)), sharex=False)
for ax, (nom, dser) in zip(np.atleast_1d(axes), dd_series.items()):
    ax.fill_between(dser.Date, dser.dd.values, 0, color="#a50f15", alpha=0.5)
    ax.set_title(f"Drawdown : {nom}"); ax.set_ylabel("Drawdown")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
fig.suptitle("Drawdown des cours publiés, par segment (non ajusté)", y=1.0)
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "03_drawdown.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "03_drawdown.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)

# %% [markdown]
# ### E.5 Statistiques des rendements
# Conventions : rendements *simples* `r = C_t / C_{t-1} - 1` et *logarithmiques* `r = ln(C_t / C_{t-1})`.
# Asymétrie : Fisher-Pearson ajusté (`bias=False`). Kurtosis : excès (Fisher, `bias=False`), donc 0 pour la loi normale.
# Ces statistiques portent sur **R_Q** (rendements « ouvrés consécutifs », continuité non démontrée) ; les rendements franchissant des lacunes sont séparés.

# %%
def stats_rendements(x):
    x = pd.Series(x).dropna()
    n = len(x)
    if n < 3:
        return {"n": n}
    q = x.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return {"n": n, "moyenne": x.mean(), "mediane": x.median(), "ecart_type": x.std(ddof=1),
            "minimum": x.min(), "maximum": x.max(),
            "q01": q.loc[0.01], "q05": q.loc[0.05], "q25": q.loc[0.25], "q75": q.loc[0.75], "q95": q.loc[0.95], "q99": q.loc[0.99],
            "asymetrie_ajustee": stats.skew(x, bias=False), "kurtosis_exces_ajustee": stats.kurtosis(x, fisher=True, bias=False),
            "proportion_nuls": float((x == 0).mean()), "n_nuls": int((x == 0).sum())}

stat_tab = pd.DataFrame({
    "R_Q simple": stats_rendements(R_Q.r_simple),
    "R_Q log": stats_rendements(R_Q.r_log),
    "R_GAP simple (lacunes, séparé)": stats_rendements(R_GAP.r_simple),
}).T
stat_tab.to_csv(os.path.join(SORTIE, "tables", "statistiques_rendements.csv"))
pd.set_option("display.float_format", lambda v: f"{v:,.5f}")
print(stat_tab.to_string())
pd.set_option("display.float_format", None)

# %% [markdown]
# ## F. Volatilité, drawdown et risque historique
#
# ### F.1 Volatilité à la fréquence observée
# L'écart-type est donné *par rendement observé*. **Aucune annualisation** : la règle de racine du temps, `σ_an = σ × √N`,
# exige un nombre de séances par an `N` documenté, que le calendrier officiel ne fournit pas. Ce choix est présenté comme une limite.

# %%
vol_obs = {
    "écart-type quotidien admissible (log)": R_Q.r_log.std(ddof=1),
    "écart-type quotidien admissible (simple)": R_Q.r_simple.std(ddof=1),
    "effectif": len(R_Q),
    "annualisation": "non effectuée : pas de calendrier officiel ni de nombre de séances documenté",
}
vol_seg = pd.DataFrame([{"segment": n, "n": int(((R_Q.segment == n)).sum()),
                         "ecart_type_log": R_Q.loc[R_Q.segment == n, "r_log"].std(ddof=1)} for n in SEGMENTS])
vol_seg.to_csv(os.path.join(SORTIE, "tables", "volatilite_par_segment.csv"), index=False)
print({k: (round(v, 6) if isinstance(v, float) else v) for k, v in vol_obs.items()})
print(vol_seg.to_string(index=False))

# %% [markdown]
# ### F.2 Volatilité glissante
# Fenêtres de 20 et 60 **rendements admissibles** (≈ 1 mois et 3 mois de séances *si* la série était quotidienne complète, ce qui n'est pas démontré).
# Le calcul est fait **à l'intérieur de chaque segment** pour ne pas mélanger des rendements séparés par une suspension ou le fractionnement.

# %%
roul = []
for nom in SEGMENTS:
    s = R_Q[R_Q.segment == nom].sort_values("date").copy()
    for w in FENETRES_VOL:
        s[f"vol_glissante_{w}"] = s.r_log.rolling(w, min_periods=w).std(ddof=1)
    roul.append(s)
roul = pd.concat(roul)
roul.to_csv(os.path.join(SORTIE, "tables", "volatilite_glissante.csv"), index=False)

fig, ax = plt.subplots(figsize=(10, 4))
for nom, col in couleurs.items():
    s = roul[roul.segment == nom]
    for w, ls in zip(FENETRES_VOL, ["-", "--"]):
        ax.plot(s.date, s[f"vol_glissante_{w}"], ls=ls, color=col, lw=1.1, label=f"{nom}, fenêtre {w}")
ax.set_title("Volatilité glissante des rendements log admissibles (non annualisée)")
ax.set_ylabel("Écart-type par rendement observé"); ax.set_xlabel("Date")
ax.legend(fontsize=6, ncol=2)
fig.text(0.01, -0.02, "Note : les segments ne sont pas reliés ; fenêtres en nombre de rendements admissibles, non en jours calendaires.", fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "04_volatilite_glissante.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "04_volatilite_glissante.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)

# %% [markdown]
# ### F.3 VaR et Expected Shortfall historiques
# Convention : **pertes positives**, `L = −r` (rendement simple). VaR au niveau `α` = quantile empirique de `L` de méthode
# `inverted_cdf` (plus petite valeur dont la fonction de répartition atteint `α`, donc traitement déterministe des égalités).
# ES = moyenne des `L` supérieures ou égales à la VaR. Le nombre d'observations dans la queue (`L ≥ VaR`) est donné.
# Intervalles de confiance : bootstrap **par blocs mobiles** de longueur `BLOC` (dépendance temporelle), `B_BOOT` répliques.
# La VaR porte sur **un** rendement admissible ; elle n'est pas étendue à plusieurs jours.

# %%
def var_es(x, niveau, bloc=BLOC, B=B_BOOT, graine=GRAINE):
    L = -np.asarray(x, dtype=float)
    n = len(L)
    if n < 2:
        return {"niveau": niveau, "n": n}
    v = np.quantile(L, niveau, method="inverted_cdf")
    queue = L[L >= v]
    es = queue.mean()
    rng = np.random.default_rng(graine)
    nb = int(np.ceil(n / bloc))
    starts_max = n - bloc
    vs, ess = [], []
    for _ in range(B):
        idx = np.concatenate([np.arange(s, s + bloc) for s in rng.integers(0, starts_max + 1, nb)])[:n]
        Lb = L[idx]
        vb = np.quantile(Lb, niveau, method="inverted_cdf")
        vs.append(vb)
        ess.append(Lb[Lb >= vb].mean())
    return {"niveau": niveau, "n": n, "obs_dans_queue": int(len(queue)),
            "VaR": v, "VaR_IC95_bas": np.quantile(vs, 0.025), "VaR_IC95_haut": np.quantile(vs, 0.975),
            "ES": es, "ES_IC95_bas": np.quantile(ess, 0.025), "ES_IC95_haut": np.quantile(ess, 0.975),
            "avertissement": "queue < MIN_QUEUE : estimation instable" if len(queue) < MIN_QUEUE else ""}

ve_rows = []
for nom, x in [("R_Q toutes périodes", R_Q.r_simple), ("R_Q S1", R_Q[R_Q.segment == "S1 pré-suspension"].r_simple),
               ("R_Q S3", R_Q[R_Q.segment == "S3 post-fractionnement"].r_simple)]:
    for niv in NIVEAUX_VAR:
        ve_rows.append({"ensemble": nom, **var_es(x, niv)})
ve_tab = pd.DataFrame(ve_rows)
ve_tab.to_csv(os.path.join(SORTIE, "tables", "var_es_historiques.csv"), index=False)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print(ve_tab.to_string(index=False))
pd.set_option("display.float_format", None)

# %% [markdown]
# ### F.4 Volumes publiés
# Les volumes sont des **titres échangés publiés**. Ils ne sont comparés qu'**à l'intérieur d'un même régime d'unités** :
# avant le fractionnement (S1 et S2) et après (S3). Le montant publié `Volume FCFA` est décrit séparément ;
# `Close × Volume` n'est pas utilisé comme montant échangé.
# Les volumes nuls sont tous documentés par `Volume FCFA = 0` dans la source.
# La moyenne seule ne permet pas de conclure à la liquidité.

# %%
obs["regime_unites"] = np.where(obs.Date < SPLIT_DATE, "avant fractionnement", "après fractionnement")
vol_reg = obs.groupby("regime_unites").agg(
    n=("Volume", "size"), mediane=("Volume", "median"), moyenne=("Volume", "mean"),
    q10=("Volume", lambda s: s.quantile(0.10)), q90=("Volume", lambda s: s.quantile(0.90)),
    nuls=("Volume", lambda s: int((s == 0).sum())), montant_publie_mediane=("Volume_FCFA", "median"))
vol_reg.to_csv(os.path.join(SORTIE, "tables", "volumes_par_regime.csv"))
print(vol_reg.to_string())

# valeurs atypiques (règle de Tukey sur log(1+volume), dans chaque régime, sans suppression)
out = []
for reg, s in obs.groupby("regime_unites"):
    lv = np.log1p(s.Volume)
    q1, q3 = lv.quantile(0.25), lv.quantile(0.75)
    iqr = q3 - q1
    m = (lv < q1 - 1.5 * iqr) | (lv > q3 + 1.5 * iqr)
    out.append(s[m].assign(regime=reg))
vol_out = pd.concat(out)[["Date", "Close", "Volume", "Volume_FCFA", "regime_unites"]]
vol_out.to_csv(os.path.join(SORTIE, "tables", "volumes_atypiques_tukey.csv"), index=False)
print(f"\nValeurs atypiques de volume (Tukey dans chaque régime, conservées) : {len(vol_out)}")

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [2.2, 1]})
for reg, col in [("avant fractionnement", "#1f4e79"), ("après fractionnement", "#c55a11")]:
    s = obs[obs.regime_unites == reg]
    axes[0].scatter(s.Date, s.Volume, s=6, color=col, label=f"{reg} (n={len(s)})")
    axes[1].hist(np.log1p(s.Volume), bins=30, alpha=0.6, color=col, label=reg)
axes[0].set_yscale("symlog", linthresh=1); axes[0].set_title("Volumes publiés (titres) ; axe symlog")
axes[0].set_ylabel("Titres échangés"); axes[0].legend(fontsize=7)
axes[1].set_title("log(1 + volume), par régime"); axes[1].set_xlabel("log(1 + titres)"); axes[1].legend(fontsize=7)
fig.text(0.01, -0.03, "Note : régimes séparés par le fractionnement ; pas de comparaison directe entre régimes.", fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "05_volumes.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "05_volumes.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)

# %% [markdown]
# ## G. Diagnostics statistiques et robustesse
#
# ### G.1 Distribution : histogramme, fonction de répartition, Q-Q
# Tests de normalité : **Jarque-Bera** (asymétrie et kurtosis, approximation asymptotique) et **Shapiro-Wilk** (plus puissant
# en petit échantillon, valide jusqu'à 5 000 observations). Un rejet ne prouve pas la prévisibilité : il indique seulement que la loi normale
# ne décrit pas bien la distribution des rendements observés.

# %%
x = R_Q.r_log.values
fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
axes[0].hist(x, bins=40, color="#1f4e79", alpha=0.8, density=True)
mu, sd = x.mean(), x.std(ddof=1)
grille = np.linspace(x.min(), x.max(), 200)
axes[0].plot(grille, stats.norm.pdf(grille, mu, sd), color="#c55a11", lw=1.2, label="normale ajustée")
axes[0].set_title("Histogramme des rendements log (R_Q)"); axes[0].set_xlabel("rendement log"); axes[0].legend(fontsize=7)
xs = np.sort(x); fdr = np.arange(1, len(xs) + 1) / len(xs)
axes[1].step(xs, fdr, where="post", color="#1f4e79"); axes[1].plot(grille, stats.norm.cdf(grille, mu, sd), color="#c55a11", lw=1)
axes[1].set_title("Fonction de répartition empirique vs normale"); axes[1].set_xlabel("rendement log")
stats.probplot(x, dist="norm", plot=axes[2])
axes[2].set_title("Graphique Q-Q contre la loi normale")
fig.tight_layout()
fig.savefig(os.path.join(SORTIE, "figures", "06_distribution_qq.png"), dpi=dpi_png, bbox_inches="tight")
fig.savefig(os.path.join(SORTIE, "figures", "06_distribution_qq.pdf"), bbox_inches="tight")
plt.show(); plt.close(fig)

# %% [markdown]
# ### G.2 Autocorrélation, Ljung-Box, effet ARCH et stationnarité
# - **Ljung-Box** sur les rendements et sur leurs carrés (`lags` = `LAGS_LJUNG`) : teste l'absence conjointe d'autocorrélation jusqu'au retard `k`.
# - **Test ARCH-LM** (`LAGS_ARCH` retards) : teste l'absence d'effet ARCH, c'est-à-dire d'hétéroscédasticité conditionnelle.
# - **ADF** (régression avec constante, retards choisis par AIC) et **KPSS** (constante, retards automatiques) sur les **niveaux de log-cours**
#   et sur les rendements. Les deux tests ont des hypothèses opposées : ADF nulle = racine unitaire ; KPSS nulle = stationnarité.
# - Les tests sont faits **par segment** (S1, S3) pour ne pas mélanger des séries séparées par une suspension ou le fractionnement.
# - Les tests multiples augmentent le risque de résultats fortuits : chaque famille est présentée sans sélection a posteriori.

# %%
def tests_serie(nom, rend, prix):
    rend = np.asarray(rend, dtype=float)
    out = {"serie": nom, "n_rendements": len(rend)}
    if len(rend) < 30:
        out["note"] = "effectif < 30 : tests non interprétables"
        return out
    lb = acorr_ljungbox(rend, lags=LAGS_LJUNG, return_df=True)
    lb2 = acorr_ljungbox(rend ** 2, lags=LAGS_LJUNG, return_df=True)
    for k in LAGS_LJUNG:
        out[f"LjungBox_rend_p_lag{k}"] = float(lb.loc[k, "lb_pvalue"])
        out[f"LjungBox_carres_p_lag{k}"] = float(lb2.loc[k, "lb_pvalue"])
    arch = het_arch(rend - rend.mean(), nlags=LAGS_ARCH)
    out["ARCH_LM_stat"], out["ARCH_LM_p"] = float(arch[0]), float(arch[1])
    jb = stats.jarque_bera(rend)
    out["JarqueBera_stat"], out["JarqueBera_p"] = float(jb.statistic), float(jb.pvalue)
    if len(rend) <= 5000:
        sw = stats.shapiro(rend)
        out["ShapiroWilk_stat"], out["ShapiroWilk_p"] = float(sw.statistic), float(sw.pvalue)
    adf_rend = adfuller(rend, regression="c", autolag="AIC")
    out["ADF_rend_p"] = float(adf_rend[1]); out["ADF_rend_retards"] = int(adf_rend[2])
    kp = kpss(rend, regression="c", nlags="auto")
    out["KPSS_rend_p"] = float(kp[1]); out["KPSS_rend_retards"] = int(kp[2])
    if prix is not None and len(prix) >= 30:
        lp = np.log(np.asarray(prix, dtype=float))
        adf_p = adfuller(lp, regression="c", autolag="AIC")
        out["ADF_log_cours_p"] = float(adf_p[1]); out["ADF_log_cours_retards"] = int(adf_p[2])
        kp_p = kpss(lp, regression="c", nlags="auto")
        out["KPSS_log_cours_p"] = float(kp_p[1])
    return out

tests = []
for nom in ["S1 pré-suspension", "S3 post-fractionnement"]:
    s_r = R_Q[R_Q.segment == nom].sort_values("date")
    # niveaux de prix du même segment, sans les lacunes internes au segment
    s_p = obs[(obs.Date >= SEGMENTS[nom][0]) & (obs.Date <= SEGMENTS[nom][1])].Close
    tests.append(tests_serie(nom, s_r.r_log, s_p))
tests_tab = pd.DataFrame(tests)
tests_tab.to_csv(os.path.join(SORTIE, "tables", "tests_diagnostics.csv"), index=False)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print(tests_tab.T.to_string())
pd.set_option("display.float_format", None)

# %% [markdown]
# ### G.3 Intervalles de confiance avec dépendance temporelle
# Bootstrap par blocs mobiles (longueur `BLOC`, sensibilité à `2 × BLOC`) pour la moyenne et l'autocorrélation d'ordre 1 des rendements log,
# sur **S3**, segment le plus long. Ce bootstrap décrit l'incertitude d'échantillonnage sous dépendance modérée ; il **ne corrige** ni les
# données manquantes ni les erreurs de la source.

# %%
def ic_bloc(x, fonction, bloc, B=B_BOOT, graine=GRAINE):
    x = np.asarray(x, dtype=float)
    n = len(x)
    rng = np.random.default_rng(graine)
    nb = int(np.ceil(n / bloc))
    vals = []
    for _ in range(B):
        idx = np.concatenate([np.arange(s, s + bloc) for s in rng.integers(0, n - bloc + 1, nb)])[:n]
        vals.append(fonction(x[idx]))
    vals = np.array(vals)
    return fonction(x), np.quantile(vals, 0.025), np.quantile(vals, 0.975)

def acf1(y):
    y = y - y.mean()
    return float((y[1:] * y[:-1]).sum() / (y * y).sum())

x3 = R_Q[R_Q.segment == "S3 post-fractionnement"].sort_values("date").r_log.values
boot_rows = []
for bloc in [BLOC, 2 * BLOC]:
    m, lo, hi = ic_bloc(x3, np.mean, bloc)
    boot_rows.append({"statistique": "moyenne des rendements log (S3)", "bloc": bloc, "estimation": m, "IC95_bas": lo, "IC95_haut": hi, "n": len(x3)})
    a1, lo, hi = ic_bloc(x3, acf1, bloc)
    boot_rows.append({"statistique": "autocorrélation d'ordre 1 (S3)", "bloc": bloc, "estimation": a1, "IC95_bas": lo, "IC95_haut": hi, "n": len(x3)})
boot_tab = pd.DataFrame(boot_rows)
boot_tab.to_csv(os.path.join(SORTIE, "tables", "ic_bootstrap_blocs.csv"), index=False)
pd.set_option("display.float_format", lambda v: f"{v:,.5f}")
print(boot_tab.to_string(index=False))
pd.set_option("display.float_format", None)

# %% [markdown]
# ### G.4 Robustesse
# Comparaison des statistiques et des VaR selon les **échantillons** et **conventions** : rendements quotidiens admissibles,
# tous les rendements non bloqués (y compris ceux franchissant des jours absents), quotidiens sans séance à volume nul,
# et quotidiens sans les 1 % de rendements les plus extrêmes **pour mesurer leur influence seulement** (les résultats principaux les conservent).

# %%
def ligne_robustesse(nom, s):
    s = pd.Series(s).dropna()
    rec = {"echantillon": nom, "n": len(s), "moyenne": s.mean() if len(s) else np.nan,
           "ecart_type_log": np.log1p(s).std(ddof=1) if len(s) > 2 else np.nan}
    rec["ecart_type_simple"] = s.std(ddof=1) if len(s) > 2 else np.nan
    rec["asymetrie"] = stats.skew(s, bias=False) if len(s) > 2 else np.nan
    rec["kurtosis_exces"] = stats.kurtosis(s, fisher=True, bias=False) if len(s) > 3 else np.nan
    if len(s) >= 20:
        rec["VaR95"] = var_es(s, 0.95, B=500)["VaR"]
        rec["ES95"] = var_es(s, 0.95, B=500)["ES"]
    return rec

q_lo, q_hi = R_Q.r_simple.quantile([0.01, 0.99])
variantes = [
    ("quotidiens admissibles (principal)", R_Q.r_simple),
    ("tous non bloqués (avec lacunes)", R_TOUS.r_simple),
    ("lacunes seules", R_GAP.r_simple),
    ("quotidiens sans séance à volume nul", R_Q_SANS_VOL0.r_simple),
    ("quotidiens sans 1 % extrêmes (sensibilité)", R_Q.r_simple[(R_Q.r_simple >= q_lo) & (R_Q.r_simple <= q_hi)]),
    ("S1 seul", R_Q[R_Q.segment == "S1 pré-suspension"].r_simple),
    ("S3 seul", R_Q[R_Q.segment == "S3 post-fractionnement"].r_simple),
    ("2025 seul", R_Q[R_Q.date.dt.year == 2025].r_simple),
    ("2026 jusqu'au 14/10 (partiel)", R_Q[R_Q.date.dt.year == 2026].r_simple),
]
rob = pd.DataFrame([ligne_robustesse(n, s) for n, s in variantes])
rob.to_csv(os.path.join(SORTIE, "tables", "robustesse.csv"), index=False)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print(rob.to_string(index=False))
pd.set_option("display.float_format", None)

# %% [markdown]
# ### G.5 Lecture critique de la robustesse
# Les variantes ne sont pas choisies pour produire un résultat : elles documentent la sensibilité aux lacunes, aux séances à volume nul,
# aux extrêmes et à la sous-période. Un résultat qui ne tient que dans une variante ne doit pas être présenté comme général.

# %% [markdown]
# ## H. Comparaison au marché (BRVM Composite)
#
# ### H.1 Couverture et définition de l'indice
# Source : `Indice_BRVMC.csv`, dépôt `harzat/brvm-data-public` (indice BRVM Composite, rapport `indices_report.json` : source sikafinance,
# mis à jour le 15/10/2026). Les conditions de calcul de l'indice ne sont pas fournies dans les fichiers joints ; sa définition
# est donc prise telle que décrite par le fichier, sans vérification.

# %%
ind = indice_brut.copy()
ind["Date"] = pd.to_datetime(ind.Date, format="%d/%m/%Y", errors="coerce")
ind["Close"] = pd.to_numeric(ind["Clôture"].str.replace(",", ".", regex=False), errors="coerce")
ind = ind[(ind.Date >= DEBUT) & (ind.Date <= FIN)].sort_values("Date").reset_index(drop=True)
print("Indice sur la fenêtre :", len(ind), "lignes ;", ind.Date.min().date(), "→", ind.Date.max().date())
print("Doublons :", int(ind.Date.duplicated().sum()), "| clôtures manquantes :", int(ind.Close.isna().sum()))
copies_ind = int(((ind.Close == ind.Close.shift()) & (ind.Date.diff().dt.days <= 4)).sum())
print("Clôtures identiques à la séance précédente (indice) :", copies_ind,
      "— à noter : la clôture du 15/10/2026 répète celle du 14/10/2026")
ind["rv"] = ind.Close.pct_change()
ind_paires = []
for i in range(1, len(ind)):
    p, c = ind.loc[i - 1], ind.loc[i]
    ind_paires.append({"date_prec": p.Date, "date": c.Date, "r_indice_log": np.log(c.Close / p.Close),
                       "r_indice_simple": c.Close / p.Close - 1, "gap": jours_ouvres_entre(p.Date, c.Date)})
ind_paires = pd.DataFrame(ind_paires)

# %% [markdown]
# ### H.2 Rapprochement des séries sur des intervalles identiques
# Appariement : seuls les rendements pour lesquels **la même paire de dates consécutives** existe dans les deux séries, sans jour ouvré
# absent dans l'une ou l'autre, sont comparés. Les dates non appariées sont listées.

# %%
cles_solibra = set(zip(R_Q.date_prec, R_Q.date))
cles_indice = set(zip(ind_paires[ind_paires.gap == 0].date_prec, ind_paires[ind_paires.gap == 0].date))
commun = sorted(cles_solibra & cles_indice)
apparies = (R_Q.set_index(["date_prec", "date"]).join(ind_paires.set_index(["date_prec", "date"]), how="inner")
            .reset_index())
apparies = apparies[~apparies.classe.str.startswith("bloqué")]
print(f"Rendements appariés (SOLIBRA quotidien admissible et indice sans lacune) : {len(apparies)}")
dates_solibra = set(obs.Date)
dates_indice = set(ind.Date)
non_app_solibra = sorted(d for d in dates_solibra - dates_indice)
non_app_indice = sorted(d for d in dates_indice - dates_solibra)
print(f"Dates SOLIBRA absentes de l'indice : {len(non_app_solibra)} ; dates de l'indice absentes de SOLIBRA : {len(non_app_indice)}")
pd.DataFrame({"date": [d.date().isoformat() for d in non_app_solibra], "serie": "SOLIBRA seul"}).to_csv(
    os.path.join(SORTIE, "tables", "dates_non_appariees.csv"), index=False)
pd.concat([pd.DataFrame({"date": [d.date().isoformat() for d in non_app_solibra], "serie": "SOLIBRA seul"}),
           pd.DataFrame({"date": [d.date().isoformat() for d in non_app_indice], "serie": "indice seul"})]).to_csv(
    os.path.join(SORTIE, "tables", "dates_non_appariees.csv"), index=False)

# %% [markdown]
# ### H.3 Performances, corrélations et régression
# - Performances comparées sur les mêmes bornes (S3 et 2025), **cours seulement**.
# - Corrélations de Pearson (linéaire) et de Spearman (rangs, robuste aux extrêmes).
# - Régression `r_SOLIBRA = α + β · r_indice + ε`, estimée par MCO, erreurs standards **HAC** de Newey-West
#   avec `maxlags = floor(4 · (n/100)^(2/9))` (règle de Newey-West, 1994, pour la dépendance modérée des rendements).
# - Le terme constant n'est **pas** qualifié d'alpha CAPM : aucun taux sans risque documenté, donc pas de rendements excédentaires.
# - `R²` est donné à titre descriptif.

# %%
if len(apparies) >= 30:
    pear = stats.pearsonr(apparies.r_simple, apparies.r_indice_simple)
    spear = stats.spearmanr(apparies.r_simple, apparies.r_indice_simple)
    lags_hac = int(np.floor(4 * (len(apparies) / 100) ** (2 / 9)))
    X = sm.add_constant(apparies.r_indice_simple.values)
    modele = sm.OLS(apparies.r_simple.values, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags_hac})
    ic = modele.conf_int(alpha=0.05)
    reg = pd.DataFrame([{
        "n": len(apparies), "pearson": pear.statistic, "pearson_p": pear.pvalue,
        "spearman": spear.statistic, "spearman_p": spear.pvalue,
        "beta_marche": modele.params[1], "beta_IC95_bas": ic[1, 0], "beta_IC95_haut": ic[1, 1], "beta_p_HAC": modele.pvalues[1],
        "constante_non_alpha": modele.params[0], "constante_p_HAC": modele.pvalues[0],
        "R2": modele.rsquared, "HAC_maxlags": lags_hac,
    }])
    reg.to_csv(os.path.join(SORTIE, "tables", "regression_marche.csv"), index=False)
    pd.set_option("display.float_format", lambda v: f"{v:,.5f}")
    print(reg.T.to_string())
    pd.set_option("display.float_format", None)
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ax.scatter(apparies.r_indice_simple, apparies.r_simple, s=8, alpha=0.6, color="#1f4e79")
    xx = np.linspace(apparies.r_indice_simple.min(), apparies.r_indice_simple.max(), 50)
    ax.plot(xx, modele.params[0] + modele.params[1] * xx, color="#c55a11", lw=1.2)
    ax.set_xlabel("Rendement simple de l'indice BRVM Composite"); ax.set_ylabel("Rendement simple de SOLIBRA")
    ax.set_title(f"Régression MCO (n={len(apparies)}), erreurs HAC")
    fig.text(0.01, -0.03, "Note : rendements appariés sur mêmes paires de dates sans lacune ; pas de causalité inférée.", fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(SORTIE, "figures", "07_regression_indice.png"), dpi=dpi_png, bbox_inches="tight")
    fig.savefig(os.path.join(SORTIE, "figures", "07_regression_indice.pdf"), bbox_inches="tight")
    plt.show(); plt.close(fig)
else:
    print("Effectif apparié < 30 : régression non estimée")

# %% [markdown]
# ### H.4 Performance comparée (cours) sur les mêmes bornes

# %%
def perf_indice(a, b):
    s = ind[(ind.Date >= a) & (ind.Date <= b)]
    return s.Close.iloc[-1] / s.Close.iloc[0] - 1 if len(s) > 1 else np.nan, (s.Date.iloc[0].date().isoformat() if len(s) else None), (s.Date.iloc[-1].date().isoformat() if len(s) else None)

comp = []
for nom, (a, b) in [("S3 post-fractionnement", (SPLIT_DATE, FIN)), ("2025 complet", (pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")))]:
    s_sol = obs[(obs.Date >= a) & (obs.Date <= b)]
    p_sol = s_sol.Close.iloc[-1] / s_sol.Close.iloc[0] - 1 if len(s_sol) > 1 else np.nan
    p_ind, d0, d1 = perf_indice(a, b)
    comp.append({"fenetre": nom, "perf_SOLIBRA": p_sol, "perf_indice": p_ind, "debut_indice": d0, "fin_indice": d1})
comp_tab = pd.DataFrame(comp)
comp_tab.to_csv(os.path.join(SORTIE, "tables", "comparaison_performance_indice.csv"), index=False)
print(comp_tab.to_string(index=False))

# rendement total indicatif (dividendes du dépôt, conditionnel)
div_pos = dividendes[dividendes.exercice.isin(["2024", "2025"])].copy()
rt_rows = []
for _, r in div_pos.iterrows():
    ex = pd.Timestamp(r.date_detachement)
    avant = obs[obs.Date < ex].Close
    if len(avant) == 0:
        continue
    p0_date = obs[obs.Date < ex].Date.iloc[-1]
    rt_rows.append({"exercice": r.exercice, "date_detachement": r.date_detachement, "pre_detachement_date": p0_date.date().isoformat(),
                    "pre_detachement_cours": avant.iloc[-1], "brut_FCFA": float(r.dividende_brut_FCFA_par_action) if r.dividende_brut_FCFA_par_action else np.nan,
                    "net_FCFA": float(r.dividende_net_FCFA_par_action)})
div_tab = pd.DataFrame(rt_rows)
a0, a1 = pd.Timestamp("2025-01-01"), FIN
s_w = obs[(obs.Date >= a0) & (obs.Date <= a1)]
p_start, p_end = s_w.Close.iloc[0], s_w.Close.iloc[-1]
brut_tot = div_tab.loc[div_tab.date_detachement.between(a0.date().isoformat(), a1.date().isoformat()), "brut_FCFA"].sum()
net_tot = div_tab.loc[div_tab.date_detachement.between(a0.date().isoformat(), a1.date().isoformat()), "net_FCFA"].sum()
rt = pd.DataFrame([{
    "fenetre": "2025-01-02 → 2026-10-14 (aucune base indéterminée, aucun événement de capital documenté dans la fenêtre)",
    "cours_debut": p_start, "cours_fin": p_end,
    "perf_cours": p_end / p_start - 1,
    "rendement_total_brut_indicatif": (p_end + brut_tot) / p_start - 1,
    "rendement_total_net_indicatif": (p_end + net_tot) / p_start - 1,
    "dividendes_bruts_FCFA": brut_tot, "dividendes_nets_FCFA": net_tot,
    "condition": "dividendes documentés uniquement par le dépôt (avis PDF non ouverts) : indicatif",
}])
rt.to_csv(os.path.join(SORTIE, "tables", "rendement_total_indicatif.csv"), index=False)
print(rt.T.to_string())
print("\nSharpe : NON CALCULÉ — aucun taux sans risque documenté (TAUX_SANS_RISQUE = None).")

# %% [markdown]
# ## I. Interprétations et limites
#
# Chaque commentaire suit la même structure : (1) résultat et période, (2) interprétation possible,
# (3) incertitude et limites, (4) conclusion que le résultat ne permet pas d'établir.

# %%
def fmt_pct(v, d=2):
    return "non calculé" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v*100:.{d}f} %"

def bloc(titre, *items):
    print(f"\n### {titre}")
    for lib, txt in items:
        print(f"**{lib}.** {txt}")

v95 = ve_tab[(ve_tab.ensemble == "R_Q toutes périodes") & (ve_tab.niveau == 0.95)].iloc[0]
v99 = ve_tab[(ve_tab.ensemble == "R_Q toutes périodes") & (ve_tab.niveau == 0.99)].iloc[0]
s3 = dd_tab[dd_tab.segment == "S3 post-fractionnement"].iloc[0]
s1 = dd_tab[dd_tab.segment == "S1 pré-suspension"].iloc[0]
bloc("Cours et performance",
     ("1. Résultat", f"Performance des cours sur S1 ({perf_seg.iloc[0].debut} → {perf_seg.iloc[0].fin}) : {fmt_pct(perf_seg.iloc[0].performance_cours)} ; "
      f"sur S3 ({perf_seg.iloc[2].debut} → {perf_seg.iloc[2].fin}) : {fmt_pct(perf_seg.iloc[2].performance_cours)}. "
      f"Performance 2026 partielle (jusqu'au 14/10) : {fmt_pct(perf_an.iloc[4].performance_cours)}."),
     ("2. Interprétation", "Ce sont des variations de cours publiés, non ajustés, hors dividendes. Elles décrivent la trajectoire du prix, pas la rentabilité d'un investisseur."),
     ("3. Incertitude", f"Base des cours indéterminée ; calendrier officiel absent ; source secondaire. Max drawdown S1 : {fmt_pct(s1.max_drawdown)} (sommet {s1.date_sommet}, creux {s1.date_creux}) ; "
      f"S3 : {fmt_pct(s3.max_drawdown)} (sommet {s3.date_sommet}, creux {s3.date_creux}) ; récupération S3 : {s3.date_recuperation}."),
     ("4. Non établi", "Performance sur toute la période (traverse le fractionnement) ; durée de récupération au-delà du segment."))

bloc("Statistiques des rendements",
     ("1. Résultat", f"Sur R_Q (n={int(stat_tab.loc['R_Q simple','n'])}) : moyenne journalière simple {stat_tab.loc['R_Q simple','moyenne']*100:.3f} %, "
      f"écart-type {stat_tab.loc['R_Q simple','ecart_type']*100:.3f} %, asymétrie ajustée {stat_tab.loc['R_Q simple','asymetrie_ajustee']:.3f}, "
      f"kurtosis d'excès {stat_tab.loc['R_Q simple','kurtosis_exces_ajustee']:.3f}, rendements nuls {stat_tab.loc['R_Q simple','proportion_nuls']*100:.1f} %."),
     ("2. Interprétation", "Une kurtosis d'excès positive indique des queues plus lourdes qu'une loi normale de même variance, sous réserve de l'échantillon."),
     ("3. Incertitude", "Les rendements sont « ouvrés consécutifs » sans calendrier officiel : la continuité n'est pas démontrée. Les rendements nuls peuvent refléter des cours inchangés, non des séances sans cotation démontrées."),
     ("4. Non établi", "Une loi de distribution précise, ou une règle de rendement quotidien ; la moyenne ne doit pas être extrapolée."))

bloc("Volatilité et risque",
     ("1. Résultat", f"VaR 95 % (une séance admissible) : {fmt_pct(v95.VaR)} (IC bootstrap {fmt_pct(v95.VaR_IC95_bas)} – {fmt_pct(v95.VaR_IC95_haut)}), "
      f"queue de {int(v95.obs_dans_queue)} observations. ES 95 % : {fmt_pct(v95.ES)}. VaR 99 % : {fmt_pct(v99.VaR)} sur {int(v99.obs_dans_queue)} observations seulement."),
     ("2. Interprétation", "Estimation historique d'une perte journalière relative, à partir de l'échantillon observé."),
     ("3. Incertitude", f"Queue 99 % < {MIN_QUEUE} observations : estimation instable, à ne pas présenter comme robuste. Pas d'annualisation (calendrier absent). Pas d'extension à plusieurs jours."),
     ("4. Non établi", "La perte maximale future ; la VaR sur plusieurs séances ; un risque de liquidité déduit des volumes."))


t1 = tests_tab.set_index("serie")
s3_lb5 = t1.loc["S3 post-fractionnement", "LjungBox_rend_p_lag5"]
s3_arch = t1.loc["S3 post-fractionnement", "ARCH_LM_p"]
s3_lb_carre = t1.loc["S3 post-fractionnement", "LjungBox_carres_p_lag5"]
bloc("Diagnostics statistiques (S1 et S3, rendements log admissibles)",
     ("1. Résultat", f"Ljung-Box sur rendements (retards 5) : p = {s3_lb5:.3f} sur S3 ; sur carrés : p = {s3_lb_carre:.3g}. "
      f"Test ARCH-LM (5 retards) : p = {s3_arch:.3g} sur S3 ; p = {t1.loc['S1 pré-suspension','ARCH_LM_p']:.3f} sur S1 (n={int(t1.loc['S1 pré-suspension','n_rendements'])}). "
      f"Jarque-Bera rejette la normalité sur les deux segments (p < 0,001). ADF rejette la racine unitaire sur les rendements ; "
      f"KPSS ne rejette pas la stationnarité des rendements (p bornée à 0,10 par l'implémentation)."),
     ("2. Interprétation", f"Sur S3, les carrés des rendements présentent une autocorrélation significative (p = {s3_lb_carre:.3g}) et l'effet ARCH est significatif (p = {s3_arch:.3g}) : "
      f"la volatilité semble regroupée dans le temps. Les rendements eux-mêmes présentent une autocorrélation significative au retard 5 sur S3 (p = {s3_lb5:.3f}) "
      f"et non significative sur S1 (p = {t1.loc['S1 pré-suspension','LjungBox_rend_p_lag5']:.3f}) : résultat fragile, à confirmer sur une série quotidienne complète. "
      "Le rejet de la normalité est attendu avec des queues lourdes."),
     ("3. Incertitude", "Les retards sont fixés (5 et 10 pour Ljung-Box, 5 pour ARCH) sans optimisation ; une dizaine de tests sont présentés, sans correction de multiplicité ; "
      "les rendements ne sont pas strictement quotidiens (continuité non démontrée), ce qui peut créer une autocorrélation artificielle."),
     ("4. Non établi", "Un rejet de normalité ou d'absence d'autocorrélation ne démontre pas une prévisibilité. Absence de rejet ≠ hypothèse nulle vérifiée. "
      "Aucune prévision n'est dérivée de ces tests."))

rb = rob.set_index("echantillon")
bloc("Robustesse",
     ("1. Résultat", f"VaR 95 % : {fmt_pct(rb.loc['quotidiens admissibles (principal)','VaR95'])} (principal), "
      f"{fmt_pct(rb.loc['quotidiens sans 1 % extrêmes (sensibilité)','VaR95'])} sans 1 % extrêmes, "
      f"{fmt_pct(rb.loc['2025 seul','VaR95'])} sur 2025 seul, {fmt_pct(rb.loc['2026 jusqu\'au 14/10 (partiel)','VaR95'])} sur 2026 partiel. "
      f"Écart-type log : {rb.loc['quotidiens admissibles (principal)','ecart_type_log']*100:.2f} % (principal) contre "
      f"{rb.loc['lacunes seules','ecart_type_log']*100:.2f} % sur les seules lacunes (n={int(rb.loc['lacunes seules','n'])})."),
     ("2. Interprétation", f"La VaR à 95 % varie de {fmt_pct(rob.VaR95.min())} à {fmt_pct(rob.VaR95.max())} selon l'échantillon. "
      "La variante sans 1 % extrêmes et la sous-période 2025 la réduisent ; la variante 2026 partielle la réduit davantage (effectif plus faible). "
      "Les rendements franchissant des lacunes ont un écart-type proche mais un effectif beaucoup plus faible."),
     ("3. Incertitude", "Les variantes ne se recoupent pas toutes : 2026 partiel (n=184) a une kurtosis d'excès très élevée (5,1) ; les extrêmes "
      "influencent fortement l'asymétrie. Aucune variante n'est présentée comme la référence définitive."),
     ("4. Non établi", "Une stabilité des paramètres dans le temps au-delà de ces sous-périodes ; l'effet des séances à volume nul, dont les cours peuvent être inchangés."))

vr = vol_reg  # indexé par régime
bloc("Volumes publiés (régimes d'unités séparés)",
     ("1. Résultat", f"Avant fractionnement : médiane {vr.loc['avant fractionnement','mediane']:.0f} titres (n={int(vr.loc['avant fractionnement','n'])}, "
      f"{int(vr.loc['avant fractionnement','nuls'])} nuls). Après : médiane {vr.loc['après fractionnement','mediane']:.0f} titres "
      f"(n={int(vr.loc['après fractionnement','n'])}, {int(vr.loc['après fractionnement','nuls'])} nul). "
      f"Valeurs atypiques (Tukey dans chaque régime, conservées) : {len(vol_out)}."),
     ("2. Interprétation", "Les niveaux de volume publiés diffèrent fortement entre régimes, mais ces régimes ont des unités d'action différentes : "
      "la différence n'est pas interprétable comme une variation de liquidité sans conversion documentée."),
     ("3. Incertitude", "Volume FCFA est un montant publié (probablement un VWAP), non vérifié ; Close × Volume n'est pas un montant échangé documenté. "
      "Les volumes nuls sont documentés par Volume FCFA = 0, pas par un bulletin."),
     ("4. Non établi", "Une conclusion de liquidité ou d'illiquidité à partir de la seule moyenne ; une comparaison directe des volumes avant et après fractionnement."))

ic = boot_tab.set_index(["statistique", "bloc"])
ri = reg.iloc[0]
bloc("Comparaison au BRVM Composite",
     ("1. Résultat", f"Rendements appariés (mêmes paires de dates sans lacune) : n = {len(apparies)}. Corrélation de Pearson = {ri.pearson:.3f} (p = {ri.pearson_p:.1e}), "
      f"Spearman = {ri.spearman:.3f} (p = {ri.spearman_p:.1e}). Régression : bêta = {ri.beta_marche:.3f} "
      f"(IC95 HAC {ri.beta_IC95_bas:.3f} – {ri.beta_IC95_haut:.3f}), R² = {ri.R2:.3f}. "
      f"Performance des cours S3 : SOLIBRA {fmt_pct(comp_tab.iloc[0].perf_SOLIBRA)} contre indice {fmt_pct(comp_tab.iloc[0].perf_indice)}."),
     ("2. Interprétation", f"Le lien contemporain entre les rendements est faible (R² = {ri.R2:.3f}) : l'indice explique très peu de la variance des rendements de SOLIBRA sur cette fenêtre. "
      "Le bêta est estimé avec une incertitude large ; il ne constitue pas une mesure stable du risque systématique sur cette fenêtre."),
     ("3. Incertitude", f"Les constantes ne sont pas des alphas CAPM (pas de taux sans risque). Si SOLIBRA est une composante de l'indice — ce que les fichiers joints ne permettent pas de vérifier — "
      "la corrélation peut être mécanique. Les rendements synchrones ne tiennent pas compte d'éventuels décalages de négociation. "
      f"{int((dn := pd.read_csv(os.path.join(SORTIE, 'tables', 'dates_non_appariees.csv'))).serie.eq('indice seul').sum())} dates de l'indice ne sont pas des séances SOLIBRA."),
     ("4. Non établi", "Un coefficient de risque systématique stable, un alpha, un Sharpe ou une causalité entre indice et titre."))

rt0 = rt.iloc[0]
bloc("Rendement total indicatif",
     ("1. Résultat", f"Du 02/01/2025 au 14/10/2026 : performance des cours {fmt_pct(rt0.perf_cours)} ; rendement total indicatif brut {fmt_pct(rt0.rendement_total_brut_indicatif)} "
      f"et net {fmt_pct(rt0.rendement_total_net_indicatif)}, en ajoutant {rt0.dividendes_bruts_FCFA:,.0f} FCFA bruts (exercices 2024 et 2025, détachements dans la fenêtre)."),
     ("2. Interprétation", "L'apport des dividendes est faible par rapport à la hausse des cours sur la même fenêtre ; le rendement total est dominé par la trajectoire du prix."),
     ("3. Incertitude", "Dividendes tirés du dépôt, avis PDF non ouverts ; pas de Sharpe (taux sans risque absent) ; fiscalité et retenue à la source non modélisées au-delà du montant net publié."),
     ("4. Non établi", "Un rendement total sur la période complète (fractionnement non résolu) ni un rendement total pour 2023-2024."))

# tableau de synthèse
syn = pd.DataFrame([
    {"analyse": "Cours et performance (segments)", "effectif": f"{len(obs)} observations ; segments S1 (n={int(perf_seg.iloc[0].n)}) et S3 (n={int(perf_seg.iloc[2].n)})",
     "conditions": "base non ajustée indéterminée : calcul par segment seulement", "limites": "bornes de S1 = séances sans transaction ; source secondaire", "conclusion": "trajectoire des cours publiés sur S3 ; pas de performance sur toute la période"},
    {"analyse": "Rendements simples et log", "effectif": f"{len(R_Q)} quotidiens admissibles ; {len(R_GAP)} lacunes séparées", "conditions": "non-blocage fractionnement et suspension", "limites": "continuité non démontrée", "conclusion": "distribution descriptive des rendements observés"},
    {"analyse": "Statistiques des rendements", "effectif": f"{len(R_Q)}", "conditions": "conventions explicites", "limites": "27 % de rendements nuls ; extrêmes influents", "conclusion": "queues lourdes et asymétrie faible ; pas de loi précise"},
    {"analyse": "Volatilité", "effectif": f"{len(R_Q)} (fenêtres 20 et 60)", "conditions": "pas d'annualisation", "limites": "pas de calendrier pour la racine du temps", "conclusion": "volatilité observée à la fréquence des observations"},
    {"analyse": "VaR / ES historiques 95 %", "effectif": f"{int(v95.n)} ; queue {int(v95.obs_dans_queue)}", "conditions": "queue ≥ 30 : satisfaite", "limites": "un jour ; IC bootstrap sous dépendance", "conclusion": "perte journalière historique relative d'environ 6 % à 7 %"},
    {"analyse": "VaR / ES historiques 99 %", "effectif": f"queue {int(v99.obs_dans_queue)}", "conditions": "queue ≥ 30 : non satisfaite", "limites": "estimation instable", "conclusion": "aucune conclusion robuste"},
    {"analyse": "Diagnostics (LB, ARCH, ADF, KPSS, JB)", "effectif": f"{int(t1.loc['S3 post-fractionnement','n_rendements'])} (S3) et {int(t1.loc['S1 pré-suspension','n_rendements'])} (S1)", "conditions": "effectif ≥ 30", "limites": "tests multiples ; retards fixés ; KPSS bornée", "conclusion": "dépendance de la volatilité sur S3 ; pas de prévisibilité démontrée"},
    {"analyse": "Comparaison à l'indice (corrélation, bêta)", "effectif": f"{len(apparies)} appariés", "conditions": "dates appariées sans lacune", "limites": "pas de taux sans risque ; composition de l'indice non vérifiée", "conclusion": "lien faible, bêta imprécis"},
    {"analyse": "Rendement total indicatif", "effectif": "2 détachements dans la fenêtre", "conditions": "dividendes documentés par le dépôt uniquement", "limites": "avis PDF non ouverts", "conclusion": "indicatif seulement"},
    {"analyse": "Sharpe", "effectif": "—", "conditions": "taux sans risque absent", "limites": "non calculé", "conclusion": "aucune"},
])
syn.to_csv(os.path.join(SORTIE, "tables", "tableau_synthese_analyses.csv"), index=False)
print(syn.to_string(index=False))

# %% [markdown]
# ## J. Export des résultats
# Les tableaux sont écrits dans `resultats/tables`, les figures dans `resultats/figures` (PNG 300 dpi et PDF),
# le journal dans `resultats/journal`, les versions dans `resultats/versions.txt`.

# %%
journal_final = pd.concat([
    exclusions.assign(type="exclusion ou retrait", origine="fichiers joints"),
    pd.DataFrame([{"date": "", "close": "", "volume": "", "volume_FCFA": "",
                   "raison": "fractionnement : base des cours indéterminée ; calculs traversant le 30/09/2024 bloqués",
                   "reference": "METADONNEES_SERIE.json ; avis n°242 non lu", "type": "contradiction non résolue", "origine": "analyse"},
                  {"date": "", "close": "", "volume": "", "volume_FCFA": "",
                   "raison": f"{int(paires.classe.str.startswith('bloqué').sum())} rendements bloqués (fractionnement ou suspension)",
                   "reference": "tables/paires_successives_toutes.csv", "type": "blocage de calcul", "origine": "analyse"},
                  {"date": "", "close": "", "volume": "", "volume_FCFA": "",
                   "raison": "calendrier officiel absent : continuité quotidienne non démontrée",
                   "reference": "CALENDRIER_COUVERTURE_2023_2026.csv", "type": "limite", "origine": "analyse"}]),
], ignore_index=True)
journal_final.to_csv(os.path.join(SORTIE, "journal", "journal_controles_exclusions.csv"), index=False)

versions = {
    "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
    "matplotlib": matplotlib.__version__, "seaborn": sns.__version__, "scipy": scipy.__version__,
    "statsmodels": statsmodels.__version__,
}
with open(os.path.join(SORTIE, "versions.txt"), "w", encoding="utf-8") as f:
    for k, v in versions.items():
        f.write(f"{k}=={v}\n")
print(open(os.path.join(SORTIE, "versions.txt"), encoding="utf-8").read())
print("Effectifs utilisés :", {"R_Q": len(R_Q), "R_GAP": len(R_GAP), "R_TOUS": len(R_TOUS), "obs": len(obs), "apparies": len(apparies)})
print("Export terminé :", sorted(os.listdir(os.path.join(SORTIE, "tables")))[:40])
