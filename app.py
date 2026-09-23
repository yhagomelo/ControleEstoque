import io
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Conciliação de EPIs", page_icon="🦺", layout="wide")

SQL_VIEW = Path(__file__).with_name("schema_view.sql").read_text(encoding="utf-8")

S_OK = "🟢 OK"
S_DIV = "🟡 DIVERGENTE"
S_GM = "🔵 APENAS NO GMCORE"
S_RS = "🔴 APENAS NO RSDATA"
S_SD = "⚠️ SEM DE-PARA"
TODOS_STATUS = [S_OK, S_DIV, S_GM, S_RS, S_SD]
COR = {S_OK: "#d1fae5", S_DIV: "#fef3c7", S_GM: "#dbeafe", S_RS: "#fee2e2", S_SD: "#e5e7eb"}

# Colunas obrigatórias (nomes normalizados) e apelidos aceitos nos arquivos
OBRIGATORIAS = {
    "gmcore": ["filial", "cod_gm", "estoque_gm"],
    "rsdata": ["filial", "produto", "ca", "quantidade_rs"],
    "depara": ["cod_gm", "key"],
}
APELIDOS = {
    "gmcore": {"produto_codigo_epi": "cod_gm", "codigo": "cod_gm", "cod": "cod_gm",
               "produto": "produto_gm", "descricao": "produto_gm", "estoque": "estoque_gm"},
    "rsdata": {"quantidade": "quantidade_rs", "qtd_rs": "quantidade_rs", "qtd": "quantidade_rs"},
    "depara": {"key_ca_produto_tamanho": "key", "chave": "key", "cod_int_produto": "cod_int_produto"},
}


def norm_col(c: str) -> str:
    c = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")


def prepara(df: pd.DataFrame, tabela: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = [APELIDOS[tabela].get(norm_col(c), norm_col(c)) for c in df.columns]
    faltando = [c for c in OBRIGATORIAS[tabela] if c not in df.columns]
    if faltando:
        st.error(f"Tabela **{tabela}**: colunas ausentes {faltando}. Colunas lidas: {list(df.columns)}")
        st.stop()
    if tabela == "gmcore":
        if "produto_gm" not in df.columns:
            df["produto_gm"] = df["cod_gm"]
        df["estoque_gm"] = pd.to_numeric(df["estoque_gm"], errors="coerce").fillna(0)
    if tabela == "rsdata":
        if "tamanho" not in df.columns:
            df["tamanho"] = ""
        df["quantidade_rs"] = pd.to_numeric(df["quantidade_rs"], errors="coerce").fillna(0)
        df["tamanho"] = df["tamanho"].fillna("").astype(str)
        df["ca"] = df["ca"].astype(str).str.replace(r"\.0$", "", regex=True)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    return df


def le_arquivo(f) -> pd.DataFrame:
    return pd.read_csv(f, sep=None, engine="python") if f.name.lower().endswith(".csv") else pd.read_excel(f)


def demo():
    gm = pd.DataFrame([
        ("ACME", "MATRIZ", "ALMOX", "EPI", "GM001", "LUVA NITRILICA M", 100),
        ("ACME", "MATRIZ", "ALMOX", "EPI", "GM002", "LUVA NITRILICA G", 50),
        ("ACME", "MATRIZ", "ALMOX", "EPI", "GM003", "CAPACETE BRANCO", 30),
        ("ACME", "FILIAL 2", "ALMOX", "EPI", "GM004", "BOTA PVC 42", 12),
        ("ACME", "FILIAL 2", "ALMOX", "EPI", "GM999", "MASCARA PFF2", 8),
    ], columns=["empresa", "filial", "departamento", "secao", "cod_gm", "produto_gm", "estoque_gm"])
    rs = pd.DataFrame([
        ("ACME", "MATRIZ", "ALMOX", "LUVA NITRILICA", "12345", "M", 100),
        ("ACME", "MATRIZ", "ALMOX", "LUVA NITRILICA", "12345", "G", 45),
        ("ACME", "FILIAL 2", "ALMOX", "BOTA PVC", "40002", "42", 12),
        ("ACME", "FILIAL 2", "ALMOX", "OCULOS AMPLA VISAO", "50003", "UN", 20),
        ("ACME", "FILIAL 2", "ALMOX", "PROTETOR AURICULAR", "77777", "UN", 15),
    ], columns=["empresa", "filial", "local_estoque", "produto", "ca", "tamanho", "quantidade_rs"])
    dp = pd.DataFrame([
        ("12345", "INT1", "GM001", "12345|LUVA NITRILICA|M"),
        ("12345", "INT1", "GM002", "12345|LUVA NITRILICA|G"),
        ("30001", "INT2", "GM003", "30001|CAPACETE BRANCO|UN"),
        ("40002", "INT3", "GM004", "40002|BOTA PVC|42"),
        ("50003", "INT4", "GM005", "50003|OCULOS AMPLA VISAO|UN"),
    ], columns=["ca", "cod_int_produto", "cod_gm", "key"])
    return gm, rs, dp


@st.cache_data(show_spinner="Conciliando...")
def concilia(gm: pd.DataFrame, rs: pd.DataFrame, dp: pd.DataFrame) -> pd.DataFrame:
    con = sqlite3.connect(":memory:")
    gm.to_sql("gmcore", con, index=False)
    rs.to_sql("rsdata", con, index=False)
    dp.to_sql("depara", con, index=False)
    con.executescript(SQL_VIEW)
    out = pd.read_sql("SELECT * FROM vw_conciliacao", con)
    con.close()
    return out


# ----------------------------- Sidebar -----------------------------
st.sidebar.header("📂 Dados")
f_gm = st.sidebar.file_uploader("Base Gmcore", type=["xlsx", "xls", "csv"])
f_rs = st.sidebar.file_uploader("Base RSData", type=["xlsx", "xls", "csv"])
f_dp = st.sidebar.file_uploader("Tabela De-Para", type=["xlsx", "xls", "csv"])
usar_demo = not (f_gm and f_rs and f_dp)

if usar_demo:
    st.sidebar.info("Sem os 3 arquivos, exibindo **dados de demonstração**.")
    gm_raw, rs_raw, dp_raw = demo()
else:
    gm_raw, rs_raw, dp_raw = le_arquivo(f_gm), le_arquivo(f_rs), le_arquivo(f_dp)

df = concilia(prepara(gm_raw, "gmcore"), prepara(rs_raw, "rsdata"), prepara(dp_raw, "depara"))

st.sidebar.header("🔎 Filtros")
filiais = st.sidebar.multiselect("Filial", sorted(df["filial"].dropna().unique()))
busca = st.sidebar.text_input("Buscar produto, código ou CA")

if "status_sel" not in st.session_state:
    st.session_state.status_sel = TODOS_STATUS
c1, c2 = st.sidebar.columns(2)
if c1.button("⚡ Só divergências", use_container_width=True):
    st.session_state.status_sel = [s for s in TODOS_STATUS if s != S_OK]
if c2.button("Todos", use_container_width=True):
    st.session_state.status_sel = TODOS_STATUS
status_sel = st.sidebar.multiselect("Status da conciliação", TODOS_STATUS, key="status_sel")

# ----------------------------- Filtragem -----------------------------
base = df.copy()
if filiais:
    base = base[base["filial"].isin(filiais)]
if busca:
    b = busca.strip()
    mask = pd.Series(False, index=base.index)
    for col in ["produto_gm", "produto_rs", "codigo_epi", "ca"]:
        mask |= base[col].fillna("").astype(str).str.contains(b, case=False, regex=False)
    base = base[mask]
tabela = base[base["status_conciliacao"].isin(status_sel)]

# ----------------------------- KPIs -----------------------------
st.title("🦺 Conciliação de Estoque de EPIs — Gmcore × RSData")
cont = base["status_conciliacao"].value_counts()
k = st.columns(6)
k[0].metric("Total analisado", len(base))
k[1].metric("🟢 OK", int(cont.get(S_OK, 0)))
k[2].metric("🟡 Divergências", int(cont.get(S_DIV, 0)))
k[3].metric("🔵 Só no Gmcore", int(cont.get(S_GM, 0)))
k[4].metric("🔴 Só no RSData", int(cont.get(S_RS, 0)))
k[5].metric("⚠️ Sem De-Para", int(cont.get(S_SD, 0)))

# ----------------------------- Tabela -----------------------------
exib = tabela.rename(columns={
    "filial": "Filial", "codigo_epi": "Código/EPI", "produto_gm": "Produto GM", "qtd_gm": "Qtd GM",
    "produto_rs": "Produto RS", "qtd_rs": "Qtd RS", "diferenca": "Diferença",
    "status_conciliacao": "Status",
})[["Filial", "Código/EPI", "Produto GM", "Qtd GM", "Produto RS", "Qtd RS", "Diferença", "Status"]]
exib = exib.fillna({"Produto GM": "—", "Produto RS": "—"})


def cor_status(v):
    return f"background-color: {COR.get(v, '')}; font-weight: 600; color: #111"


def cor_dif(v):
    return "color: #b91c1c; font-weight: 700" if v != 0 else ""


st.dataframe(
    exib.style.map(cor_status, subset=["Status"]).map(cor_dif, subset=["Diferença"]),
    use_container_width=True, hide_index=True, height=520,
)
st.caption(f"{len(exib)} linhas exibidas")

# ----------------------------- Exportação -----------------------------
diverg = base[base["status_conciliacao"] != S_OK].sort_values(["filial", "status_conciliacao"])
diverg_x = diverg.rename(columns={
    "filial": "Filial", "chave": "Chave", "codigo_epi": "Código/EPI", "ca": "CA", "tamanho": "Tamanho",
    "produto_gm": "Produto GM", "qtd_gm": "Qtd GM", "produto_rs": "Produto RS", "qtd_rs": "Qtd RS",
    "diferenca": "Diferença", "status_conciliacao": "Status",
})
e1, e2, _ = st.columns([1, 1, 4])
e1.download_button("⬇️ Divergências (CSV)", diverg_x.to_csv(index=False, sep=";").encode("utf-8-sig"),
                   "divergencias_epi.csv", "text/csv")
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    diverg_x.to_excel(w, index=False, sheet_name="Divergencias")
e2.download_button("⬇️ Divergências (Excel)", buf.getvalue(), "divergencias_epi.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
