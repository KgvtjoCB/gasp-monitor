from datetime import datetime
import pandas as pd
import requests
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==============================================================================
# CONFIGURAÇÕES DO DATAJUD / CNJ
# ==============================================================================
URL_API = "https://api-publica.datajud.cnj.jus.br/api_publica_tjes/_search"
API_KEY = "cjZwYXJ0bmVyOmJ1Z3N3YXJtLWtleQ=="

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

# Configuração da página web
st.set_page_config(
    page_title="Monitor de Restrições - GASP", page_icon="⚖️", layout="wide"
)
st.title("⚖️ Sistema de Monitoramento de Restrições Impeditivas")
st.markdown(
    "Gerência de Administração do Sistema Penitenciário — Acompanhamento de processos"
)

# Conexão com o Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)


def carregar_dados():
    df = conn.read(ttl=0)
    colunas_necessarias = ["processo", "nome_ppl", "data_insercao", "status"]
    for col in colunas_necessarias:
        if col not in df.columns:
            df[col] = None
    return df[colunas_necessarias]


# ------------------------------------------------------------------------------
# FORMULÁRIO DE CADASTRO
# ------------------------------------------------------------------------------
st.subheader("📋 Cadastrar novo processo impeditivo")

with st.form(key="form_cadastro", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

    with col1:
        num_processo = st.text_input(
            "Número do processo (somente números):",
            placeholder="Ex: 00012345620268080000",
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
    num_limpo = "".join(filter(str.isdigit, num_processo))
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
                "status": status_inicial,
            }])

            df_atualizado = pd.concat(
                [df_atual, novo_registro], ignore_index=True
            )
            conn.update(data=df_atualizado)
            st.success("Processo cadastrado com sucesso na planilha.")
            st.rerun()

st.divider()

# ------------------------------------------------------------------------------
# PLANILHA DE DADOS CONSOLIDADOS (EDITÁVEL)
# ------------------------------------------------------------------------------
df_banco = carregar_dados()
st.subheader("📊 Planilha de dados consolidados")

if not df_banco.empty:
    st.markdown(
        "Você pode editar o status ou as informações diretamente na tabela abaixo e clicar no botão **Salvar alterações na planilha**."
    )

    df_editado = st.data_editor(
        df_banco,
        column_config={
            "processo": st.column_config.TextColumn("PROCESSO"),
            "nome_ppl": st.column_config.TextColumn("NOME DA PPL"),
            "data_insercao": st.column_config.TextColumn("DATA DE INSERÇÃO"),
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
            conn.update(data=df_editado)
            st.success("Alterações salvas com sucesso.")
            st.rerun()

    with col_btn_varredura:
        executar_varredura = st.button(
            "🔍 Executar varredura dos pendentes no Datajud", type="primary"
        )

    # --------------------------------------------------------------------------
    # LÓGICA DE VARREDURA (APENAS REGISTROS "PENDENTE")
    # --------------------------------------------------------------------------
    if executar_varredura:
        headers = {
            "Authorization": f"APIKey {API_KEY}",
            "Content-Type": "application/json",
        }
        alertas = []

        df_pendentes = df_editado[df_editado["status"] == "Pendente"]

        if df_pendentes.empty:
            st.info("Não há processos com status 'Pendente' para consultar.")
        else:
            with st.spinner(
                f"Consultando a API do TJES para {len(df_pendentes)} processo(s) pendente(s)..."
            ):
                for _, row in df_pendentes.iterrows():
                    numero = str(row["processo"])
                    ppl = row["nome_ppl"]

                    payload = {"query": {"match": {"numeroProcesso": numero}}}

                    try:
                        res = requests.post(
                            URL_API, json=payload, headers=headers
                        )
                        dados = res.json()
                        hits = dados.get("hits", {}).get("hits", [])

                        if hits:
                            movs = hits[0]["_source"].get("movimentos", [])
                            for m in movs:
                                cod = m.get("codigo")
                                nome_mov = str(m.get("nome", "")).lower()

                                if (cod in CODIGOS_ALVO) or any(
                                    t in nome_mov for t in TERMOS_ALVO
                                ):
                                    alertas.append({
                                        "ppl": ppl,
                                        "proc": numero,
                                        "evento": m.get("nome"),
                                        "data": m.get("dataHora"),
                                    })
                                    break
                    except Exception as e:
                        st.error(f"Erro ao consultar o processo {numero}: {e}")

            if alertas:
                st.balloons()
                st.error("🚨 Atenção: desimpedimento detectado!")
                for a in alertas:
                    st.markdown(f"""
                    * **PPL:** {a['ppl']}
                    * **Processo:** `{a['proc']}`
                    * **Movimento:** {a['evento']}
                    * **Data/Hora:** {a['data']}
                    * **Ação recomendada:** Reavaliar a transferência para o regime semiaberto no sistema BNMP 3.0 e alterar o status para **Analisado**.
                    """)
            else:
                st.success(
                    "Nenhuma alteração de soltura ou baixa detectada nos processos pendentes."
                )
else:
    st.info("Nenhum processo cadastrado na planilha até o momento.")
