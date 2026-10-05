"""
utils.py - socle commun aux deux applications (app.py et Analyse_matiere.py)

Contenu
-------
1. Configuration (examens, fichiers, coefficients)
2. Import_data() : lecture + traitement, stockage dans st.session_state
3. Calculs (taux de réussite, moyennes ...)
4. Fonctions graphiques réutilisables (streamlit_echarts)
5. Tableaux stylés, filtres en cascade, widgets de sidebar, CSS
"""
from __future__ import annotations

import json
import os
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_echarts import JsCode, st_echarts

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
# Fichier des coefficients : une feuille par examen (BEPC, BEPC bilingue, CAP industriel,
# CAP STT, Industrial CAP, TST CAP), chacune avec les colonnes  Examen | MATIERE | coef.
COEF_FILE = "tableau_matieres_coefficients.xlsx"

# La colonne NOTE est-elle DÉJÀ pondérée (note x coefficient) ?
#   False : NOTE = note /20 brute -> numérateur = somme(NOTE x coef)
#   True  : NOTE = note x coef    -> numérateur = somme(NOTE)
#           (la note /20 d'une matière est alors NOTE / coef)
#
# MOYENNE INDIVIDUELLE = numérateur / somme des coefficients DES MATIÈRES QUE LE CANDIDAT
# A RÉELLEMENT PASSÉES (une ligne avec une note). Un candidat de CAP ne passe que les
# matières de sa série : le dénominateur est donc propre à chaque candidat
# (colonne TOTAL_COEF de la table candidat) et non le total de la feuille de l'examen.
#
# Une note manquante (vide) signifie-t-elle « matière non passée » (False : la matière est
# exclue du calcul) ou « absent / zéro » (True : la matière compte avec 0, coef au dénominateur) ?
NOTE_MANQUANTE_COMPTEE_ZERO = False
NOTE_DEJA_PONDEREE = True

EXAMS = {
    "BEPC": dict(files=["BEPC_partie_1.csv", "BEPC_partie_2.csv", "BEPC_partie_3.csv"],
                 icon=":material/school:"),
    "BEPC BILINGUE": dict(files=["BEPC_BILINGUE.csv"], icon=":material/translate:"),
    "CAP INDUSTRIEL": dict(files=["CAP_INDUSTRIEL.csv"], icon=":material/construction:"),
    "CAP STT": dict(files=["CAP_STT.csv"], icon=":material/business_center:"),
    "INDUSTRIAL CAP": dict(files=["INDUSTRIAL_CAP.csv"],
                           icon=":material/precision_manufacturing:"),
    "TST CAP": dict(files=["TST_CAP.csv"], icon=":material/engineering:"),
}

# Dossiers où chercher les CSV et le fichier des coefficients
DATA_DIRS = [
    Path(os.environ.get("DATA_DIR", "data")),
    Path(__file__).parent / "data",
    Path(__file__).parent,
    Path.cwd(),
]

REQUIRED = ["REGION", "DEPARTEMENT", "ETABLISSEMENT", "ORDRE_ENS", "SERIE",
            "NUM_CANDIDAT", "MATIERE", "NOTE"]
ATTR = ["REGION", "DEPARTEMENT", "ETABLISSEMENT", "ORDRE_ENS", "SERIE"]
CAND_KEYS = ATTR + ["NUM_CANDIDAT"]

# Palette
NAVY, TEAL, AMBER, RED = "#1B3A5C", "#2A9D8F", "#E9A23B", "#C8553D"
PURPLE, SKY, SAGE, ROSE = "#6C5B9E", "#3D8BBF", "#8AB17D", "#B56576"
INK, MUTED, GRID = "#1F2A37", "#6B7280", "#E5E9F0"
PALETTE = [NAVY, TEAL, AMBER, RED, PURPLE, SKY, SAGE, ROSE]
HEAT = ["#D95F4B", "#F3A55C", "#F8E7B0", "#9ED3C6", "#3FA796"]

METRICS = {
    "taux": dict(label="Taux de réussite", unit="%", dec=1),
    "moy_admis": dict(label="Moyenne des admis", unit="", dec=2),
    "moy": dict(label="Moyenne générale", unit="", dec=2),
    "eff": dict(label="Effectif", unit="", dec=0),
}


# =============================================================================
# 2. IMPORT DES DONNÉES
# =============================================================================
def _find_file(fname: str):
    for d in DATA_DIRS:
        p = Path(d) / fname
        if p.exists():
            return p
    low = fname.lower()
    for d in DATA_DIRS:
        if Path(d).is_dir():
            for p in Path(d).glob("*"):
                if p.name.lower() == low:
                    return p
    return None


def _read_csv(path: Path) -> pd.DataFrame:
    last = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                head = f.readline()
            sep = ";" if head.count(";") > head.count(",") else ","
            return pd.read_csv(path, sep=sep, encoding=enc, dtype=str, low_memory=False)
        except UnicodeDecodeError as e:
            last = e
    raise last  # type: ignore[misc]


def _norm(x) -> str:
    """Clé de comparaison : sans accents, majuscules, espaces simplifiés."""
    x = unicodedata.normalize("NFKD", str(x))
    x = "".join(ch for ch in x if not unicodedata.combining(ch))
    return " ".join(x.upper().replace("_", " ").split())


def _load_coefs():
    """Lit tableau_matieres_coefficients.xlsx -> ({examen_norm: {matière_norm: coef}}, notes)."""
    notes = []
    p = _find_file(COEF_FILE)
    if p is None:
        notes.append(f"Fichier introuvable : {COEF_FILE} (coefficients = 1 par défaut)")
        return {}, notes
    try:
        sheets = pd.read_excel(p, sheet_name=None)
    except Exception as e:  # noqa: BLE001
        notes.append(f"{COEF_FILE} : lecture impossible ({e})")
        return {}, notes
    out = {}
    for sh, t in sheets.items():
        t = t.copy()
        t.columns = [_norm(c) for c in t.columns]
        ccoef = next((c for c in t.columns if c.startswith("COEF")), None)
        cmat = next((c for c in t.columns if c.startswith("MATIERE")), None)
        if ccoef is None or cmat is None:
            notes.append(f"Feuille « {sh} » : colonnes MATIERE et coef introuvables")
            continue
        t["_c"] = pd.to_numeric(t[ccoef].astype(str).str.replace(",", ".", regex=False),
                                errors="coerce")
        t = t.dropna(subset=["_c", cmat])
        out[_norm(sh)] = {_norm(m): float(c) for m, c in zip(t[cmat], t["_c"])}
    return out, notes


def _prepare(df: pd.DataFrame, coefs: dict):
    """Nettoyage + moyenne individuelle PONDÉRÉE. Retourne (raw, cand, avertissements)."""
    df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"colonnes manquantes : {', '.join(missing)}")
    for c in ATTR + ["MATIERE"]:
        df[c] = df[c].fillna("NON RENSEIGNÉ").astype(str).str.strip()
    df["ORDRE_ENS"] = df["ORDRE_ENS"].str.upper()
    df["SERIE"] = df["SERIE"].str.upper()
    df["MATIERE"] = df["MATIERE"].str.upper()
    df["NUM_CANDIDAT"] = df["NUM_CANDIDAT"].fillna("").astype(str).str.strip()
    df["NOTE"] = pd.to_numeric(
        df["NOTE"].astype(str).str.replace(",", ".", regex=False), errors="coerce")

    warns = []
    df["_K"] = df["MATIERE"].map(_norm)
    cm = dict(coefs or {})
    if not cm:
        warns.append("aucun coefficient trouvé (1 par défaut)")
    unknown = sorted(set(df.loc[~df["_K"].isin(cm), "MATIERE"].unique()))
    if cm and unknown:
        warns.append("matière(s) absente(s) du fichier des coefficients (coef 1) : "
                     + ", ".join(unknown[:6]) + (" …" if len(unknown) > 6 else ""))
    df["COEF"] = df["_K"].map(cm).fillna(1.0)
    if NOTE_DEJA_PONDEREE:
        df["NOTE20"] = df["NOTE"] / df["COEF"]
        weighted = df["NOTE"]
    else:
        df["NOTE20"] = df["NOTE"]
        weighted = df["NOTE"] * df["COEF"]
    df["CID"] = df.groupby(CAND_KEYS, sort=False).ngroup().astype("int32")
    # Matières réellement passées par le candidat : on ne compte que les lignes notées
    # (sauf si NOTE_MANQUANTE_COMPTEE_ZERO : la note manquante vaut alors 0).
    passed = df["NOTE"].notna() | NOTE_MANQUANTE_COMPTEE_ZERO
    df["_W"] = weighted.fillna(0.0).where(passed, 0.0)
    df["_C"] = df["COEF"].where(passed, 0.0)
    df["_N"] = passed.astype("int8")
    agg = df.groupby("CID", sort=False).agg(W=("_W", "sum"), C=("_C", "sum"), NB=("_N", "sum"))

    cand = df.drop_duplicates("CID")[["CID"] + ATTR].set_index("CID")
    # moyenne individuelle = somme(note x coef) / somme des coef des matières passées
    cand["TOTAL_COEF"] = agg["C"]
    cand["MOYENNE"] = agg["W"] / agg["C"].where(agg["C"] > 0)
    cand["NB_MATIERES"] = agg["NB"]
    cand = cand.reset_index()
    cand = cand[cand["MOYENNE"].notna()].reset_index(drop=True)   # candidats sans aucune note
    raw = df[["CID"] + ATTR + ["MATIERE", "COEF", "NOTE20"]].copy()
    for c in ATTR:
        cand[c] = cand[c].astype("category")
    for c in ATTR + ["MATIERE"]:
        raw[c] = raw[c].astype("category")
    return raw, cand, warns


def Import_data(force: bool = False) -> None:
    """Importe et traite les CSV une seule fois par session (st.session_state).

    Après l'appel, st.session_state contient :
      - "raw"      : {examen: table (candidat, matière, note)}
      - "cand"     : {examen: table candidat avec MOYENNE}
      - "cand_all" : tous les examens empilés (colonne EXAMEN)
    Le BEPC est la fusion de BEPC_partie_1, 2 et 3.
    """
    if st.session_state.get("_data_ready") and not force:
        return
    raw, cand, missing, notes = {}, {}, [], []
    coef_tables, cnotes = _load_coefs()
    notes.extend(cnotes)
    coef_view = {}
    with st.spinner("Importation et préparation des données (une seule fois)…"):
        for name, cfg in EXAMS.items():
            frames = []
            for f in cfg["files"]:
                p = _find_file(f)
                if p is None:
                    missing.append(f)
                    continue
                try:
                    frames.append(_read_csv(p))
                except Exception as e:  # noqa: BLE001
                    notes.append(f"{f} : lecture impossible ({e})")
            if not frames:
                continue
            try:
                cm = coef_tables.get(_norm(name), {})
                if coef_tables and not cm:
                    notes.append(f"{name} : feuille absente du fichier des coefficients")
                r, c, w = _prepare(pd.concat(frames, ignore_index=True), cm)
                coef_view[name] = cm
                notes.extend(f"{name} : {x}" for x in w)
            except Exception as e:  # noqa: BLE001
                notes.append(f"{name} : {e}")
                continue
            raw[name], cand[name] = r, c
            if len(c) and c["MOYENNE"].max() > 20.5:
                notes.append(
                    f"{name} : des moyennes dépassent 20. Vérifiez le fichier des coefficients "
                    f"et NOTE_DEJA_PONDEREE (utils.py).")

        if cand:
            cand_all = pd.concat([c.assign(EXAMEN=n) for n, c in cand.items()],
                                 ignore_index=True)
            for c in ATTR + ["EXAMEN"]:
                cand_all[c] = cand_all[c].astype("category")
        else:
            cand_all = pd.DataFrame()

    st.session_state.update(raw=raw, cand=cand, cand_all=cand_all, coefs=coef_view, _missing=missing,
                            _notes=notes, _data_ver=time.time(), _data_ready=True)


def show_data_notes() -> None:
    for f in st.session_state.get("_missing", []):
        st.sidebar.warning(f"Fichier introuvable : {f}", icon=":material/warning:")
    for n in st.session_state.get("_notes", []):
        st.sidebar.warning(n, icon=":material/warning:")


def sidebar_data_controls() -> None:
    with st.sidebar:
        st.markdown("#### :material/database: Données")
        n = {k: len(v) for k, v in st.session_state["cand"].items()}
        st.caption(" · ".join(f"{k} : {v:,}".replace(",", " ") for k, v in n.items())
                   + " candidats")
        if st.button("Recharger les données", icon=":material/refresh:"):
            Import_data(force=True)
            st.rerun()
    show_data_notes()


def sidebar_thresholds(exams, prefix="seuil", title="Seuils d'admission", icon="tune"):
    st.sidebar.markdown(f"#### :material/{icon}: {title}")
    st.sidebar.caption("Moyenne à partir de laquelle un candidat est admis.")
    return {e: st.sidebar.slider(e, 6.0, 10.0, 10.0, 0.05, format="%.2f",
                                 key=f"{prefix}_{e}") for e in exams}


# =============================================================================
# 3. CALCULS
# =============================================================================
def metric_table(df: pd.DataFrame, by, metric: str) -> pd.DataFrame:
    """df doit contenir MOYENNE et ADMIS (bool). Retourne les colonnes `by` + VALUE."""
    by = [by] if isinstance(by, str) else list(by)
    if metric == "taux":
        s = df.groupby(by, observed=True)["ADMIS"].mean() * 100
    elif metric == "moy_admis":
        s = df[df["ADMIS"]].groupby(by, observed=True)["MOYENNE"].mean()
    elif metric == "moy":
        s = df.groupby(by, observed=True)["MOYENNE"].mean()
    elif metric == "eff":
        s = df.groupby(by, observed=True).size()
    elif metric == "admis":
        s = df.groupby(by, observed=True)["ADMIS"].sum()
    else:
        raise ValueError(metric)
    out = s.rename("VALUE").reset_index()
    for c in by:
        out[c] = out[c].astype(str)
    return out


def ref_value(df: pd.DataFrame, metric: str) -> float:
    if df.empty:
        return np.nan
    if metric == "taux":
        return float(df["ADMIS"].mean() * 100)
    if metric == "moy_admis":
        return float(df.loc[df["ADMIS"], "MOYENNE"].mean())
    if metric == "moy":
        return float(df["MOYENNE"].mean())
    return float(len(df))


def subject_metric(df: pd.DataFrame, by, metric: str, seuil: float) -> pd.DataFrame:
    """df contient NOTE20. metric : moy | taux | std | med | eff | cv."""
    by = [by] if isinstance(by, str) else list(by)
    if metric == "taux":
        s = df.assign(_ok=df["NOTE20"] >= seuil).groupby(by, observed=True)["_ok"].mean() * 100
    else:
        g = df.groupby(by, observed=True)["NOTE20"]
        if metric == "moy":
            s = g.mean()
        elif metric == "std":
            s = g.std()
        elif metric == "med":
            s = g.median()
        elif metric == "eff":
            s = g.size()
        elif metric == "cv":
            s = g.std() / g.mean() * 100
        else:
            raise ValueError(metric)
    out = s.rename("VALUE").reset_index()
    for c in by:
        out[c] = out[c].astype(str)
    return out


@st.cache_data(show_spinner=False, max_entries=600)
def cached_metric(exam, seuil, by, metric, ver, _df):
    d = _df.assign(ADMIS=_df["MOYENNE"] >= seuil)
    return metric_table(d, list(by), metric)


@st.cache_data(show_spinner=False, max_entries=600)
def cached_metric_all(seuils_key, by, metric, ver, _df):
    m = dict(seuils_key)
    thr = _df["EXAMEN"].astype(str).map(m).to_numpy(dtype=float)
    d = _df.assign(ADMIS=_df["MOYENNE"].to_numpy() >= thr)
    return metric_table(d, list(by), metric)


@st.cache_data(show_spinner=False, max_entries=600)
def cached_subject_metric(exam, coefs_key, seuil, by, metric, ver, _df):
    return subject_metric(_df, list(by), metric, seuil)


@st.cache_data(show_spinner=False, max_entries=100)
def cached_box(tag, cat, val, ver, _df):
    return box_stats(_df, cat, val)


@st.cache_data(show_spinner=False, max_entries=100)
def region_map(key, ver, _df):
    p = _df[["REGION", "DEPARTEMENT"]].drop_duplicates()
    out = {}
    for r, g in p.groupby("REGION", observed=True):
        out[str(r)] = sorted(g["DEPARTEMENT"].astype(str).unique())
    return out


def box_stats(df: pd.DataFrame, cat: str, val: str) -> pd.DataFrame:
    g = df.groupby(cat, observed=True)[val]
    out = pd.concat({"p5": g.quantile(0.05), "q1": g.quantile(0.25), "med": g.median(),
                     "q3": g.quantile(0.75), "p95": g.quantile(0.95)}, axis=1)
    out.index = out.index.astype(str)
    return out


def entity_pivot(dd, func, col, index=("ETABLISSEMENT", "ORDRE_ENS"), min_eff=20,
                 top_n=40, desc=True, eff_label="EFFECTIF"):
    """Tableau index × col (valeurs = func(df, by) -> VALUE) + effectif + ensemble."""
    index = list(index)
    tot = func(dd, index).rename(columns={"VALUE": "ENSEMBLE"})
    eff = dd.groupby(index, observed=True).size().rename(eff_label).reset_index()
    for c in index:
        eff[c] = eff[c].astype(str)
    cell = func(dd, index + [col])
    piv = cell.pivot_table(index=index, columns=col, values="VALUE", aggfunc="first")
    piv.columns = [str(c) for c in piv.columns]
    value_cols = list(piv.columns)
    piv = piv.reset_index()
    out = eff.merge(tot, on=index).merge(piv, on=index)
    out = out[out[eff_label] >= min_eff].sort_values("ENSEMBLE", ascending=not desc).head(top_n)
    return out[index + [eff_label] + value_cols + ["ENSEMBLE"]], value_cols + ["ENSEMBLE"]


# =============================================================================
# 4. GRAPHIQUES (streamlit_echarts)
# =============================================================================
def reset_chart_keys() -> None:
    st.session_state["_ck"] = 0


def _key() -> str:
    n = st.session_state.get("_ck", 0) + 1
    st.session_state["_ck"] = n
    return f"ec_{n}"


def show(option: dict, height: int = 380) -> None:
    st_echarts(options=option, height=f"{int(height)}px", key=_key())


def lighten(hex_color: str, f: float = 0.5) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(c + (255 - c) * f) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _grad(col, horizontal=False):
    return {"type": "linear", "x": 0, "y": 0, "x2": 1 if horizontal else 0,
            "y2": 0 if horizontal else 1,
            "colorStops": [{"offset": 0, "color": lighten(col, .45) if horizontal else col},
                           {"offset": 1, "color": col if horizontal else lighten(col, .45)}]}


def _vals(s, dec):
    return [None if pd.isna(x) else round(float(x), dec) for x in s]


def _title(title, subtitle):
    if not title:
        return {}
    return {"text": title, "subtext": subtitle or "", "left": 0, "top": 0, "itemGap": 4,
            "textStyle": {"fontSize": 15, "fontWeight": 600, "color": INK},
            "subtextStyle": {"fontSize": 12, "color": MUTED}}


def _base(title, subtitle):
    return {"backgroundColor": "transparent",
            "textStyle": {"fontFamily": "Inter, sans-serif", "color": INK},
            "title": _title(title, subtitle), "animationDuration": 600}


_TOOLTIP = {"backgroundColor": "rgba(255,255,255,.97)", "borderColor": GRID,
            "textStyle": {"color": INK, "fontSize": 12}}


def _markline(value, label, horizontal, dec, unit):
    if value is None or pd.isna(value):
        return None
    return {"silent": True, "symbol": ["none", "none"],
            "lineStyle": {"type": "dashed", "color": RED, "width": 2},
            "label": {"formatter": f"{label} : {value:.{dec}f}{unit}", "color": RED,
                      "fontWeight": 600, "fontSize": 11,
                      # Barres horizontales : la ligne est verticale. L'axe des valeurs est en
                      # bas et l'axe des catégories est inversé, donc "start" place l'étiquette
                      # en haut du graphique (côté opposé à la graduation), au-dessus des barres.
                      "position": "start" if horizontal else "insideEndTop",
                      "distance": 6 if horizontal else 4},
            "data": [{"xAxis": float(value)} if horizontal else {"yAxis": float(value)}]}


def bar_chart(df, cat, val, group=None, title=None, subtitle=None, ref=None,
              ref_label="National", unit="", decimals=1, horizontal=False, height=380,
              sort="desc", stacked=False, colors=None, label=True, diverging=False):
    """Barres (simples, groupées, empilées) avec étiquettes et ligne de référence."""
    if df is None or len(df) == 0:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    colors = colors or PALETTE
    d = df.copy()
    d[cat] = d[cat].astype(str)
    if group is None:
        if sort:
            d = d.sort_values(val, ascending=(sort == "asc"))
        cats = d[cat].tolist()
        blocks = [("", _vals(d[val], decimals))]
    else:
        d[group] = d[group].astype(str)
        piv = d.pivot_table(index=cat, columns=group, values=val, aggfunc="first")
        if sort:
            piv = piv.loc[piv.mean(axis=1).sort_values(ascending=(sort == "asc")).index]
        cats = [str(c) for c in piv.index]
        blocks = [(str(c), _vals(piv[c], decimals)) for c in piv.columns]

    n_bars = len(cats) * len(blocks)
    rot = 90 if (not horizontal and not stacked and n_bars > 24) else 0
    series = []
    for i, (name, data) in enumerate(blocks):
        col = colors[i % len(colors)]
        if diverging and group is None:
            data = [None if v is None else
                    {"value": v, "itemStyle": {"color": _grad(TEAL if v >= 0 else RED, horizontal)}}
                    for v in data]
        lab = {"show": label, "fontSize": 11, "color": MUTED, "formatter": f"{{c}}{unit}",
               "position": "right" if horizontal else "top"}
        if stacked:
            lab.update(position="inside", color="#fff")
        if rot:
            lab.update(rotate=90, align="left", verticalAlign="middle", distance=6)
        s = {"type": "bar", "name": name, "data": data, "barMaxWidth": 22 if horizontal else 40,
             "itemStyle": {"borderRadius": [0, 4, 4, 0] if horizontal else [4, 4, 0, 0],
                           "color": _grad(col, horizontal)},
             "label": lab, "emphasis": {"focus": "series"}}
        if stacked:
            s["stack"] = "total"
            s["itemStyle"]["borderRadius"] = 0
        series.append(s)
    ml = None if stacked else _markline(ref, ref_label, horizontal, decimals, unit)
    if ml:
        series[0]["markLine"] = ml

    cat_axis = {"type": "category", "data": cats, "axisTick": {"show": False},
                "axisLine": {"lineStyle": {"color": GRID}},
                "axisLabel": {"color": MUTED, "interval": 0, "fontSize": 11,
                              "rotate": 0 if (horizontal or len(cats) <= 7) else 35}}
    val_axis = {"type": "value", "min": 0, "boundaryGap": [0, "14%"],
                "splitLine": {"lineStyle": {"color": "#EEF1F6"}},
                "axisLabel": {"color": MUTED, "formatter": f"{{value}}{unit}"}}
    if diverging:
        val_axis.pop("min")
    legend = {"bottom": 0, "type": "scroll", "icon": "roundRect",
              "textStyle": {"color": MUTED}} if group is not None else None
    opt = _base(title, subtitle)
    opt.update({
        "color": colors,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, **_TOOLTIP},
        "grid": {"left": 8, "right": 56 if horizontal else 24, "top": 70 if title else 36,
                 "bottom": 46 if legend else 8, "containLabel": True},
        "xAxis": val_axis if horizontal else cat_axis,
        "yAxis": ({**cat_axis, "inverse": True} if horizontal else val_axis),
        "series": series})
    if legend:
        opt["legend"] = legend
    h = height
    if horizontal:
        h = max(height, int(len(cats) * (20 + 11 * len(blocks)) + 130))
    show(opt, h)


def heatmap_chart(df, x, y, val, title=None, subtitle=None, unit="", decimals=1,
                  height=None, palette=None, vmin=None, vmax=None, sort_y=True):
    d = df.dropna(subset=[val]).copy() if df is not None else pd.DataFrame()
    if d.empty:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    d[x] = d[x].astype(str)
    d[y] = d[y].astype(str)
    xs = sorted(d[x].unique())
    ys = (list(d.groupby(y)[val].mean().sort_values(ascending=False).index) if sort_y
          else sorted(d[y].unique()))
    xm = {k: i for i, k in enumerate(xs)}
    ym = {k: i for i, k in enumerate(ys)}
    data = [[xm[a], ym[b], round(float(v), decimals)] for a, b, v in zip(d[x], d[y], d[val])]
    lo = float(d[val].min()) if vmin is None else vmin
    hi = float(d[val].max()) if vmax is None else vmax
    if lo == hi:
        hi = lo + 1
    h = height or int(min(950, max(320, 26 * len(ys) + 170)))
    tip = ("function(p){var X=" + json.dumps(xs) + ",Y=" + json.dumps(ys)
           + ";return '<b>'+Y[p.value[1]]+'</b><br/>'+X[p.value[0]]+' : <b>'+p.value[2]+'"
           + unit + "</b>';}")
    opt = _base(title, subtitle)
    opt.update({
        "tooltip": {"position": "top", "formatter": JsCode(tip).js_code, **_TOOLTIP},
        "grid": {"left": 8, "right": 24, "top": 100 if title else 56, "bottom": 56,
                 "containLabel": True},
        "xAxis": {"type": "category", "data": xs, "position": "top",
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": MUTED, "interval": 0, "fontSize": 11,
                                "rotate": 0 if len(xs) <= 7 else 35}},
        "yAxis": {"type": "category", "data": ys, "inverse": True,
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": MUTED, "interval": 0, "fontSize": 11}},
        "visualMap": {"min": lo, "max": hi, "calculable": True, "orient": "horizontal",
                      "left": "center", "bottom": 2, "itemWidth": 14, "itemHeight": 200,
                      "precision": decimals, "textStyle": {"color": MUTED},
                      "inRange": {"color": palette or HEAT}},
        "series": [{"type": "heatmap", "data": data,
                    "label": {"show": len(data) <= 260, "fontSize": 10, "color": INK,
                              "formatter": JsCode("function(p){return p.value[2];}").js_code},
                    "itemStyle": {"borderColor": "#fff", "borderWidth": 2, "borderRadius": 3},
                    "emphasis": {"itemStyle": {"shadowBlur": 8, "shadowColor": "rgba(0,0,0,.25)"}}}]})
    show(opt, h)


def gauge_chart(value, title="Taux de réussite", subtitle=None, height=310, unit="%"):
    """Jauge stylée : arc de progression arrondi + anneau tricolore intérieur."""
    v = 0.0 if value is None or pd.isna(value) else float(value)
    col = RED if v < 40 else AMBER if v < 60 else TEAL
    opt = _base(subtitle, None)
    opt["title"] = {"text": subtitle or "", "left": "center", "top": 0,
                    "textStyle": {"fontSize": 14, "fontWeight": 600, "color": MUTED}}
    common = {"type": "gauge", "startAngle": 215, "endAngle": -35, "min": 0, "max": 100,
              "center": ["50%", "58%"]}
    opt["series"] = [
        {**common, "radius": "92%", "splitNumber": 5,
         "progress": {"show": True, "width": 22, "roundCap": True,
                      "itemStyle": {"color": {"type": "linear", "x": 0, "y": 1, "x2": 1, "y2": 0,
                                              "colorStops": [{"offset": 0, "color": lighten(col, .35)},
                                                             {"offset": 1, "color": col}]}}},
         "axisLine": {"roundCap": True, "lineStyle": {"width": 22, "color": [[1, "#E8EDF4"]]}},
         "pointer": {"show": False}, "axisTick": {"show": False},
         "splitLine": {"show": False},
         "axisLabel": {"distance": 30, "color": MUTED, "fontSize": 10},
         "title": {"show": True, "offsetCenter": [0, "74%"], "fontSize": 13, "color": MUTED},
         "detail": {"valueAnimation": True, "offsetCenter": [0, "22%"], "fontSize": 42,
                    "fontWeight": 700, "color": col, "formatter": "{value}" + unit},
         "data": [{"value": round(v, 1), "name": title}]},
        {**common, "radius": "66%", "silent": True,
         "axisLine": {"lineStyle": {"width": 4, "color": [[.4, lighten(RED, .35)],
                                                         [.6, lighten(AMBER, .35)],
                                                         [1, lighten(TEAL, .35)]]}},
         "pointer": {"show": False}, "axisTick": {"show": False}, "splitLine": {"show": False},
         "axisLabel": {"show": False}, "detail": {"show": False}, "data": [{"value": 0}]},
    ]
    show(opt, height)


def hist_chart(values, threshold=None, title=None, subtitle=None, bin_width=0.5,
               vmax=20.0, height=340, xlabel="Note /20"):
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    edges = np.arange(0, vmax + bin_width, bin_width)
    counts, _ = np.histogram(np.clip(v, 0, vmax), bins=edges)
    labels = [f"{e:.1f}" for e in edges[:-1]]
    data = []
    for c, e in zip(counts, edges[:-1]):
        below = threshold is not None and (e + bin_width) <= threshold + 1e-9
        data.append({"value": int(c), "itemStyle": {
            "color": lighten(RED, .1) if below else TEAL, "borderRadius": [3, 3, 0, 0]}})
    s = {"type": "bar", "data": data, "barCategoryGap": "8%"}
    if threshold is not None:
        s["markLine"] = {"silent": True, "symbol": ["none", "none"],
                         "lineStyle": {"type": "dashed", "color": NAVY, "width": 2},
                         "label": {"formatter": f"Seuil {threshold:.2f}", "color": NAVY,
                                   "fontWeight": 600},
                         "data": [{"xAxis": float(threshold / bin_width - 0.5)}]}
    opt = _base(title, subtitle)
    opt.update({
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, **_TOOLTIP},
        "grid": {"left": 8, "right": 24, "top": 70 if title else 30, "bottom": 28,
                 "containLabel": True},
        "xAxis": {"type": "category", "data": labels, "name": xlabel, "nameLocation": "middle",
                  "nameGap": 28, "nameTextStyle": {"color": MUTED},
                  "axisLabel": {"color": MUTED, "interval": 1}, "axisTick": {"show": False}},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#EEF1F6"}},
                  "axisLabel": {"color": MUTED}},
        "series": [s]})
    show(opt, height)


def boxplot_chart(stats, title=None, subtitle=None, ref=None, ref_label="National",
                  decimals=2, height=400, horizontal=False):
    """stats : sortie de box_stats (p5, q1, med, q3, p95). Moustaches = P5–P95."""
    if stats is None or len(stats) == 0:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    s = stats.dropna().sort_values("med", ascending=False)
    cats = [str(c) for c in s.index]
    data = [[round(float(r.p5), 2), round(float(r.q1), 2), round(float(r.med), 2),
             round(float(r.q3), 2), round(float(r.p95), 2)] for r in s.itertuples()]
    tip = ("function(p){var v=p.value; if(v.length>5){v=v.slice(v.length-5);}"
           "return '<b>'+p.name+'</b><br/>P5 : '+v[0]+'<br/>Q1 : '+v[1]+'<br/>Médiane : '+v[2]"
           "+'<br/>Q3 : '+v[3]+'<br/>P95 : '+v[4];}")
    ser = {"type": "boxplot", "data": data, "boxWidth": [10, 34],
           "itemStyle": {"color": lighten(TEAL, .6), "borderColor": TEAL, "borderWidth": 1.6},
           "emphasis": {"itemStyle": {"borderColor": NAVY}}}
    ml = _markline(ref, ref_label, horizontal, decimals, "")
    if ml:
        ser["markLine"] = ml
    cat_axis = {"type": "category", "data": cats, "axisTick": {"show": False},
                "axisLabel": {"color": MUTED, "interval": 0, "fontSize": 11,
                              "rotate": 0 if horizontal or len(cats) <= 6 else 30}}
    val_axis = {"type": "value", "scale": True,
                "splitLine": {"lineStyle": {"color": "#EEF1F6"}},
                "axisLabel": {"color": MUTED}}
    opt = _base(title, subtitle)
    opt.update({
        "tooltip": {"trigger": "item", "formatter": JsCode(tip).js_code, **_TOOLTIP},
        "grid": {"left": 8, "right": 56 if horizontal else 24, "top": 70 if title else 30,
                 "bottom": 8, "containLabel": True},
        "xAxis": val_axis if horizontal else cat_axis,
        "yAxis": {**cat_axis, "inverse": True} if horizontal else val_axis,
        "series": [ser]})
    h = max(height, len(cats) * 34 + 130) if horizontal else height
    show(opt, h)


def scatter_chart(df, x, y, name, size=None, title=None, subtitle=None, xlabel="", ylabel="",
                  height=420, color=TEAL, ref_x=None, ref_y=None, xunit="", yunit="",
                  decimals=1, show_names=False):
    d = df.dropna(subset=[x, y]).copy() if df is not None else pd.DataFrame()
    if d.empty:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    if size is not None and d[size].max() > d[size].min():
        sz = 9 + 25 * (d[size] - d[size].min()) / (d[size].max() - d[size].min())
    else:
        sz = pd.Series(12, index=d.index)
    data = [{"value": [round(float(a), decimals + 1), round(float(b), decimals + 1),
                       round(float(s), 1)], "name": str(n)}
            for a, b, s, n in zip(d[x], d[y], sz, d[name])]
    tip = ("function(p){return '<b>'+p.name+'</b><br/>" + xlabel + " : '+p.value[0]+'" + xunit
           + "<br/>" + ylabel + " : '+p.value[1]+'" + yunit + "';}")
    lines = []
    if ref_x is not None and not pd.isna(ref_x):
        lines.append({"xAxis": float(ref_x)})
    if ref_y is not None and not pd.isna(ref_y):
        lines.append({"yAxis": float(ref_y)})
    ser = {"type": "scatter", "data": data,
           "symbolSize": JsCode("function(v){return v[2];}").js_code,
           "itemStyle": {"color": lighten(color, .1), "opacity": .75, "borderColor": "#fff",
                         "borderWidth": 1},
           "label": {"show": show_names, "position": "right", "color": MUTED, "fontSize": 11,
                     "formatter": JsCode("function(p){return p.name;}").js_code},
           "emphasis": {"focus": "self", "itemStyle": {"opacity": 1}}}
    if lines:
        ser["markLine"] = {"silent": True, "symbol": ["none", "none"],
                           "lineStyle": {"type": "dashed", "color": RED, "width": 1.6},
                           "label": {"show": False}, "data": lines}
    axis = lambda nm, u: {"type": "value", "scale": True, "name": nm, "nameLocation": "middle",  # noqa: E731
                          "nameGap": 34, "nameTextStyle": {"color": MUTED},
                          "splitLine": {"lineStyle": {"color": "#EEF1F6"}},
                          "axisLabel": {"color": MUTED, "formatter": "{value}" + u}}
    opt = _base(title, subtitle)
    opt.update({
        "tooltip": {"trigger": "item", "formatter": JsCode(tip).js_code, **_TOOLTIP},
        "grid": {"left": 8, "right": 24, "top": 70 if title else 30, "bottom": 36,
                 "containLabel": True},
        "xAxis": axis(xlabel, xunit), "yAxis": axis(ylabel, yunit), "series": [ser]})
    show(opt, height)


# =============================================================================
# 5. TABLEAUX STYLÉS, FILTRES, CSS
# =============================================================================
def bar_table(df, value_cols, fmt="{:.1f}", color=TEAL, vmin=0.0, vmax=None, height=480,
              int_cols=()):
    """Tableau HTML stylé avec barres de valeur dans les cellules."""
    if df is None or df.empty:
        st.info("Aucune donnée à afficher.", icon=":material/info:")
        return
    formats = {c: fmt for c in value_cols}
    formats.update({c: "{:,.0f}" for c in int_cols})
    sty = (df.style.hide(axis="index").format(formats, na_rep="–")
           .bar(subset=value_cols, color=lighten(color, .4), vmin=vmin, vmax=vmax,
                align="left")
           .set_table_attributes('class="dtable"'))
    html = sty.to_html()
    html = "\n".join(l.strip() for l in html.splitlines() if l.strip())
    st.markdown(f'<div class="dtable-wrap" style="max-height:{height}px">{html}</div>',
                unsafe_allow_html=True)


def cascade_filters(df, key, ver, map_df=None):
    """Région -> départements (le multiselect ne propose que ceux de la région)."""
    rmap = region_map(key, ver, df if map_df is None else map_df)
    c1, c2 = st.columns(2)
    all_lbl = "Toutes les régions"
    reg = c1.selectbox("Région", [all_lbl] + sorted(rmap), key=f"{key}_reg")
    deps = sorted({x for v in rmap.values() for x in v}) if reg == all_lbl else rmap[reg]
    k = f"{key}_dep"
    if k in st.session_state:
        st.session_state[k] = [x for x in st.session_state[k] if x in deps]
    sel = c2.multiselect("Départements", deps, key=k,
                         placeholder="Tous les départements" +
                         ("" if reg == all_lbl else " de la région"))
    out = df
    if reg != all_lbl:
        out = out[out["REGION"] == reg]
    if sel:
        out = out[out["DEPARTEMENT"].isin(sel)]
    if sel:
        scope = sel[0] if len(sel) == 1 else f"{len(sel)} départements"
    elif reg != all_lbl:
        scope = reg
    else:
        scope = "National"
    return out, scope


def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def section(icon, title, desc=None):
    st.markdown(f"### :material/{icon}: {title}")
    if desc:
        st.caption(desc)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
.stApp, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp label,
.stApp button, .stApp [data-baseweb] { font-family: 'Inter', sans-serif; }
.stApp { background: #F6F8FB; }
.block-container { padding-top: 1.4rem; max-width: 1560px; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E5E9F0; }
[data-testid="stMetric"] { background: #fff; border: 1px solid #E5E9F0; border-left: 4px solid #1B3A5C;
  border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 2px rgba(16,24,40,.05); }
[data-testid="stMetricLabel"] p { font-weight: 600; color: #6B7280; font-size: .78rem;
  text-transform: uppercase; letter-spacing: .04em; }
[data-testid="stMetricValue"] { font-weight: 700; color: #1B3A5C; }
[data-testid="stVerticalBlockBorderWrapper"] { background: #fff; border-radius: 12px; }
button[data-baseweb="tab"] { font-weight: 600; }
h3 { color: #1B3A5C; font-weight: 700; letter-spacing: -.01em; margin-top: .6rem; }
.hero { background: linear-gradient(120deg, #1B3A5C 0%, #24607A 55%, #2A9D8F 100%);
  border-radius: 14px; padding: 22px 28px; margin-bottom: 14px; color: #fff;
  box-shadow: 0 6px 18px rgba(27,58,92,.18); }
.hero-title { font-size: 1.55rem; font-weight: 700; letter-spacing: -.01em; }
.hero-sub { font-size: .92rem; opacity: .85; margin-top: 4px; }
.dtable-wrap { overflow: auto; border: 1px solid #E5E9F0; border-radius: 10px; background: #fff; }
.dtable { border-collapse: collapse; width: 100%; font-size: .82rem; }
.dtable th { position: sticky; top: 0; z-index: 1; background: #1B3A5C; color: #fff; font-weight: 600;
  padding: 8px 10px; text-align: left; white-space: nowrap; }
.dtable td { padding: 6px 10px; border-bottom: 1px solid #EEF1F6; color: #1F2A37; white-space: nowrap; }
.dtable tr:hover td { filter: brightness(.97); }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><div class="hero-title">{title}</div>'
                f'<div class="hero-sub">{subtitle}</div></div>', unsafe_allow_html=True)
