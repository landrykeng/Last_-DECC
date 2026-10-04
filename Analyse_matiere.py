"""
Analyse par matière - un onglet par examen
Lancement : streamlit run Analyse_matiere.py

Rappel : les notes de matière sont analysées sur 20 (non pondérées). La pondération par
les coefficients ne s'applique qu'à la moyenne individuelle du candidat (cf. utils.py).
"""
import numpy as np
import pandas as pd
import streamlit as st

from utils import (
    EXAMS, AMBER, NAVY, PALETTE, TEAL,
    Import_data, bar_chart, bar_table, box_stats, boxplot_chart, cached_box,
    cached_subject_metric, cascade_filters, entity_pivot, fmt_int, heatmap_chart, hero,
    hist_chart, inject_css, reset_chart_keys, scatter_chart, section, sidebar_data_controls,
    sidebar_thresholds, subject_metric,
)

st.set_page_config(page_title="Analyse par matière", page_icon=":material/menu_book:",
                   layout="wide")
inject_css()
reset_chart_keys()
hero("Analyse par matière", "Performances, disparités et profils de réussite, matière par matière")

Import_data()
if not st.session_state.get("raw"):
    st.error("Aucun fichier CSV trouvé. Placez les fichiers dans un dossier `data/` à côté "
             "de ce script (ou définissez DATA_DIR).", icon=":material/error:")
    st.stop()

raw = st.session_state["raw"]
ver = st.session_state["_data_ver"]
exams = [e for e in EXAMS if e in raw]

sidebar_data_controls()
seuils = sidebar_thresholds(exams, prefix="mat", title="Seuil de réussite par matière",
                            icon="rule")
st.sidebar.caption("Une note ≥ seuil (sur 20) est considérée comme réussie dans la matière.")
with st.sidebar.expander("Coefficients des matières", icon=":material/calculate:"):
    st.caption("Issus de tableau_matieres_coefficients.xlsx (utilisés pour la moyenne "
               "individuelle pondérée).")
    for _e, _cm in st.session_state.get("coefs", {}).items():
        if _cm:
            st.markdown(f"**{_e}** · total {sum(_cm.values()):g}")
            st.dataframe(pd.DataFrame({"MATIERE": list(_cm), "COEF": list(_cm.values())}),
                         hide_index=True, height=min(300, 36 * len(_cm) + 40))


@st.cache_data(show_spinner=False, max_entries=12)
def clean_subjects(exam, ver, _raw):
    return _raw.dropna(subset=["NOTE20"]).reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=12)
def cached_profile(exam, seuil, ver, _df):
    p = _df.groupby(["CID", "MATIERE"], observed=True)["NOTE20"].mean().unstack()
    if len(p) > 300_000:
        p = p.sample(300_000, random_state=0)
    corr = p.corr(min_periods=30)
    disc = pd.Series({c: p[c].corr(p.drop(columns=c).mean(axis=1)) for c in p.columns})
    dist = (p < seuil).sum(axis=1).value_counts().sort_index()
    return corr, disc, dist


def long_corr(corr):
    return corr.rename_axis(index="M1", columns="M2").stack().rename("VALUE").reset_index()


def render_exam(name):
    seuil = seuils[name]
    d = clean_subjects(name, ver, raw[name])
    if d.empty:
        st.info("Aucune note exploitable.", icon=":material/info:")
        return

    def mt(by, metric):
        return cached_subject_metric(name, (), seuil, tuple(by), metric, ver, d)

    nat_moy = d["NOTE20"].mean()
    nat_sd = d["NOTE20"].std()
    nat_rate = (d["NOTE20"] >= seuil).mean() * 100
    subj = mt(["MATIERE"], "moy").sort_values("VALUE")
    weak, best = subj.iloc[0], subj.iloc[-1]

    k = st.columns(5)
    #k[0].metric("Matières", fmt_int(d["MATIERE"].nunique()))
    #k[1].metric("Moyenne des notes", f"{nat_moy:.2f}", f"Écart type : {nat_sd:.2f}", delta_color="off")
    #k[2].metric("Taux de réussite (notes)", f"{nat_rate:.1f} %", f"Seuil : {seuil:.2f}", delta_color="off")
    #k[3].metric("Matière la plus forte", str(best["MATIERE"]), f"Moyenne : {best['VALUE']:.2f}",
       #         delta_color="off")
    #k[4].metric("Matière la plus faible", str(weak["MATIERE"]), f"Moyenne : {weak['VALUE']:.2f}",
       #         delta_color="off")

    # ---- A. Vue d'ensemble --------------------------------------------------
    section("overview", "Vue d'ensemble des matières",
            "La ligne pointillée rouge indique le niveau national.")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        bar_chart(subj, "MATIERE", "VALUE", horizontal=True, decimals=2,
                  title="Moyenne par matière (/20)", ref=nat_moy, ref_label="Moyenne nationale")
    with c2.container(border=True):
        bar_chart(mt(["MATIERE"], "taux"), "MATIERE", "VALUE", horizontal=True, unit="%",
                  title="Taux de réussite par matière", ref=nat_rate, ref_label="National",
                  colors=[TEAL])
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        gap = subj.copy()
        gap["VALUE"] = gap["VALUE"] - nat_moy
        bar_chart(gap, "MATIERE", "VALUE", horizontal=True, decimals=2, diverging=True, ref=0,
                  ref_label="Moyenne nationale", title="Écart à la moyenne nationale",
                  subtitle="Matières qui tirent les résultats vers le haut ou vers le bas")
    with c2.container(border=True):
        stats = cached_box(f"{name}_mat", "MATIERE", "NOTE20", ver, d)
        boxplot_chart(stats, horizontal=True, title="Dispersion des notes par matière",
                      subtitle="Boîte : Q1–Q3 · trait : médiane · moustaches : P5–P95",
                      ref=nat_moy, ref_label="Moyenne nationale")
    sc = subj.merge(mt(["MATIERE"], "std"), on="MATIERE", suffixes=("_m", "_s")).merge(
        mt(["MATIERE"], "eff"), on="MATIERE")

    # ---- B. Ordre d'enseignement -------------------------------------------
    section("account_balance", "Matières × ordre d'enseignement")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        bar_chart(mt(["MATIERE", "ORDRE_ENS"], "moy"), "MATIERE", "VALUE", group="ORDRE_ENS",
                  horizontal=True, decimals=2, title="Moyenne par matière et ordre d'enseignement",
                  ref=nat_moy, ref_label="Moyenne nationale")
    with c2.container(border=True):
        bar_chart(mt(["MATIERE", "ORDRE_ENS"], "taux"), "MATIERE", "VALUE", group="ORDRE_ENS",
                  horizontal=True, unit="%", title="Taux de réussite par matière et ordre",
                  ref=nat_rate, ref_label="National")
    po = mt(["MATIERE", "ORDRE_ENS"], "moy").pivot_table(index="MATIERE", columns="ORDRE_ENS",
                                                         values="VALUE")

    # ---- C. Régions ---------------------------------------------------------
    section("map", "Matières × régions")
    reg_m, reg_t = mt(["REGION", "MATIERE"], "moy"), mt(["REGION", "MATIERE"], "taux")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        heatmap_chart(reg_m, "MATIERE", "REGION", "VALUE", decimals=2,
                      title="Moyenne par région et matière")
    with c2.container(border=True):
        heatmap_chart(reg_t, "MATIERE", "REGION", "VALUE", unit="%",
                      title="Taux de réussite par région et matière")
    with st.container(border=True):
        st.markdown("**Matière la plus forte et la plus faible de chaque région**")
        rows = []
        for r, g in reg_m.groupby("REGION"):
            rows.append({"Région": r, "Matière la plus forte": g.loc[g["VALUE"].idxmax(), "MATIERE"],
                         "Moyenne (forte)": g["VALUE"].max(),
                         "Matière la plus faible": g.loc[g["VALUE"].idxmin(), "MATIERE"],
                         "Moyenne (faible)": g["VALUE"].min(),
                         "Amplitude": g["VALUE"].max() - g["VALUE"].min()})
        bar_table(pd.DataFrame(rows), ["Moyenne (forte)", "Moyenne (faible)", "Amplitude"],
                  fmt="{:.2f}", vmax=20.0, color=NAVY, height=360)

    # ---- D. Séries ----------------------------------------------------------
    section("category", "Matières × séries")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        heatmap_chart(mt(["SERIE", "MATIERE"], "moy"), "MATIERE", "SERIE", "VALUE", decimals=2,
                      title="Moyenne par série et matière")
    with c2.container(border=True):
        heatmap_chart(mt(["SERIE", "MATIERE"], "taux"), "MATIERE", "SERIE", "VALUE", unit="%",
                      title="Taux de réussite par série et matière")

    # ---- E. Focus matière ---------------------------------------------------
    section("center_focus_strong", "Focus sur une matière",
            "Toutes les analyses ci-dessous portent sur la matière choisie.")
    mat = st.selectbox("Matière", sorted(d["MATIERE"].astype(str).unique()), key=f"focus_{name}")
    dm = d[d["MATIERE"] == mat]
    m_moy, m_rate = dm["NOTE20"].mean(), (dm["NOTE20"] >= seuil).mean() * 100
    f = st.columns(4)
    f[0].metric("Notes", fmt_int(len(dm)))
    f[1].metric("Moyenne", f"{m_moy:.2f}", f"Écart type : {dm['NOTE20'].std():.2f}", delta_color="off")
    f[2].metric("Taux de réussite", f"{m_rate:.1f} %", delta_color="off")
    f[3].metric("Médiane", f"{dm['NOTE20'].median():.2f}", delta_color="off")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        bar_chart(subject_metric(dm, ["REGION"], "moy", seuil), "REGION", "VALUE", decimals=2,
                  title=f"{mat} : moyenne par région", ref=m_moy, ref_label="National")
    with c2.container(border=True):
        bar_chart(subject_metric(dm, ["REGION"], "taux", seuil), "REGION", "VALUE", unit="%",
                  title=f"{mat} : taux de réussite par région", ref=m_rate, ref_label="National",
                  colors=[TEAL])
    with st.container(border=True):
        dmf, scope = cascade_filters(dm, f"flt_{name}", ver, map_df=d)
    if dmf.empty:
        st.info("Aucune note pour cette sélection.", icon=":material/info:")
    else:
        s_moy, s_rate = dmf["NOTE20"].mean(), (dmf["NOTE20"] >= seuil).mean() * 100
        st.caption(f"Périmètre : **{scope}** · {fmt_int(len(dmf))} notes")
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            bar_chart(subject_metric(dmf, ["DEPARTEMENT"], "moy", seuil).head(40), "DEPARTEMENT",
                      "VALUE", horizontal=True, decimals=2, title=f"{mat} : moyenne par département",
                      ref=s_moy, ref_label=scope)
        with c2.container(border=True):
            hist_chart(dmf["NOTE20"].to_numpy(), threshold=seuil, title=f"{mat} : distribution des notes",
                       xlabel="Note /20")
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            bar_chart(subject_metric(dmf, ["SERIE", "ORDRE_ENS"], "moy", seuil), "SERIE", "VALUE",
                      group="ORDRE_ENS", sort=None, decimals=2,
                      title=f"{mat} : moyenne par série et ordre", ref=s_moy, ref_label=scope)
        with c2.container(border=True):
            bar_chart(subject_metric(dmf, ["SERIE", "ORDRE_ENS"], "taux", seuil), "SERIE", "VALUE",
                      group="ORDRE_ENS", sort=None, unit="%",
                      title=f"{mat} : taux de réussite par série et ordre", ref=s_rate, ref_label=scope)
        with st.container(border=True):
            t1, t2 = st.columns(2)
            min_eff = t1.number_input("Effectif minimum", 1, 100000, 20, key=f"me_{name}")
            top_n = t2.number_input("Établissements affichés", 5, 500, 40, key=f"tn_{name}")
            st.markdown(f"**{mat} : moyenne par établissement et série**")
            tab, cols = entity_pivot(dmf, lambda x, by: subject_metric(x, by, "moy", seuil), "SERIE",
                                     min_eff=min_eff, top_n=top_n, eff_label="NB NOTES")
            bar_table(tab, cols, fmt="{:.2f}", vmax=20.0, int_cols=["NB NOTES"])

    # ---- F. Établissements × matières ---------------------------------------
    section("apartment", "Établissements × matières",
            "Moyenne /20 de chaque établissement dans chaque matière (filtres en cascade).")
    with st.container(border=True):
        df2, scope2 = cascade_filters(d, f"flt2_{name}", ver)
        t1, t2 = st.columns(2)
        min_eff2 = t1.number_input("Effectif minimum (notes)", 1, 100000, 30, key=f"me2_{name}")
        top2 = t2.number_input("Établissements affichés", 5, 500, 40, key=f"tn2_{name}")
        if df2.empty:
            st.info("Aucune note pour cette sélection.", icon=":material/info:")
        else:
            tab2, cols2 = entity_pivot(df2, lambda x, by: subject_metric(x, by, "moy", seuil),
                                       "MATIERE", min_eff=min_eff2, top_n=top2,
                                       eff_label="NB NOTES")
            bar_table(tab2, cols2, fmt="{:.2f}", vmax=20.0, int_cols=["NB NOTES"], height=520)

    # ---- G. Départements : écart à la moyenne nationale ---------------------
    section("compare_arrows", "Départements × matières : écart à la moyenne nationale")
    dep = mt(["REGION", "DEPARTEMENT", "MATIERE"], "moy")
    nat_by = subj.set_index("MATIERE")["VALUE"]
    dep = dep.assign(VALUE=dep["VALUE"] - dep["MATIERE"].map(nat_by))
    reg = st.selectbox("Filtrer par région", ["Toutes les régions"] + sorted(dep["REGION"].unique()),
                       key=f"dep_reg_{name}")
    if reg != "Toutes les régions":
        dep = dep[dep["REGION"] == reg]
    lim = float(np.nanmax(np.abs(dep["VALUE"]))) if len(dep) else 1.0
    with st.container(border=True):
        heatmap_chart(dep, "MATIERE", "DEPARTEMENT", "VALUE", decimals=2, vmin=-lim, vmax=lim,
                      title="Écart de moyenne à la moyenne nationale de la matière",
                      subtitle="Vert : au-dessus de la moyenne nationale · Rouge : en dessous")

    # ---- H. Profil des candidats --------------------------------------------
    section("psychology", "Profil des candidats et liens entre matières")
    corr, disc, dist = cached_profile(name, seuil, ver, d)
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        share = (dist / dist.sum() * 100).rename("VALUE").reset_index()
        share.columns = ["NB", "VALUE"]
        share["NB"] = share["NB"].astype(int).astype(str)
        bar_chart(share, "NB", "VALUE", unit="%", sort=None, colors=[AMBER],
                  title="Candidats selon le nombre de matières en dessous du seuil",
                  subtitle="Part des candidats ayant échoué dans 0, 1, 2… matières")
    with c2.container(border=True):
        bar_chart(pd.DataFrame({"MATIERE": disc.index.astype(str), "VALUE": disc.values}),
                  "MATIERE", "VALUE", horizontal=True, decimals=2, colors=[PALETTE[5]],
                  title="Pouvoir discriminant des matières",
                  subtitle="Corrélation de la note avec la moyenne des autres matières")
    with st.container(border=True):
        heatmap_chart(long_corr(corr), "M1", "M2", "VALUE", decimals=2, sort_y=False, vmin=-0.2, vmax=1,
                      title="Corrélation entre les notes des matières")


tabs = st.tabs([f"{EXAMS[e]['icon']} {e}" for e in exams])
for tab, e in zip(tabs, exams):
    with tab:
        render_exam(e)
