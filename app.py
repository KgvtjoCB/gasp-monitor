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

CODIGOS_ALVO = [12001, 12002]
TERMOS_ALVO = [
    "alvará de soltura",
    "baixa de mandado de prisão",
    "contramandado",
    "revogação de prisão temporária",
    "revogação de prisão preventiva",
    "relaxamento de prisão",
    "extinção da punibilidade",
]

st.set_page_config(
    page_title="Monitor de Restrições - GASP", page_icon="⚖️", layout="wide"
)
st.title("⚖️ Sistema de Monitoramento de Restrições Impeditivas")
st.markdown(
    "Gerência de Administração do Sistema Penitenciário — Acompanhamento de processos"
)

conn = st.connection("gsheets", type=GSheetsConnection)


def formatar_numero_processo(valor):
    """Garante a integridade do número do processo impedindo conversões de notação científica."""
    if pd.isna(valor) or valor == "":
        return ""

    val_str = str(valor).strip()

    # Trata caso o pandas leia como notação científica (ex: 5.035390262025808e+19)
    if "e+" in val_str.lower():
        try:
            val_str = f"{int(float(val_str))}"
        except ValueError:
            pass

    return re.sub(r"\D", "", val_str)


def carregar_dados():
    # Lê a planilha forçando o conector a ignorar o cache
    df = conn.read(ttl=0)

    colunas_necessarias = [
        "processo",
        "nome_ppl",
        "data_insercao",
        "orgao_julgador",
        "status",
    ]
    for col in colunas_necessarias:
        if col not in df.columns:
            df[col] = ""

    df = df[colunas_necessarias]

    # Força tipo string pura em todas as colunas
    for col in df.columns:
        df[col] = df[col].astype(str).fillna("")

    df["processo"] = df["processo"].apply(formatar_numero_processo)
    return df


def salvar_dados_planilha(df_salvar):
    df_salvar["processo"] = df_salvar["processo"].apply(
        formatar_numero_processo
    )
    for col in df_salvar.columns:
        df_salvar[col] = df_salvar[col].astype(str).fillna("")

    conn.update(data=df_salvar.to_dict(orient="records"))


# ------------------------------------------------------------------------------
# FORMULÁRIO DE CADASTRO
# ------------------------------------------------------------------------------
st.subheader("📋 Cadastrar novo processo impeditivo")

with st.form(key="form_cadastro", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

    with col1:
        num_processo = st.text_input(
            "Número do processo (somente números):",
            placeholder="Ex: 50353902620258080048",
            max_chars=20,
        )

    with col2:
        nome_ppl = st.text_input(
            "Nome da pessoa privada de liberdade (PPL):",
            placeholder="Ex: João da Silva",
        )

    with col3:
        data_insercao = st.date_input(
            "Data de inserção:",
            value=datetime.now(),
            format="DD/MM/YYYY",
        )

    with col4:
        status_inicial = st.selectbox(
            "Status do registro:", options=["Pendente", "Analisado"], index=0
        )

    submit = st.form_submit_button("Cadastrar para monitoramento")

if submit:
    num_limpo = formatar_numero_processo(num_processo)
    nome_formatado = nome_ppl.strip().upper()

    if not num_limpo or not nome_formatado:
        st.error("Preencha o número do processo e o nome do preso.")
    else:
        df_atual = carregar_dados()

        if (
            not df_atual.empty
            and num_limpo in df_atual["processo"].astype(str).values
        ):
            st.warning("Este processo já está cadastrado no sistema.")
        else:
            novo_registro = pd.DataFrame([{
                "processo": str(num_limpo),
                "nome_ppl": nome_formatado,
                "data_insercao": data_insercao.strftime("%d/%m/%Y"),
                "orgao_julgador": "Aguardando consulta",
                "status": status_inicial,
            }])

            df_atualizado = pd.concat(
                [df_atual, novo_registro], ignore_index=True
            )
            salvar_dados_planilha(df_atualizado)
            st.success("Processo cadastrado com sucesso na planilha.")
            st.rerun()

st.divider()

# ------------------------------------------------------------------------------
# PLANILHA DE DADOS CONSOLIDADOS
# ------------------------------------------------------------------------------
df_banco = carregar_dados()
st.subheader("📊 Planilha de dados consolidados")

if not df_banco.empty:
    st.markdown(
        "Edite as informações na tabela abaixo. Para **excluir**, clique na linha e pressione **Delete** do teclado e salve."
    )

    df_editado = st.data_editor(
        df_banco,
        column_config={
            "processo": st.column_config.TextColumn(
                "PROCESSO",
                help="Número do processo (apenas dígitos)",
                validate=r"^\d*$",
            ),
            "nome_ppl": st.column_config.TextColumn("NOME DA PPL"),
            "data_insercao": st.column_config.TextColumn("DATA DE INSERÇÃO"),
            "orgao_julgador": st.column_config.TextColumn("ÓRGÃO JULGADOR"),
            "status": st.column_config.SelectboxColumn(
                "STATUS",
                options=["Pendente", "Analisado"],
                required=True,
            ),
        },
        use_container_width=True,
        num_rows="dynamic",
    )

    col_btn_salvar, col_btn_varredura = st.columns([1, 1])

    with col_btn_salvar:
        if st.button("💾 Salvar alterações na planilha"):
            salvar_dados_planilha(df_editado)
            st.success("Alterações salvas com sucesso.")
            st.rerun()

    with col_btn_varredura:
        executar_varredura = st.button(
            "🔍 Executar varredura dos pendentes no Datajud", type="primary"
        )

    if executar_varredura:
        headers = {
            "Authorization": f"APIKey {API_KEY}",
            "Content-Type": "application/json",
        }
        alertas = []
        alteracao_dados = False

        df_execucao = df_banco.copy()
        indices_pendentes = df_execucao[
            df_execucao["status"] == "Pendente"
        ].index

        if len(indices_pendentes) == 0:
            st.info("Não há processos com status 'Pendente' para consultar.")
        else:
            with st.spinner(
                f"Consultando a API do TJES para {len(indices_pendentes)} processo(s)..."
            ):
                for idx in indices_pendentes:
                    numero_limpo = formatar_numero_processo(
                        df_execucao.at[idx, "processo"]
                    )
                    ppl = df_execucao.at[idx, "nome_ppl"]

                    if not numero_limpo:
                        continue

                    # Executa a busca exatamente como testado no PowerShell
                    payload = {"query": {"term": {"numeroProcesso": numero_limpo}}}

                    try:
                        res = requests.post(
                            URL_API,
                            json=payload,
                            headers=headers,
                            timeout=15,
                        )
                        dados = res.json()
                        hits = dados.get("hits", {}).get("hits", [])

                        if hits:
                            fonte = hits[0].get("_source", {})

                            orgao_info = fonte.get("orgaoJulgador", {})
                            orgao_nome = ""
                            if isinstance(orgao_info, dict):
                                orgao_nome = str(
                                    orgao_info.get("nome", "")
                                ).strip()

                            if orgao_nome:
                                df_execucao.at[idx, "orgao_julgador"] = (
                                    orgao_nome
                                )
                                alteracao_dados = True
                                st.toast(f"✓ Órgão localizado: {orgao_nome}")

                            movs = fonte.get("movimentos", [])
                            for m in movs:
                                cod = m.get("codigo")
                                nome_mov = str(m.get("nome", "")).lower()

                                if (cod in CODIGOS_ALVO) or any(
                                    t in nome_mov for t in TERMOS_ALVO
                                ):
                                    alertas.append({
                                        "ppl": ppl,
                                        "proc": numero_limpo,
                                        "orgao": orgao_nome or "Não informado",
                                        "evento": m.get("nome"),
                                        "data": m.get("dataHora"),
                                    })
                                    break
                        else:
                            st.toast(
                                f"❌ Processo {numero_limpo} não encontrado no TJES."
                            )

                    except Exception as e:
                        st.error(f"Erro ao consultar o Datajud: {e}")

            if alteracao_dados:
                salvar_dados_planilha(df_execucao)

            if alertas:
                st.balloons()
                st.error("🚨 Atenção: desimpedimento detectado!")
                for a in alertas:
                    st.markdown(f"""
                    * **PPL:** {a['ppl']}
                    * **Processo:** `{a['proc']}`
                    * **Órgão julgador:** {a['orgao']}
                    * **Movimento:** {a['evento']}
                    * **Data/Hora:** {a['data']}
                    * **Ação recomendada:** Reavaliar a transferência para o regime semiaberto no BNMP 3.0 e alterar o status para **Analisado**.
                    """)
            else:
                st.success("Varredura concluída com sucesso.")

            st.rerun()
else:
    st.info("Nenhum processo cadastrado na planilha até o momento.")
