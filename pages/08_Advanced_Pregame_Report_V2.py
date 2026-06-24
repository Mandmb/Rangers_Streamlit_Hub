# =============================================================
# 08_Advanced_Pregame_Report_V2.py
# Advanced Pregame Report - visual PDF version
# =============================================================

import io
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="Advanced Pregame Report V2", layout="wide")

NAVY = colors.HexColor("#002D72")
RED = colors.HexColor("#BA0C2F")
DARK = colors.HexColor("#172033")
LIGHT_BG = colors.HexColor("#F5F7FA")
BORDER = colors.HexColor("#D2D8E2")
GREEN_BG = colors.HexColor("#E6F4EA")
GREEN_TXT = colors.HexColor("#137333")
RED_BG = colors.HexColor("#FCE8E6")
RED_TXT = colors.HexColor("#B3261E")
MUTED = colors.HexColor("#5F6B7A")

PITCH_COLORS = {
    "FA": colors.HexColor("#D7263D"),
    "FF": colors.HexColor("#D7263D"),
    "Fastball": colors.HexColor("#D7263D"),
    "4-Seam Fastball": colors.HexColor("#D7263D"),
    "Four-Seam Fastball": colors.HexColor("#D7263D"),
    "SI": colors.HexColor("#FF9F1C"),
    "Sinker": colors.HexColor("#FF9F1C"),
    "FC": colors.HexColor("#48A868"),
    "Cutter": colors.HexColor("#48A868"),
    "CH": colors.HexColor("#2878D7"),
    "Changeup": colors.HexColor("#2878D7"),
    "SL": colors.HexColor("#2E86DE"),
    "Slider": colors.HexColor("#2E86DE"),
    "CU": colors.HexColor("#6F42C1"),
    "Curveball": colors.HexColor("#6F42C1"),
    "CB": colors.HexColor("#6F42C1"),
    "FS": colors.HexColor("#00A6A6"),
    "Splitter": colors.HexColor("#00A6A6"),
    "Sweeper": colors.HexColor("#8E44AD"),
}
COUNTS = ["0-0", "1-0", "2-0", "3-0", "0-1", "1-1", "2-1", "3-1", "0-2", "1-2", "2-2", "3-2"]

# ----------------------------
# Helpers
# ----------------------------
def clean_columns(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def read_csv(uploaded):
    if uploaded is None:
        return None
    return clean_columns(pd.read_csv(uploaded))

def pct_to_float(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip().replace("%", "")
    if s in ["", "-", "nan", "None"]:
        return np.nan
    try:
        return float(s) / 100.0 if "%" in str(x) else float(s)
    except Exception:
        return np.nan

def num(x):
    if pd.isna(x):
        return 0.0
    s = str(x).strip().replace("%", "").replace(",", "")
    if s in ["", "-", "nan", "None"]:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def fmt_pct(v, digits=1):
    try:
        if pd.isna(v):
            return "-"
        return f"{v*100:.{digits}f}%"
    except Exception:
        return "-"

def fmt_dec(v):
    try:
        if pd.isna(v): return ".000"
        return f"{v:.3f}".replace("0.", ".")
    except Exception:
        return ".000"

def first_existing(df, names):
    if df is None:
        return None
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    return None

def safe_div(a, b):
    return float(a) / float(b) if b else 0.0

def is_swing_result(val):
    s = str(val).lower()
    # User definition: ball or called strike = take. Anything else = swing.
    take_tokens = ["ball", "strike looking", "called strike", "strike called"]
    if s.strip() in ["ball", "ball in the dirt"]:
        return False
    if "strike looking" in s or "called strike" in s or "strike called" in s:
        return False
    return True

def final_pitch_rows(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    sort_cols = [c for c in ["gameId", "abNumInGame", "pitchNumInAB", "pitchNumInGame"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols)
    group_cols = [c for c in ["gameId", "abNumInGame"] if c in df.columns]
    if len(group_cols) >= 2:
        return df.groupby(group_cols, as_index=False).tail(1)
    return df

def classify_result(result):
    s = str(result).lower()
    h = 0; tb = 0; ab = 1; bb = 0; k = 0; hbp = 0
    if "walk" in s:
        ab = 0; bb = 1
    elif "hit by pitch" in s:
        ab = 0; hbp = 1
    elif "sac" in s or "catcher interference" in s:
        ab = 0
    elif "strikeout" in s:
        k = 1
    if "home run" in s:
        h = 1; tb = 4
    elif "triple" in s:
        h = 1; tb = 3
    elif "double" in s and "double play" not in s:
        h = 1; tb = 2
    elif "single" in s:
        h = 1; tb = 1
    return ab, h, tb, bb, k, hbp

def hitter_stats(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["Player","PA","AB","H","BB","K","AVG","OBP","SLG","OPS","BB%","K%"])
    player_col = first_existing(df, ["batter", "batterAbbrevName", "playerFullName", "batterFullName"])
    result_col = first_existing(df, ["pitchResult", "playResult", "result", "pitchOutcome"])
    last = final_pitch_rows(df)
    if player_col is None or result_col is None or last.empty:
        return pd.DataFrame(columns=["Player","PA","AB","H","BB","K","AVG","OBP","SLG","OPS","BB%","K%"])
    rows = []
    for _, r in last.iterrows():
        ab, h, tb, bb, k, hbp = classify_result(r.get(result_col, ""))
        rows.append({"Player": str(r.get(player_col, "Unknown")), "PA": 1, "AB": ab, "H": h, "TB": tb, "BB": bb, "K": k, "HBP": hbp})
    out = pd.DataFrame(rows).groupby("Player", as_index=False).sum(numeric_only=True)
    out["AVG"] = out.apply(lambda r: safe_div(r.H, r.AB), axis=1)
    out["OBP"] = out.apply(lambda r: safe_div(r.H + r.BB + r.HBP, r.AB + r.BB + r.HBP), axis=1)
    out["SLG"] = out.apply(lambda r: safe_div(r.TB, r.AB), axis=1)
    out["OPS"] = out["OBP"] + out["SLG"]
    out["BB%"] = out.apply(lambda r: safe_div(r.BB, r.PA), axis=1)
    out["K%"] = out.apply(lambda r: safe_div(r.K, r.PA), axis=1)
    return out[["Player","PA","AB","H","BB","K","AVG","OBP","SLG","OPS","BB%","K%"]].sort_values("PA", ascending=False)

def pitcher_stats(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["Pitcher","PA","BB","K","BB%","K%"])
    pitcher_col = first_existing(df, ["pitcher", "pitcherAbbrevName", "pitcherFullName"])
    result_col = first_existing(df, ["pitchResult", "playResult", "result", "pitchOutcome"])
    last = final_pitch_rows(df)
    if pitcher_col is None or result_col is None or last.empty:
        return pd.DataFrame(columns=["Pitcher","PA","BB","K","BB%","K%"])
    rows=[]
    for _, r in last.iterrows():
        s=str(r.get(result_col,"" )).lower()
        rows.append({"Pitcher": str(r.get(pitcher_col, "Unknown")), "PA":1, "BB": int("walk" in s), "K": int("strikeout" in s)})
    out=pd.DataFrame(rows).groupby("Pitcher", as_index=False).sum(numeric_only=True)
    out["BB%"] = out.apply(lambda r: safe_div(r.BB, r.PA), axis=1)
    out["K%"] = out.apply(lambda r: safe_div(r.K, r.PA), axis=1)
    return out.sort_values("PA", ascending=False)

def pitch_usage_by_count(df):
    if df is None or df.empty:
        return pd.DataFrame()
    count_col = first_existing(df, ["count", "Count"])
    type_col = first_existing(df, ["PitchType", "pitchTypeFull", "pitchType", "type"])
    if count_col is None or type_col is None:
        return pd.DataFrame()
    d = df[[count_col, type_col]].copy()
    d.columns=["Count", "Pitch"]
    d = d.dropna()
    d["Pitch"] = d["Pitch"].astype(str).str.strip()
    d = d[~d["Pitch"].str.upper().isin(["UN", "UNKNOWN", "NAN", "-"])]
    tab = pd.crosstab(d["Count"], d["Pitch"], normalize="index")
    tab = tab.reindex([c for c in COUNTS if c in tab.index])
    return tab.fillna(0)

def pitch_usage_overall(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["Pitch Type","Usage %"])
    type_col = first_existing(df, ["PitchType", "pitchTypeFull", "pitchType", "type"])
    if type_col is None:
        return pd.DataFrame(columns=["Pitch Type","Usage %"])
    d = df[type_col].dropna().astype(str).str.strip()
    d = d[~d.str.upper().isin(["UN", "UNKNOWN", "NAN", "-"])]
    vc = d.value_counts(normalize=True).reset_index()
    vc.columns = ["Pitch Type", "Usage %"]
    return vc

def pitcher_usage_table(df):
    if df is None or df.empty:
        return pd.DataFrame()
    pitcher_col = first_existing(df, ["pitcher", "pitcherAbbrevName", "pitcherFullName"])
    type_col = first_existing(df, ["PitchType", "pitchTypeFull", "pitchType", "type"])
    if pitcher_col is None or type_col is None:
        return pd.DataFrame()
    d = df[[pitcher_col, type_col]].copy(); d.columns=["Pitcher","Pitch"]
    d["Pitch"] = d["Pitch"].astype(str).str.strip()
    d = d[~d["Pitch"].str.upper().isin(["UN", "UNKNOWN", "NAN", "-"])]
    counts = d.groupby("Pitcher").size().rename("Pitches")
    tab = pd.crosstab(d["Pitcher"], d["Pitch"], normalize="index")
    out = tab.mul(100).round(1).reset_index().merge(counts.reset_index(), on="Pitcher")
    cols = ["Pitcher", "Pitches"] + [c for c in out.columns if c not in ["Pitcher", "Pitches"]]
    return out[cols].sort_values("Pitches", ascending=False)

def swing_take_by_count(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["Count","Pitches","Swing%","Take%"])
    count_col=first_existing(df,["count","Count"]); res_col=first_existing(df,["pitchResult","pitchOutcome"])
    if count_col is None or res_col is None:
        return pd.DataFrame(columns=["Count","Pitches","Swing%","Take%"])
    d=df[[count_col,res_col]].copy(); d.columns=["Count","Result"]
    d=d.dropna(subset=["Count"])
    d["Swing"] = d["Result"].apply(is_swing_result)
    out=d.groupby("Count").agg(Pitches=("Swing","size"), Swing=("Swing","sum")).reset_index()
    out["Swing%"] = out["Swing"] / out["Pitches"]
    out["Take%"] = 1 - out["Swing%"]
    out = out[out["Count"].astype(str).isin(COUNTS)]
    out["Count"] = pd.Categorical(out["Count"], categories=COUNTS, ordered=True)
    return out.sort_values("Count")[["Count","Pitches","Swing%","Take%"]]

def hitter_swing_table(df):
    if df is None or df.empty:
        return pd.DataFrame()
    player_col=first_existing(df,["batter","batterAbbrevName","playerFullName"]); count_col=first_existing(df,["count","Count"]); res_col=first_existing(df,["pitchResult","pitchOutcome"])
    if None in [player_col,count_col,res_col]: return pd.DataFrame()
    d=df[[player_col,count_col,res_col]].copy(); d.columns=["Hitter","Count","Result"]
    d=d[d["Count"].astype(str).isin(COUNTS)]
    d["Swing"]=d["Result"].apply(is_swing_result)
    counts=d.groupby("Hitter").size().rename("Pitches")
    tab=pd.crosstab(d["Hitter"], d["Count"], values=d["Swing"], aggfunc="mean").fillna(0)
    tab=tab.reindex(columns=COUNTS, fill_value=0)
    out=tab.reset_index().merge(counts.reset_index(), on="Hitter")
    return out[["Hitter","Pitches"]+COUNTS].sort_values("Pitches", ascending=False)

def catcher_table(df):
    if df is None or df.empty or "BaseStealAtt" not in df.columns:
        return pd.DataFrame(columns=["Catcher","SBA","CS","SB","CS%"])
    catcher_col=first_existing(df,["catcher","Catcher","catcherAbbrevName"])
    outs_col=first_existing(df,["outs"])
    if catcher_col is None or outs_col is None:
        return pd.DataFrame(columns=["Catcher","SBA","CS","SB","CS%"])
    d=df.copy().sort_values([c for c in ["gameId","pitchNumInGame"] if c in df.columns])
    d["NextOuts"] = d.groupby("gameId")[outs_col].shift(-1) if "gameId" in d.columns else d[outs_col].shift(-1)
    sba_mask=d["BaseStealAtt"].notna() & (d["BaseStealAtt"].astype(str).str.strip()!="")
    x=d[sba_mask].copy()
    if x.empty: return pd.DataFrame(columns=["Catcher","SBA","CS","SB","CS%"])
    x["CS"]=(pd.to_numeric(x["NextOuts"],errors="coerce") > pd.to_numeric(x[outs_col],errors="coerce")).astype(int)
    x["SB"]=1-x["CS"]
    out=x.groupby(catcher_col).agg(SBA=("CS","size"), CS=("CS","sum"), SB=("SB","sum")).reset_index().rename(columns={catcher_col:"Catcher"})
    out["CS%"] = out.apply(lambda r: safe_div(r.CS, r.SBA), axis=1)
    return out.sort_values("SBA", ascending=False)

def sba_team_count(stolen_df, sba_count_df):
    if sba_count_df is not None and not sba_count_df.empty:
        total = sba_count_df[sba_count_df.iloc[:,0].astype(str).str.upper()=="TOTAL"]
        if not total.empty:
            row=total.iloc[0]
            data=[]
            for c in COUNTS:
                col=f"SBA{c}"
                if col in sba_count_df.columns:
                    data.append({"Count":c,"SBA":num(row[col])})
            if data: return pd.DataFrame(data)
    if stolen_df is not None and "Count" in stolen_df.columns and "SBA" in stolen_df.columns:
        d=stolen_df[["Count","SBA"]].copy()
        d=d[d["Count"].astype(str).isin(COUNTS)]
        return d
    return pd.DataFrame(columns=["Count","SBA"])

def runner_tendencies(sba_count_df):
    if sba_count_df is None or sba_count_df.empty:
        return pd.DataFrame()
    d=sba_count_df.copy()
    if "playerFullName" in d.columns:
        d=d[~d["playerFullName"].astype(str).str.lower().isin(["nan","playerfullname"])]
    if "playerId" in d.columns:
        d=d[~d["playerId"].astype(str).str.upper().isin(["TOTAL","PLAYERID"])]
    if "playerFullName" not in d.columns: return pd.DataFrame()
    cols=["playerFullName","SBA","SB","SB%"] + [f"SBA{c}" for c in COUNTS if f"SBA{c}" in d.columns]
    out=d[[c for c in cols if c in d.columns]].copy()
    out["SBA"] = out["SBA"].apply(num) if "SBA" in out.columns else 0
    out["SB"] = out["SB"].apply(num) if "SB" in out.columns else 0
    if "SB%" in out.columns:
        out["SB%"] = out["SB%"].apply(pct_to_float)
    else:
        out["SB%"] = out.apply(lambda r: safe_div(r.get("SB",0), r.get("SBA",0)), axis=1)
    for c in [f"SBA{x}" for x in COUNTS if f"SBA{x}" in out.columns]: out[c]=out[c].apply(num)
    return out.sort_values("SBA", ascending=False)

def league_hitting_avgs(df):
    base={"AVG":np.nan,"OBP":np.nan,"SLG":np.nan,"OPS":np.nan,"BB%":np.nan,"K%":np.nan}
    if df is None or df.empty: return base
    row=df[df.iloc[:,0].astype(str).str.upper()=="TOTAL"].head(1)
    if row.empty: row=df.head(1)
    r=row.iloc[0]
    for k in base:
        if k in df.columns:
            base[k]=pct_to_float(r[k]) if "%" in k else num(r[k])
    return base

def league_pitching_avgs(df):
    base={"BB%":np.nan,"K%":np.nan,"ERA":np.nan,"WHIP":np.nan,"BA":np.nan,"OPS":np.nan}
    if df is None or df.empty: return base
    row=df[df.iloc[:,0].astype(str).str.upper()=="TOTAL"].head(1)
    if row.empty: row=df.head(1)
    r=row.iloc[0]
    for k in base:
        if k in df.columns:
            base[k]=pct_to_float(r[k]) if "%" in k else num(r[k])
    return base

# ----------------------------
# File detection
# ----------------------------
def detect_files(files):
    detected = {"pregame":None,"standard":None,"catching":None,"stolen":None,"sba_count":None,"lg_hitting":None,"lg_pitching":None}
    for f in files or []:
        name = f.name.lower()
        if "pregame hitting" in name:
            detected["lg_hitting"] = f
        elif name == "rate.csv" or " rate" in name:
            detected["lg_pitching"] = f
        elif "sba count" in name:
            detected["sba_count"] = f
        elif "stolen" in name:
            detected["stolen"] = f
        elif "catching" in name and "pregame" in name:
            detected["catching"] = f
        elif "standard" in name:
            detected["standard"] = f
        elif "pregame" in name:
            detected["pregame"] = f
    return detected

# ----------------------------
# PDF drawing helpers
# ----------------------------
def rr(c, x, y, w, h, r=8, stroke=1, fill=0):
    c.roundRect(x, y, w, h, r, stroke=stroke, fill=fill)

def draw_text(c, text, x, y, size=10, color=colors.black, font="Helvetica", max_width=None, leading=12):
    c.setFillColor(color); c.setFont(font, size)
    text = str(text)
    if max_width is None:
        c.drawString(x,y,text); return
    words=text.split(); line=""; yy=y
    for word in words:
        test=(line+" "+word).strip()
        if c.stringWidth(test,font,size) <= max_width:
            line=test
        else:
            c.drawString(x,yy,line); yy-=leading; line=word
    if line: c.drawString(x,yy,line)

def draw_center(c, text, x, y, w, size=10, color=colors.black, font="Helvetica-Bold"):
    c.setFillColor(color); c.setFont(font, size)
    c.drawCentredString(x+w/2, y, str(text))

def draw_logo(c, x, y, logo_bytes=None):
    if logo_bytes:
        try:
            img=ImageReader(io.BytesIO(logo_bytes))
            c.drawImage(img,x,y,62,62,mask='auto',preserveAspectRatio=True,anchor='c')
            return
        except Exception:
            pass
    # fallback badge
    c.setFillColor(RED); c.circle(x+31,y+31,31,stroke=0,fill=1)
    c.setFillColor(NAVY); c.circle(x+31,y+31,24,stroke=0,fill=1)
    c.setFillColor(colors.white); c.circle(x+31,y+31,17,stroke=0,fill=1)
    draw_center(c,"T",x+14,y+17,34,28,RED,"Helvetica-Bold")

def header(c, opponent, date_text, logo_bytes=None, page=1):
    W,H=landscape(letter)
    draw_logo(c, 28, H-78, logo_bytes)
    draw_text(c,"ADVANCED PREGAME REPORT",110,H-42,32,NAVY,"Helvetica-Bold")
    draw_text(c,f"VS. {opponent.upper()}",112,H-68,15,RED,"Helvetica-Bold")
    draw_text(c,date_text,W-150,H-42,10,NAVY,"Helvetica-Bold")
    c.setStrokeColor(RED); c.setLineWidth(2); c.line(24,H-88,W-24,H-88)
    draw_text(c,f"PAGE {page}",W-65,20,8,NAVY,"Helvetica-Bold")

def section_bar(c, title, x, y, w, h=24):
    c.setFillColor(NAVY); rr(c,x,y,w,h,5,0,1)
    draw_text(c,title,x+12,y+7,14,colors.white,"Helvetica-Bold")

def metric_card(c, x, y, w, h, title, value, lg_value=None, better=True, lower_is_better=False):
    c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,x,y,w,h,7,1,1)
    draw_center(c,title,x,y+h-18,w,9,NAVY,"Helvetica-Bold")
    draw_center(c,value,x,y+h-44,w,20,NAVY,"Helvetica-Bold")
    if lg_value is not None:
        draw_center(c,f"LG AVG  {lg_value}",x,y+31,w,8,DARK,"Helvetica-Bold")
    label = "BETTER" if better else "BELOW AVG"
    bg = GREEN_BG if better else RED_BG
    fg = GREEN_TXT if better else RED_TXT
    c.setFillColor(bg); c.setStrokeColor(colors.HexColor("#C9E7D0") if better else colors.HexColor("#F4C7C3")); rr(c,x+w*0.18,y+8,w*0.64,17,4,1,1)
    draw_center(c,("▲ " if better and not lower_is_better else "▼ " if better else "▼ ")+label,x+w*0.18,y+13,w*0.64,8,fg,"Helvetica-Bold")

def insight_box(c,x,y,w,h,title,body,accent=NAVY):
    c.setFillColor(colors.HexColor("#F8FBFF")); c.setStrokeColor(colors.HexColor("#B8C7DA")); rr(c,x,y,w,h,8,1,1)
    c.setFillColor(colors.white); c.setStrokeColor(accent); c.circle(x+35,y+h-43,20,stroke=1,fill=0)
    c.setStrokeColor(accent); c.setLineWidth(2); c.line(x+35,y+h-68,x+35,y+h-18); c.line(x+10,y+h-43,x+60,y+h-43)
    c.circle(x+35,y+h-43,6,stroke=1,fill=0)
    draw_text(c,title,x+76,y+h-28,10,accent,"Helvetica-Bold")
    draw_text(c,body,x+76,y+h-47,10,DARK,"Helvetica-Bold",max_width=w-90,leading=14)

def small_table(c, df, x, y, w, h, title, cols=None, max_rows=6, font_size=7):
    c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,x,y,w,h,6,1,1)
    draw_center(c,title,x,y+h-16,w,9,NAVY,"Helvetica-Bold")
    if df is None or df.empty:
        draw_center(c,"No data",x,y+h/2,w,9,MUTED,"Helvetica")
        return
    d=df.copy().head(max_rows)
    if cols:
        d=d[[col for col in cols if col in d.columns]]
    cols=list(d.columns)
    top=y+h-30
    row_h=(h-38)/(len(d)+1)
    col_w=w/len(cols)
    c.setFillColor(colors.HexColor("#F1F3F6")); c.rect(x+4,top-row_h,w-8,row_h,stroke=0,fill=1)
    for i,col in enumerate(cols):
        draw_center(c,col,x+i*col_w,top-row_h+row_h*0.32,col_w,6,NAVY,"Helvetica-Bold")
    for r_idx,(_,row) in enumerate(d.iterrows()):
        yy=top-row_h*(r_idx+2)
        if r_idx%2==1:
            c.setFillColor(colors.HexColor("#FAFBFC")); c.rect(x+4,yy,w-8,row_h,stroke=0,fill=1)
        for i,col in enumerate(cols):
            val=row[col]
            if isinstance(val,float):
                if "%" in str(col): val=fmt_pct(val)
                elif col in ["AVG","OBP","SLG","OPS","BA"]: val=fmt_dec(val)
                else: val=f"{val:.1f}"
            draw_center(c,str(val)[:22],x+i*col_w,yy+row_h*0.32,col_w,font_size,DARK,"Helvetica")

def bar_chart(c, data, x, y, w, h, title, value_col, label_col="Count", pct=False):
    c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,x,y,w,h,6,1,1)
    draw_center(c,title,x,y+h-16,w,9,NAVY,"Helvetica-Bold")
    if data is None or data.empty or value_col not in data.columns:
        draw_center(c,"No data",x,y+h/2,w,9,MUTED,"Helvetica")
        return
    d=data.copy().head(12)
    vals=d[value_col].astype(float).fillna(0)
    maxv=max(vals.max(),1 if not pct else 1)
    row_h=(h-36)/len(d)
    for i,(_,r) in enumerate(d.iterrows()):
        yy=y+h-34-(i+1)*row_h+4
        lab=str(r[label_col])
        v=float(r[value_col])
        draw_text(c,lab,x+10,yy+2,7,DARK,"Helvetica")
        bx=x+42; bw=(w-95)*(v/maxv)
        c.setFillColor(NAVY); c.rect(bx,yy,bw,7,stroke=0,fill=1)
        txt=fmt_pct(v) if pct else str(int(v))
        draw_text(c,txt,bx+bw+4,yy,7,DARK,"Helvetica")

def stacked_pitch_chart(c, tab, x, y, w, h, title):
    c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,x,y,w,h,6,1,1)
    draw_center(c,title,x,y+h-16,w,9,NAVY,"Helvetica-Bold")
    if tab is None or tab.empty:
        draw_center(c,"No data",x,y+h/2,w,9,MUTED,"Helvetica")
        return
    d=tab.copy().head(12)
    pitches=list(d.columns)[:7]
    row_h=(h-48)/len(d)
    for i,(count,row) in enumerate(d.iterrows()):
        yy=y+h-35-(i+1)*row_h+5
        draw_text(c,str(count),x+10,yy+1,7,DARK,"Helvetica")
        start=x+42; full=w-70
        cursor=start
        for p in pitches:
            val=float(row[p]) if p in row else 0
            seg=full*val
            c.setFillColor(PITCH_COLORS.get(str(p), colors.grey))
            c.rect(cursor,yy,seg,8,stroke=0,fill=1)
            cursor+=seg
    # legend
    lx=x+42; ly=y+12
    for p in pitches[:6]:
        c.setFillColor(PITCH_COLORS.get(str(p), colors.grey)); c.circle(lx,ly+3,3,stroke=0,fill=1)
        draw_text(c,str(p),lx+8,ly,6,DARK,"Helvetica-Bold")
        lx += 58

def pitch_usage_vs_league_table(opp_usage, xleague=None):
    d=opp_usage.copy() if opp_usage is not None else pd.DataFrame()
    if d.empty: return d
    d["LG AVG"] = np.nan
    d["DIFF"] = np.nan
    return d.head(8)

def make_insights(pitch_usage, swing_count, sba_count, hitters, pitchers):
    insights={}
    if pitch_usage is not None and not pitch_usage.empty:
        overall=pitch_usage.iloc[0]
        insights["pitching"] = f"Highest overall pitch usage is {overall['Pitch Type']} at {fmt_pct(overall['Usage %'])}. Be ready for their primary pitch in leverage counts."
    else: insights["pitching"] = "Attack plan should focus on count leverage and forcing their staff into the zone."
    if swing_count is not None and not swing_count.empty:
        row=swing_count.sort_values("Swing%",ascending=False).iloc[0]
        insights["hitting"] = f"They swing most in {row['Count']} counts ({fmt_pct(row['Swing%'])}). Use that count to expand or change speeds."
    else: insights["hitting"] = "Use count tendencies to decide when to challenge and when to expand."
    if sba_count is not None and not sba_count.empty:
        row=sba_count.sort_values("SBA",ascending=False).iloc[0]
        insights["running"] = f"Running game is most active in {row['Count']} counts with {int(row['SBA'])} attempts. Control tempo there."
    else: insights["running"] = "Prioritize quick times, good holds, and controlling the running game."
    if hitters is not None and not hitters.empty:
        top=hitters.sort_values("OPS",ascending=False).iloc[0]
        insights["matchups"] = f"Circle {top['Player']} as a primary bat. They lead this file in OPS at {fmt_dec(top['OPS'])}."
    else: insights["matchups"] = "Identify the bats that can change the game and avoid mistakes in their damage zones."
    return insights

# ----------------------------
# PDF builder
# ----------------------------
def build_visual_pdf(opponent, date_text, logo_bytes, data):
    buf=io.BytesIO()
    c=canvas.Canvas(buf, pagesize=landscape(letter))
    W,H=landscape(letter)
    margin=24
    insights=make_insights(data['pitch_usage_overall'],data['swing_count'],data['sba_count'],data['hitters'],data['pitchers'])

    # Page 1
    header(c,opponent,date_text,logo_bytes,1)
    section_bar(c,"EXECUTIVE SUMMARY",margin,H-122,W-2*margin,24)
    card_y=H-245; card_w=142; gap=10
    hs=data['team_hitting']; ps=data['team_pitching']; cs=data['team_catching']; bs=data['team_running']
    metric_card(c,margin,card_y,card_w,92,"TEAM HITTING",fmt_dec(hs.get('AVG',0)),fmt_dec(data['lg_hit'].get('AVG',np.nan)),hs.get('AVG',0)>=data['lg_hit'].get('AVG',0))
    metric_card(c,margin+(card_w+gap),card_y,card_w,92,"TEAM PITCHING",fmt_pct(ps.get('BB%',0)),fmt_pct(data['lg_pitch'].get('BB%',np.nan)),ps.get('BB%',0)<=data['lg_pitch'].get('BB%',1),lower_is_better=True)
    metric_card(c,margin+2*(card_w+gap),card_y,card_w,92,"TEAM BASERUNNING",fmt_pct(bs.get('SB%',0)),"",True)
    metric_card(c,margin+3*(card_w+gap),card_y,card_w,92,"TEAM CATCHING",fmt_pct(cs.get('CS%',0)),"",True)
    c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,margin+4*(card_w+gap),card_y,W-margin-(margin+4*(card_w+gap)),92,7,1,1)
    draw_text(c,"KEY TAKEAWAYS",margin+4*(card_w+gap)+14,card_y+66,10,NAVY,"Helvetica-Bold")
    for i,t in enumerate([insights['pitching'], insights['hitting'], insights['running']]):
        draw_text(c,"• "+t,margin+4*(card_w+gap)+16,card_y+47-i*18,7,DARK,"Helvetica",max_width=165,leading=9)

    section_bar(c,"GAME PLAN",margin,H-285,W-2*margin,24)
    gp_y=85; gp_h=170; gp_w=(W-2*margin)/5
    titles=["PITCHING APPROACH","DEFENSIVE APPROACH","OFFENSIVE APPROACH","KEY MATCHUPS","BOTTOM LINE"]
    bodies=[
        "Attack early in the count. Use pitch usage tendencies to anticipate when they become predictable.",
        "Control the running game with quick deliveries, good holds, and awareness in steal counts.",
        "Force their staff into the zone. Use BB% and K% leaders to identify matchup pressure points.",
        insights['matchups'],
        "Discipline, execution, and controlling the running game should drive the plan."
    ]
    for i,(t,b) in enumerate(zip(titles,bodies)):
        x=margin+i*gp_w
        c.setFillColor(colors.white); c.setStrokeColor(BORDER); rr(c,x,gp_y,gp_w-2,gp_h,4,1,1)
        draw_center(c,t,x,gp_y+gp_h-24,gp_w-2,8,RED if i in [0,2,4] else NAVY,"Helvetica-Bold")
        draw_text(c,"• "+b,x+12,gp_y+gp_h-50,8,DARK,"Helvetica",max_width=gp_w-24,leading=13)
    c.showPage()

    # Page 2 Pitching
    header(c,opponent,date_text,logo_bytes,2)
    section_bar(c,"PITCHING PLAN",margin,H-122,W-2*margin,28)
    metric_card(c,W-260,H-217,110,88,"TEAM BB%",fmt_pct(ps.get('BB%',0)),fmt_pct(data['lg_pitch'].get('BB%',np.nan)),ps.get('BB%',0)<=data['lg_pitch'].get('BB%',1),lower_is_better=True)
    metric_card(c,W-140,H-217,110,88,"TEAM K%",fmt_pct(ps.get('K%',0)),fmt_pct(data['lg_pitch'].get('K%',np.nan)),ps.get('K%',0)>=data['lg_pitch'].get('K%',0))
    stacked_pitch_chart(c,data['pitch_usage_count'],margin,H-392,340,250,"PITCH USAGE BY COUNT")
    ptable=pitch_usage_vs_league_table(data['pitch_usage_overall'])
    ptd=ptable.copy()
    if not ptd.empty:
        ptd["Usage %"]=ptd["Usage %"].apply(fmt_pct)
        ptd["LG AVG"]="-"; ptd["DIFF"]="-"
    small_table(c,ptd,margin+350,H-392,220,250,"PITCH USAGE (OVERALL)",max_rows=8,font_size=7)
    insight_box(c,W-260,H-392,230,120,"KEY INSIGHT",insights['pitching'])
    topbb=data['pitchers'].sort_values('BB%',ascending=False).head(3) if not data['pitchers'].empty else pd.DataFrame()
    topk=data['pitchers'].sort_values('K%',ascending=False).head(3) if not data['pitchers'].empty else pd.DataFrame()
    small_table(c,topbb,margin,60,260,110,"HIGHEST BB% PITCHERS",cols=["Pitcher","PA","BB%","K%"],max_rows=3)
    small_table(c,topk,margin+275,60,260,110,"HIGHEST K% PITCHERS",cols=["Pitcher","PA","K%","BB%"],max_rows=3)
    small_table(c,data['pitcher_usage'],margin+550,60,220,110,"PITCHER USAGE SNAPSHOT",max_rows=4,font_size=6)
    c.showPage()

    # Page 3 Hitting
    header(c,opponent,date_text,logo_bytes,3)
    section_bar(c,"HITTING PLAN",margin,H-122,W-2*margin,28)
    bar_chart(c,data['swing_count'],margin,H-382,250,240,"SWING RATE BY COUNT","Swing%",pct=True)
    swing_overall = pd.DataFrame({"Zone":["Overall"],"Swing%":[data['swing_count']['Swing%'].mean() if not data['swing_count'].empty else 0],"LG AVG":[np.nan],"DIFF":[np.nan]})
    swing_overall["Swing%"] = swing_overall["Swing%"].apply(fmt_pct); swing_overall["LG AVG"]="-"; swing_overall["DIFF"]="-"
    small_table(c,swing_overall,margin+265,H-382,220,110,"HITTER SWING% (OVERALL)",max_rows=3)
    insight_box(c,margin+265,H-382+120,220,120,"KEY INSIGHT",insights['hitting'])
    hitters=data['hitters']
    top_ops=hitters.sort_values('OPS',ascending=False).head(3) if not hitters.empty else pd.DataFrame()
    bot_ops=hitters[hitters['PA']>=3].sort_values('OPS',ascending=True).head(3) if not hitters.empty else pd.DataFrame()
    small_table(c,top_ops,W-285,H-275,255,145,"TOP 3 HITTERS",cols=["Player","PA","AVG","OBP","SLG","OPS","BB%","K%"],max_rows=3,font_size=6)
    small_table(c,bot_ops,W-285,H-430,255,145,"BOTTOM 3 HITTERS",cols=["Player","PA","AVG","OBP","SLG","OPS","BB%","K%"],max_rows=3,font_size=6)
    # stat leaderboard grid
    metrics=["AVG","OBP","SLG","OPS","BB%","K%"]
    x0=margin; y0=55; bw=122; bh=94
    for i,m in enumerate(metrics):
        x=x0+(i%3)*(bw+8); y=y0+(1-i//3)*(bh+8)
        top=hitters.sort_values(m,ascending=(m=="K%")).head(3) if not hitters.empty else pd.DataFrame()
        small_table(c,top,x,y,bw,bh,f"BEST {m}",cols=["Player",m,"PA"],max_rows=3,font_size=6)
    c.showPage()

    # Page 4 Catching & Running
    header(c,opponent,date_text,logo_bytes,4)
    section_bar(c,"CATCHING & RUNNING GAME",margin,H-122,W-2*margin,28)
    metric_card(c,W-260,H-217,110,88,"TEAM CS%",fmt_pct(cs.get('CS%',0)),None,True)
    metric_card(c,W-140,H-217,110,88,"TEAM SB%",fmt_pct(bs.get('SB%',0)),None,True)
    bar_chart(c,data['sba_count'],margin,H-392,250,250,"SBA BY COUNT","SBA",pct=False)
    small_table(c,data['catchers'],margin+265,H-392,250,250,"CATCHER LEADERBOARD (BY CS%)",cols=["Catcher","SBA","CS","SB","CS%"],max_rows=8)
    runners=data['runners'][[c for c in ["playerFullName","SBA","SB","SB%"] if c in data['runners'].columns]].copy() if not data['runners'].empty else pd.DataFrame()
    if not runners.empty: runners=runners.rename(columns={"playerFullName":"Runner"})
    small_table(c,runners,W-285,H-392,255,160,"INDIVIDUAL RUNNER TENDENCIES (SB%)",max_rows=6)
    insight_box(c,W-285,80,255,120,"KEY INSIGHT",insights['running'],accent=GREEN_TXT)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()

# ----------------------------
# Streamlit UI
# ----------------------------
st.title("Advanced Pregame Report V2")
st.caption("Upload all opponent and league CSVs at once. Export a visual PDF game plan.")

with st.sidebar:
    st.header("Upload Files")
    all_files = st.file_uploader("Upload all CSVs at once", type=["csv"], accept_multiple_files=True)
    opponent = st.text_input("Opponent Name", "Opponent")
    logo_file = st.file_uploader("Optional team logo", type=["png","jpg","jpeg"])
    st.caption("Expected: Pregame, Copy of Standard, Catching PreGame, Stolen Bases, SBA Count, Pregame Hitting, Rate")

detected=detect_files(all_files)
if all_files:
    st.success(f"Uploaded {len(all_files)} file(s).")
    st.write({k:(v.name if v else None) for k,v in detected.items()})
else:
    st.info("Upload the CSVs to start.")
    st.stop()

pregame=read_csv(detected['pregame'])
standard=read_csv(detected['standard'])
catching=read_csv(detected['catching'])
stolen=read_csv(detected['stolen'])
sba_count_df=read_csv(detected['sba_count'])
lg_hit_df=read_csv(detected['lg_hitting'])
lg_pitch_df=read_csv(detected['lg_pitching'])

hitters=hitter_stats(pregame)
pitchers=pitcher_stats(standard)
pitch_count=pitch_usage_by_count(standard)
pitch_overall=pitch_usage_overall(standard)
pitcher_usage=pitcher_usage_table(standard)
swing_count=swing_take_by_count(pregame)
hitter_swing=hitter_swing_table(pregame)
catchers=catcher_table(catching)
sba_count=sba_team_count(stolen,sba_count_df)
runners=runner_tendencies(sba_count_df)
lg_hit=league_hitting_avgs(lg_hit_df)
lg_pitch=league_pitching_avgs(lg_pitch_df)

team_hitting={}
if not hitters.empty:
    totals=hitters.sum(numeric_only=True)
    team_hitting={"AVG":safe_div(totals.get('H',0),totals.get('AB',0)),"OBP":safe_div(totals.get('H',0)+totals.get('BB',0),totals.get('AB',0)+totals.get('BB',0)),"SLG":np.nan,"OPS":np.nan,"BB%":safe_div(totals.get('BB',0),totals.get('PA',0)),"K%":safe_div(totals.get('K',0),totals.get('PA',0))}
else: team_hitting={"AVG":0,"BB%":0,"K%":0}
team_pitching={"BB%": pitchers['BB'].sum()/pitchers['PA'].sum() if not pitchers.empty and pitchers['PA'].sum() else 0,
               "K%": pitchers['K'].sum()/pitchers['PA'].sum() if not pitchers.empty and pitchers['PA'].sum() else 0}
team_catching={"SBA": catchers['SBA'].sum() if not catchers.empty else 0,
               "CS%": safe_div(catchers['CS'].sum(), catchers['SBA'].sum()) if not catchers.empty else 0}
team_running={"SBA": runners['SBA'].sum() if not runners.empty and 'SBA' in runners else 0,
              "SB%": safe_div(runners['SB'].sum(), runners['SBA'].sum()) if not runners.empty and 'SB' in runners and runners['SBA'].sum() else 0}

data={"hitters":hitters,"pitchers":pitchers,"pitch_usage_count":pitch_count,"pitch_usage_overall":pitch_overall,"pitcher_usage":pitcher_usage,"swing_count":swing_count,"hitter_swing":hitter_swing,"catchers":catchers,"sba_count":sba_count,"runners":runners,"lg_hit":lg_hit,"lg_pitch":lg_pitch,"team_hitting":team_hitting,"team_pitching":team_pitching,"team_catching":team_catching,"team_running":team_running}

# dashboard preview
c1,c2,c3,c4=st.columns(4)
c1.metric("Team AVG", fmt_dec(team_hitting.get('AVG',0)), f"Lg {fmt_dec(lg_hit.get('AVG',np.nan))}")
c2.metric("Pitching BB%", fmt_pct(team_pitching.get('BB%',0)), f"Lg {fmt_pct(lg_pitch.get('BB%',np.nan))}")
c3.metric("Pitching K%", fmt_pct(team_pitching.get('K%',0)), f"Lg {fmt_pct(lg_pitch.get('K%',np.nan))}")
c4.metric("Running SB%", fmt_pct(team_running.get('SB%',0)))

tabs=st.tabs(["Pitching","Hitting","Catching & Running","PDF Export"])
with tabs[0]:
    st.subheader("Pitching")
    st.dataframe(pitch_count.style.format("{:.1%}"), use_container_width=True)
    st.dataframe(pitcher_usage, use_container_width=True)
    st.dataframe(pitchers, use_container_width=True)
with tabs[1]:
    st.subheader("Hitting")
    st.dataframe(swing_count.style.format({"Swing%":"{:.1%}","Take%":"{:.1%}"}), use_container_width=True)
    st.dataframe(hitters, use_container_width=True)
    st.dataframe(hitter_swing, use_container_width=True)
with tabs[2]:
    st.subheader("Catching & Running")
    st.dataframe(catchers, use_container_width=True)
    st.dataframe(sba_count, use_container_width=True)
    st.dataframe(runners, use_container_width=True)
with tabs[3]:
    st.subheader("Export Beautiful PDF")
    logo_bytes = logo_file.read() if logo_file else None
    pdf_bytes=build_visual_pdf(opponent, datetime.now().strftime("%b %d, %Y"), logo_bytes, data)
    st.download_button("Download Beautiful Pregame PDF", data=pdf_bytes, file_name=f"{opponent.replace(' ','_')}_advanced_pregame_report_v2.pdf", mime="application/pdf")
