"""
Tableau de bord des résultats d'examens

"""
import numpy as np
import pandas as pd
import streamlit as st

from utils import (
    EXAMS, METRICS, NAVY, RED, TEAL, PALETTE,
    Import_data, bar_chart, bar_table, boxplot_chart, cached_box, cached_metric,
    cached_metric_all, cascade_filters, entity_pivot, fmt_int, gauge_chart, heatmap_chart,
    hero, hist_chart, inject_css, metric_table, ref_value, reset_chart_keys, scatter_chart,
    section, sidebar_data_controls, sidebar_thresholds, box_stats,
)

st.set_page_config(page_title="Résultats d'examens", page_icon=":material/analytics:",
                   layout="wide")
inject_css()
reset_chart_keys()
hero("Tableau de bord des résultats d'examens",
     "Taux de réussite, moyennes et analyses territoriales par examen")

Import_data()
if not st.session_state.get("cand"):
    st.error("Aucun fichier CSV trouvé. Placez les fichiers dans un dossier `data/` à côté "
             "de app.py (ou définissez la variable d'environnement DATA_DIR).",
             icon=":material/error:")
    st.stop()

cand = st.session_state["cand"]
cand_all = st.session_state["cand_all"]
ver = st.session_state["_data_ver"]
exams = [e for e in EXAMS if e in cand]

sidebar_data_controls()
seuils = sidebar_thresholds(exams, prefix="gen")
seuils_key = tuple(sorted(seuils.items()))


def mt_all(by, metric):
    return cached_metric_all(seuils_key, tuple(by), metric, ver, cand_all)


def region_filter(label, key, df, col="REGION"):
    opts = ["Toutes les régions"] + sorted(df[col].astype(str).unique())
    return st.selectbox(label, opts, key=key)


# -----------------------------------------------------------------------------
# ONGLET GÉNÉRAL (sans cadres autour des graphiques)
# -----------------------------------------------------------------------------
def crosses(metric, unit, dec, label):
    """Croisements région / ordre / heatmap département x examen pour une métrique."""
    c1, c2 = st.columns(2)
    with c1:
        bar_chart(mt_all(["REGION", "EXAMEN"], metric), "REGION", "VALUE", group="EXAMEN",
                  title=f"{label} par région et examen", unit=unit, decimals=dec)
    with c2:
        bar_chart(mt_all(["ORDRE_ENS", "EXAMEN"], metric), "ORDRE_ENS", "VALUE",
                  group="EXAMEN", title=f"{label} par ordre d'enseignement et examen",
                  unit=unit, decimals=dec, sort=None)
    dep = mt_all(["REGION", "DEPARTEMENT", "EXAMEN"], metric)
    reg = region_filter("Filtrer la heatmap par région", f"hm_{metric}", dep)
    if reg != "Toutes les régions":
        dep = dep[dep["REGION"] == reg]
    heatmap_chart(dep, "EXAMEN", "DEPARTEMENT", "VALUE",
                  title=f"{label} par département et examen", unit=unit, decimals=dec)


def render_general():
    section("speed", "Indicateurs clés",
            "Valeur : taux de réussite au seuil choisi · Delta : moyenne générale à l'examen")
    for i in range(0, len(exams), 3):
        cols = st.columns(3)
        for col, e in zip(cols, exams[i:i + 3]):
            d = cand[e]
            rate = (d["MOYENNE"] >= seuils[e]).mean() * 100
            col.metric(e, f"{rate:.1f} %",
                       f"Moyenne générale : {d['MOYENNE'].mean():.2f}", delta_color="off",
                       help=f"Seuil d'admission : {seuils[e]:.2f} · {fmt_int(len(d))} candidats")
    st.divider()

    section("emoji_events", "1. Analyse des taux de réussite")
    crosses("taux", "%", 1, "Taux de réussite")
    eff, adm = mt_all(["EXAMEN"], "eff"), mt_all(["EXAMEN"], "admis")
    st_df = eff.merge(adm, on="EXAMEN", suffixes=("_e", "_a"))
    st_df["Admis"], st_df["Non admis"] = st_df["VALUE_a"], st_df["VALUE_e"] - st_df["VALUE_a"]
    long = st_df.melt(id_vars="EXAMEN", value_vars=["Admis", "Non admis"], var_name="Statut",
                      value_name="VALUE")
    c1, c2 = st.columns(2)
    with c1:
        bar_chart(long, "EXAMEN", "VALUE", group="Statut", stacked=True, decimals=0, sort=None,
                  colors=[TEAL, RED], title="Admis et non admis par examen",
                  subtitle="Effectifs de candidats")
    with c2:
        ex = st.selectbox("Examen (classement des départements)", exams, key="rank_exam")
        mte = cached_metric(ex, seuils[ex], ("DEPARTEMENT",), "taux", ver, cand[ex])
        mef = cached_metric(ex, seuils[ex], ("DEPARTEMENT",), "eff", ver, cand[ex])
        r = mte.merge(mef, on="DEPARTEMENT", suffixes=("", "_eff"))
        min_eff = st.number_input("Effectif minimum", 1, 100000, 30, key="rank_min")
        r = r[r["VALUE_eff"] >= min_eff].sort_values("VALUE", ascending=False)
        top = pd.concat([r.head(8), r.tail(8)]).drop_duplicates("DEPARTEMENT")
        bar_chart(top, "DEPARTEMENT", "VALUE", horizontal=True, unit="%", decimals=1,
                  title=f"{ex} : 8 meilleurs et 8 derniers départements",
                  ref=ref_value(cand[ex].assign(ADMIS=cand[ex]["MOYENNE"] >= seuils[ex]),
                                "taux"), ref_label="National")
    st.divider()

    section("military_tech", "2. Analyse de la moyenne des admis")
    crosses("moy_admis", "", 2, "Moyenne des admis")
    ex2 = st.selectbox("Examen (marge au-dessus du seuil)", exams, key="margin_exam")
    mm = cached_metric(ex2, seuils[ex2], ("REGION",), "moy_admis", ver, cand[ex2]).copy()
    mm["VALUE"] = mm["VALUE"] - seuils[ex2]
    bar_chart(mm, "REGION", "VALUE", decimals=2, diverging=True, ref=0, ref_label="Seuil",
              title=f"{ex2} : écart entre la moyenne des admis et le seuil, par région",
              subtitle="Mesure l'intensité de la réussite au-delà du seuil d'admission")
    st.divider()

    section("insights", "3. Analyse de la moyenne générale")
    crosses("moy", "", 2, "Moyenne générale")
    c1, c2 = st.columns(2)
    with c1:
        stats = cached_box("all_exam", "EXAMEN", "MOYENNE", ver, cand_all)
        boxplot_chart(stats, title="Distribution des moyennes par examen",
                      subtitle="Boîte : Q1–Q3 · trait : médiane · moustaches : P5–P95")
    with c2:
        ex3 = st.selectbox("Examen (distribution)", exams, key="hist_exam")
        hist_chart(cand[ex3]["MOYENNE"].to_numpy(), threshold=seuils[ex3],
                   title=f"{ex3} : distribution des moyennes", xlabel="Moyenne /20")
    dpt = cached_metric(ex3, seuils[ex3], ("DEPARTEMENT",), "taux", ver, cand[ex3]).merge(
        cached_metric(ex3, seuils[ex3], ("DEPARTEMENT",), "moy", ver, cand[ex3]),
        on="DEPARTEMENT", suffixes=("_t", "_m")).merge(
        cached_metric(ex3, seuils[ex3], ("DEPARTEMENT",), "eff", ver, cand[ex3]),
        on="DEPARTEMENT")
    scatter_chart(dpt, "VALUE_m", "VALUE_t", "DEPARTEMENT", size="VALUE",
                  title=f"{ex3} : moyenne générale et taux de réussite par département",
                  subtitle="Taille des bulles proportionnelle à l'effectif",
                  xlabel="Moyenne générale", ylabel="Taux de réussite", yunit="%",
                  ref_x=cand[ex3]["MOYENNE"].mean(), height=440)


# -----------------------------------------------------------------------------
# ONGLET PAR EXAMEN (graphiques dans des cadres)
# -----------------------------------------------------------------------------
def render_exam(name):
    seuil = seuils[name]
    d0 = cand[name]
    d = d0.assign(ADMIS=d0["MOYENNE"] >= seuil)
    n, n_adm = len(d), int(d["ADMIS"].sum())
    rate = n_adm / n * 100 if n else np.nan
    moy, sd = d["MOYENNE"].mean(), d["MOYENNE"].std()
    adm = d.loc[d["ADMIS"], "MOYENNE"]
    moy_a, sd_a = adm.mean(), adm.std()

    def mt(by, metric):
        return cached_metric(name, seuil, tuple(by), metric, ver, d0)

    g, k1, k2 = st.columns([1.25, 1, 1])
    with g.container(border=True):
        gauge_chart(rate, subtitle=f"Seuil d'admission : {seuil:.2f}")
    with k1:
        st.metric("Moyenne des admis", f"{moy_a:.2f}", f"Écart type : {sd_a:.2f}",
                  delta_color="off")
        st.metric("Candidats", fmt_int(n))
    with k2:
        st.metric("Moyenne générale", f"{moy:.2f}", f"Écart type : {sd:.2f}", delta_color="off")
        st.metric("Admis", fmt_int(n_adm))

    nat = {"taux": rate, "moy_admis": moy_a}
    section("map", "Analyse par région",
            "La ligne pointillée rouge indique le niveau national.")
    for by in ("ORDRE_ENS", "SERIE"):
        lbl = "ordre d'enseignement" if by == "ORDRE_ENS" else "série"
        c1, c2 = st.columns(2)
        for col, metric, unit, dec in ((c1, "taux", "%", 1), (c2, "moy_admis", "", 2)):
            with col.container(border=True):
                bar_chart(mt(["REGION", by], metric), "REGION", "VALUE", group=by,
                          title=f"{METRICS[metric]['label']} : région × {lbl}", unit=unit,
                          decimals=dec, ref=nat[metric], ref_label="National")

    section("filter_alt", "Analyse ciblée (filtres en cascade)",
            "Choisissez une région puis, parmi ses départements, ceux à analyser.")
    with st.container(border=True):
        dd, scope = cascade_filters(d, f"flt_{name}", ver)
    if dd.empty:
        st.info("Aucun candidat pour cette sélection.", icon=":material/info:")
        return
    sc = {"taux": ref_value(dd, "taux"), "moy_admis": ref_value(dd, "moy_admis")}
    st.caption(f"Périmètre : **{scope}** · {fmt_int(len(dd))} candidats")
    c1, c2 = st.columns(2)
    for col, metric, unit, dec in ((c1, "taux", "%", 1), (c2, "moy_admis", "", 2)):
        with col.container(border=True):
            bar_chart(metric_table(dd, ["ORDRE_ENS", "SERIE"], metric), "SERIE", "VALUE",
                      group="ORDRE_ENS", sort=None, unit=unit, decimals=dec,
                      title=f"{METRICS[metric]['label']} : ordre d'enseignement × série",
                      ref=sc[metric], ref_label=scope)

    with st.container(border=True):
        t1, t2 = st.columns(2)
        min_eff = t1.number_input("Effectif minimum par établissement", 1, 100000, 20,
                                  key=f"me_{name}")
        top_n = t2.number_input("Nombre d'établissements affichés", 5, 500, 40, key=f"tn_{name}")
        for metric, fmt, vmax, color in (("taux", "{:.1f}", 100.0, TEAL),
                                         ("moy_admis", "{:.2f}", 20.0, NAVY)):
            st.markdown(f"**{METRICS[metric]['label']} : établissement × série**")
            tab, cols = entity_pivot(dd, lambda x, by, m=metric: metric_table(x, by, m), "SERIE",
                                     min_eff=min_eff, top_n=top_n)
            bar_table(tab, cols, fmt=fmt, vmax=vmax, color=color, int_cols=["EFFECTIF"])

    section("query_stats", "Analyses complémentaires", f"Périmètre : {scope}")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        hist_chart(dd["MOYENNE"].to_numpy(), threshold=seuil,
                   title="Distribution des moyennes", xlabel="Moyenne /20")
    with c2.container(border=True):
        boxplot_chart(box_stats(dd, "SERIE", "MOYENNE"), title="Dispersion des moyennes par série",
                      subtitle="Moustaches : P5–P95", ref=dd["MOYENNE"].mean(), ref_label=scope)
    c1, c2 = st.columns(2)
    dep = metric_table(dd, ["DEPARTEMENT"], "taux").merge(
        metric_table(dd, ["DEPARTEMENT"], "eff"), on="DEPARTEMENT", suffixes=("", "_e"))
    dep = dep[dep["VALUE_e"] >= min_eff].sort_values("VALUE", ascending=False)
    with c1.container(border=True):
        bar_chart(dep.head(10), "DEPARTEMENT", "VALUE", horizontal=True, unit="%",
                  title="Meilleurs départements (taux de réussite)", ref=sc["taux"],
                  ref_label=scope)
    with c2.container(border=True):
        bar_chart(dep.tail(10).sort_values("VALUE"), "DEPARTEMENT", "VALUE", horizontal=True,
                  unit="%", title="Départements les plus en difficulté", sort="asc",
                  ref=sc["taux"], ref_label=scope, colors=[RED])
    etab = metric_table(dd, ["ETABLISSEMENT"], "taux").merge(
        metric_table(dd, ["ETABLISSEMENT"], "moy"), on="ETABLISSEMENT", suffixes=("_t", "_m")).merge(
        metric_table(dd, ["ETABLISSEMENT"], "eff"), on="ETABLISSEMENT")
    etab = etab[etab["VALUE"] >= min_eff]
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        scatter_chart(etab, "VALUE", "VALUE_t", "ETABLISSEMENT", title="Effectif et taux de réussite",
                      subtitle="Un point par établissement", xlabel="Effectif", ylabel="Taux de réussite",
                      yunit="%", decimals=0, ref_y=sc["taux"])
    with c2.container(border=True):
        sd_reg = (d.groupby("REGION", observed=True)["MOYENNE"].std()
                  .rename("VALUE").reset_index())
        bar_chart(sd_reg, "REGION", "VALUE", decimals=2, colors=[PALETTE[4]],
                  title="Écart-type des moyennes par région",
                  subtitle="Hétérogénéité des résultats au sein de chaque région",
                  ref=sd, ref_label="National")


tabs = st.tabs([":material/dashboard: Général"] + [f"{EXAMS[e]['icon']} {e}" for e in exams])
with tabs[0]:
    render_general()
for tab, e in zip(tabs[1:], exams):
    with tab:
        render_exam(e)
