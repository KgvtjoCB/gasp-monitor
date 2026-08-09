from datetime import datetime
import json
import re
import pandas as pd
import requests
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==============================================================================
# CONFIGURAÇÕES DO DATAJUD / CNJ
# ==============================================================================
URL_API = "https://api-publica.datajud.cnj.jus.br/api_publica_tjes/_search"
API_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="

st.set_page_config(
    page_title="Diagnóstico Datajud", page_icon="🛠️", layout="wide"
)
st.title("🛠️ Diagnóstico do Datajud em Tempo Real")

conn = st.connection("gsheets", type=GSheetsConnection)


def formatar_numero_processo(valor):
    if pd.isna(valor) or valor == "":
        return ""
    val_str = str(valor).strip()
    if "e+" in val_str.lower():
        try:
            val_str = f"{int(float(val_str))}"
        except ValueError:
            pass
    return re.sub(r"\D", "", val_str)


# Carrega dados
df_banco = conn.read(ttl=0)
for col in ["processo", "nome_ppl", "data_insercao", "orgao_julgador", "status"]:
    if col not in df_banco.columns:
        df_banco[col] = ""

df_banco["processo"] = df_banco["processo"].apply(formatar_numero_processo)

st.write("### Tabela Atual Lido da Planilha:")
st.dataframe(df_banco)

if st.button("🔍 Executar varredura com DIAGNÓSTICO COMPLETO", type="primary"):
    headers = {
        "Authorization": f"APIKey {API_KEY}",
        "Content-Type": "application/json",
    }

    indices_pendentes = df_banco[df_banco["status"] == "Pendente"].index

    if len(indices_pendentes) == 0:
        st.warning(
            "Nenhum processo com status 'Pendente' foi encontrado na planilha."
        )
    else:
        for idx in indices_pendentes:
            numero = str(df_banco.at[idx, "processo"])
            ppl = df_banco.at[idx, "nome_ppl"]

            with st.expander(
                f"🔎 Analisando Processo: {numero} ({ppl})", expanded=True
            ):
                payload = {"query": {"term": {"numeroProcesso": numero}}}

                st.write("**1. Dados enviados para a API:**")
                st.code(json.dumps(payload, indent=2), language="json")

                try:
                    res = requests.post(
                        URL_API, json=payload, headers=headers, timeout=15
                    )

                    st.write(f"**2. Código de Status HTTP:** `{res.status_code}`")

                    if res.status_code == 200:
                        dados = res.json()
                        hits = dados.get("hits", {}).get("hits", [])
                        total_hits = (
                            dados.get("hits", {})
                            .get("total", {})
                            .get("value", 0)
                        )

                        st.write(
                            f"**3. Total de processos encontrados:** `{total_hits}`"
                        )

                        if hits:
                            fonte = hits[0].get("_source", {})
                            orgao_info = fonte.get("orgaoJulgador", {})
                            st.success(f"✓ Órgão Julgador encontrado: {orgao_info}")
                            st.write("**Conteúdo do `_source` retornado:**")
                            st.json(fonte)
                        else:
                            st.error(
                                f"A API respondeu OK (200), mas a busca por '{numero}' não retornou nenhum 'hit'."
                            )
                            st.write("**Resposta bruta do Datajud:**")
                            st.json(dados)
                    else:
                        st.error(
                            f"Erro na requisição. Resposta do servidor: {res.text}"
                        )

                except Exception as e:
                    st.error(f"Erro de conexão com o Datajud: {e}")
