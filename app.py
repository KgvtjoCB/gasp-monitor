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

CODIGOS_ALVO = [
    12001,  # Alvará de Soltura
    12002,  # Contramandado de Prisão
    10964,  # Concessão de Liberdade Provisória
    10963,  # Revogação de Prisão Preventiva
    10965,  # Revogação de Prisão Temporária
    10966,  # Relaxamento de Prisão
    183,    # Extinção da Punibilidade
]

TERMOS_ALVO = [
    "alvará de soltura",
    "alvara de soltura",
    "contramandado",
    "baixa de mandado de prisão",
    "baixa do mandado",
    "liberdade provisória",
    "liberdade provisoria",
    "revogação de prisão",
    "revogacao de prisao",
    "relaxamento de prisão",
    "relaxamento de prisao",
    "extinção da punibilidade",
    "extincao da punibilidade",
    "concedida a liberdade",
    "revogada a prisão",
]

st.set_page_config(
    page_title="Monitor de Restrições - GASP", page_icon="⚖️", layout="wide"
)

# ==============================================================================
# ESTILIZAÇÃO CSS CUSTOMIZADA (PADRÃO CACTUS / INSTITUCIONAL)
# ==============================================================================
st.markdown("""
<style>
    /* Fundo limpo e tipografia neutra */
    .stApp {
        background-color: #f8f9fa;
    }
    
    /* Botões padronizados */
    .stButton > button {
        border-radius: 6px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    
    /* Containers de formulário com bordas suaves */
    div[data-testid="stForm"] {
        background-color: #ffffff;
        border-radius: 8px;
        border: 1px solid #e9ecef;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        padding: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ Sistema de Monitoramento de Restrições Impeditivas (BETA)")
st.markdown(
    "Gerência de Administração do Sistema Penitenciário — Acompanhamento de processos"
)

conn = st.connection("gsheets", type=GSheetsConnection)

# ==============================================================================
# FUNÇÕES DE BANCO DE DADOS
# ==============================================================================
def formatar_numero_processo(valor):
    if pd.isna(valor) or valor is None:
        return ""
    val_str = str(valor).strip()
    if val_str.lower() == "nan":
        return ""
    if val_str.startswith("'"):
        val_str = val_str[1:]
    return re.sub(r"\D", "", val_str)


def carregar_dados():
    df = conn.read(ttl=0, dtype=str)
    colunas_necessarias = [
        "processo",
        "nome_ppl",
        "data_insercao",
        "data_mandado",
        "orgao_julgador",
        "status",
    ]
    for col in colunas_necessarias:
        if col not in df.columns:
            df[col] = ""
    df = df[colunas_necessarias]
    for col in df.columns:
        df[col] = df[col].astype(str).fillna("").replace("nan", "")
    df["processo"] = df["processo"].apply(formatar_numero_processo)
    return df


def salvar_dados_planilha(df_salvar):
    df_salvar["processo"] = df_salvar["processo"].apply(formatar_numero_processo)
    for col in df_salvar.columns:
        df_salvar[col] = df_salvar[col].astype(str).fillna("").replace("nan", "")
    st.cache_data.clear()
    conn.update(data=df_salvar)


def carregar_historico_baixas():
    try:
        df_hist = conn.read(worksheet="historico_baixas", ttl=0, dtype=str)
        colunas_hist = [
            "processo", "nome_ppl", "orgao_julgador", 
            "evento_detectado", "data_evento_tjes", "data_registro_sistema"
        ]
        for col in colunas_hist:
            if col not in df_hist.columns:
                df_hist[col] = ""
        df_hist = df_hist[colunas_hist]
        for col in df_hist.columns:
            df_hist[col] = df_hist[col].astype(str).fillna("").replace("nan", "")
        df_hist["processo"] = df_hist["processo"].apply(formatar_numero_processo)
        return df_hist
    except Exception:
        return pd.DataFrame(columns=[
            "processo", "nome_ppl", "orgao_julgador", 
            "evento_detectado", "data_evento_tjes", "data_registro_sistema"
        ])


def salvar_historico_baixas(df_hist_salvar):
    df_hist_salvar["processo"] = df_hist_salvar["processo"].apply(formatar_numero_processo)
    for col in df_hist_salvar.columns:
        df_hist_salvar[col] = df_hist_salvar[col].astype(str).fillna("").replace("nan", "")
    st.cache_data.clear()
    conn.update(worksheet="historico_baixas", data=df_hist_salvar)


# ==============================================================================
# DESIGN DA PÁGINA (ABAS)
# ==============================================================================
aba_monitoramento, aba_historico = st.tabs(["📊 Monitoramento ativo", "🚨 Histórico de baixas"])

# ------------------------------------------------------------------------------
# ABA 1: MONITORAMENTO ATIVO
# ------------------------------------------------------------------------------
with aba_monitoramento:
    st.subheader("📋 Cadastrar novo processo impeditivo")

    with st.form(key="form_cadastro", clear_on_submit=True):
        col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])

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
            data_mandado = st.date_input(
                "Última verificação no BNMP:",
                value=datetime.now(),
                format="DD/MM/YYYY",
                help="Data em que foi realizada a última consulta no BNMP. Impede alertas falsos de alvarás antigos."
            )

        with col5:
            status_inicial = st.selectbox(
                "Status do registro:", options=["Pendente", "Analisado"], index=0
            )

        submit = st.form_submit_button("Cadastrar para monitoramento")

    if submit:
        num_limpo = formatar_numero_processo(num_processo)
        nome_formatado = nome_ppl.strip().upper()

        if not num_limpo or not nome_formatado:
            st.error("Preencha o número do processo e o nome do preso.")
        elif len(num_limpo) != 20:
            st.error(f"O número do processo deve conter exatamente 20 dígitos (tem {len(num_limpo)}).")
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
                    "data_mandado": data_mandado.strftime("%d/%m/%Y"),
                    "orgao_julgador": "Aguardando consulta",
                    "status": status_inicial,
                }])

                df_atualizado = pd.concat([df_atual, novo_registro], ignore_index=True)
                salvar_dados_planilha(df_atualizado)
                st.success("Processo cadastrado com sucesso na planilha.")
                st.rerun()

    st.divider()

    df_banco = carregar_dados()
    df_exibicao = df_banco.copy()

    # ----------------------------------------------------------------------
    # BUSCA GLOBAL E BADGE DE QUANTITATIVO
    # ----------------------------------------------------------------------
    termo_busca = st.text_input(
        "🔍 Filtrar registros por nome, processo, órgão ou status:",
        placeholder="Digite para pesquisar em tempo real em todas as colunas..."
    )

    if not df_exibicao.empty and termo_busca:
        termo_limpo = termo_busca.strip().lower()
        df_exibicao = df_exibicao[
            df_exibicao["nome_ppl"].str.lower().str.contains(termo_limpo) |
            df_exibicao["processo"].str.contains(termo_limpo) |
            df_exibicao["orgao_julgador"].str.lower().str.contains(termo_limpo) |
            df_exibicao["status"].str.lower().str.contains(termo_limpo)
        ]

    # Reseta o índice para garantir ordenação nativa fluida ao clicar no cabeçalho
    if not df_exibicao.empty:
        df_exibicao = df_exibicao.reset_index(drop=True)

    total_registros = len(df_exibicao)
    col_titulo, col_badge = st.columns([3, 1])

    with col_titulo:
        st.subheader("📊 Planilha de dados consolidados")
    with col_badge:
        st.markdown(
            f"""
            <div style="text-align: right; margin-top: 10px;">
                <span style="background-color: #212529; color: #ffffff; padding: 6px 16px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
                    {total_registros} registro{'s' if total_registros != 1 else ''}
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

    if not df_banco.empty:
        st.markdown(
            "Edite as informações na tabela abaixo. Clique nos **cabeçalhos das colunas** para ordenar. Para **excluir**, selecione a linha, pressione **Delete** no teclado e salve."
        )

        df_editado = st.data_editor(
            df_exibicao,
            column_config={
                "processo": st.column_config.TextColumn(
                    "PROCESSO",
                    help="Número do processo (20 dígitos)",
                    validate=r"^\d{20}$",
                ),
                "nome_ppl": st.column_config.TextColumn("NOME DO PRESO"),
                "data_insercao": st.column_config.TextColumn("DATA DE INSERÇÃO"),
                "data_mandado": st.column_config.TextColumn("ÚLTIMA VERIFICAÇÃO NO BNMP"),
                "orgao_julgador": st.column_config.TextColumn("ÓRGÃO JULGADOR"),
                "status": st.column_config.SelectboxColumn(
                    "STATUS",
                    options=["Pendente", "Analisado"],
                    required=True,
                ),
            },
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,  # Oculta a coluna de índice numérico
        )

        col_btn_salvar, col_btn_varredura = st.columns([1, 1])

        with col_btn_salvar:
            if st.button("💾 Salvar alterações na planilha"):
                salvar_dados_planilha(df_editado)
                st.success("Alterações salvas com sucesso.")
                st.rerun()

        with col_btn_varredura:
            executar_varredura = st.button(
                "🔍 Executar varredura", type="primary"
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
                df_execucao["status"].str.strip().str.lower() == "pendente"
            ].index

            if len(indices_pendentes) == 0:
                st.info("Não há processos com status 'Pendente' para consultar.")
            else:
                with st.spinner(f"Consultando a API do TJES para {len(indices_pendentes)} processo(s) pendente(s)..."):
                    for idx in indices_pendentes:
                        numero_limpo = formatar_numero_processo(df_execucao.at[idx, "processo"])
                        ppl = df_execucao.at[idx, "nome_ppl"]

                        if not numero_limpo or len(numero_limpo) != 20:
                            continue

                        payload = {"query": {"term": {"numeroProcesso": numero_limpo}}}

                        try:
                            res = requests.post(URL_API, json=payload, headers=headers, timeout=15)
                            dados = res.json()
                            hits = dados.get("hits", {}).get("hits", [])

                            if hits:
                                fonte = hits[0].get("_source", {})

                                orgao_info = fonte.get("orgaoJulgador", {})
                                orgao_nome = ""
                                if isinstance(orgao_info, dict):
                                    orgao_nome = str(orgao_info.get("nome", "")).strip()

                                if orgao_nome and df_execucao.at[idx, "orgao_julgador"] != orgao_nome:
                                    df_execucao.at[idx, "orgao_julgador"] = orgao_nome
                                    alteracao_dados = True

                                movs = fonte.get("movimentos", [])
                                for m in movs:
                                    cod = m.get("codigo")
                                    nome_mov = str(m.get("nome", "")).lower()
                                    data_mov_iso = m.get("dataHora", "")

                                    movimento_valido = True
                                    try:
                                        data_mandado_str = str(df_execucao.at[idx, "data_mandado"]).strip()
                                        
                                        if data_mandado_str and data_mov_iso:
                                            dt_mandado = datetime.strptime(data_mandado_str, "%d/%m/%Y").date()
                                            dt_movimento = datetime.strptime(data_mov_iso[:10], "%Y-%m-%d").date()
                                            
                                            if dt_movimento < dt_mandado:
                                                movimento_valido = False
                                    except Exception:
                                        pass

                                    if movimento_valido:
                                        if (cod in CODIGOS_ALVO) or any(t in nome_mov for t in TERMOS_ALVO):
                                            alertas.append({
                                                "ppl": ppl,
                                                "proc": numero_limpo,
                                                "orgao": orgao_nome or "Não informado",
                                                "evento": m.get("nome"),
                                                "data": m.get("dataHora"),
                                            })
                                            break
                        except Exception as e:
                            st.error(f"Erro ao consultar o Datajud: {e}")

                if alteracao_dados:
                    salvar_dados_planilha(df_execucao)

                if alertas:
                    st.error("🚨 Atenção: desimpedimentos detectados no Datajud!")
                    
                    df_hist_atual = carregar_historico_baixas()
                    novos_registros = []
                    data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                    for a in alertas:
                        duplicado = False
                        if not df_hist_atual.empty:
                            ja_existe = df_hist_atual[
                                (df_hist_atual["processo"] == a['proc']) & 
                                (df_hist_atual["evento_detectado"] == a['evento'])
                            ]
                            if len(ja_existe) > 0:
                                duplicado = True

                        if not duplicado:
                            novos_registros.append({
                                "processo": a['proc'],
                                "nome_ppl": a['ppl'],
                                "orgao_julgador": a['orgao'],
                                "evento_detectado": a['evento'],
                                "data_evento_tjes": a['data'],
                                "data_registro_sistema": data_hora_atual
                            })

                        st.markdown(f"""
                        * **PPL:** {a['ppl']}
                        * **Processo:** `{a['proc']}`
                        * **Órgão julgador:** {a['orgao']}
                        * **Movimento:** {a['evento']}
                        * **Data/Hora:** {a['data']}
                        * **Ação recomendada:** Reavaliar a transferência para o regime semiaberto no BNMP 3.0 e alterar o status para **Analisado**.
                        """)

                    if novos_registros:
                        df_novos_hist = pd.DataFrame(novos_registros)
                        df_hist_atualizado = pd.concat([df_hist_atual, df_novos_hist], ignore_index=True)
                        salvar_historico_baixas(df_hist_atualizado)
                else:
                    st.success("Varredura concluída com sucesso. Nenhuma nova alteração identificada.")

                st.rerun()
    else:
        st.info("Nenhum processo cadastrado na planilha até o momento.")

# ------------------------------------------------------------------------------
# ABA 2: HISTÓRICO DE BAIXAS
# ------------------------------------------------------------------------------
with aba_historico:
    st.subheader("📋 Registro de baixas detectadas")
    st.markdown("Abaixo estão listados todos os processos que tiveram movimentação de soltura/extinção detectada. Para **excluir um registro**, selecione a linha na tabela, pressione **Delete** no teclado e clique em **Salvar alterações**.")
    
    df_historico_view = carregar_historico_baixas()
    
    if not df_historico_view.empty:
        df_historico_editado = st.data_editor(
            df_historico_view,
            column_config={
                "processo": st.column_config.TextColumn("PROCESSO"),
                "nome_ppl": st.column_config.TextColumn("NOME DO PRESO"),
                "orgao_julgador": st.column_config.TextColumn("ÓRGÃO JULGADOR"),
                "evento_detectado": st.column_config.TextColumn("EVENTO DETECTADO (TJES)"),
                "data_evento_tjes": st.column_config.TextColumn("DATA/HORA DO EVENTO"),
                "data_registro_sistema": st.column_config.TextColumn("DATA DE VERIFICAÇÃO")
            },
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="editor_historico"
        )
        
        col_hist_1, col_hist_2 = st.columns([1, 1])
        
        with col_hist_1:
            if st.button("💾 Salvar alterações no Histórico"):
                salvar_historico_baixas(df_historico_editado)
                st.success("Histórico atualizado com sucesso.")
                st.rerun()
                
        st.divider()
        
        with st.expander("🗑️ Excluir um registro específico por seleção"):
            opcoes_exclusao = [
                f"{row['nome_ppl']} — Processo: {row['processo']} ({row['evento_detectado']})"
                for _, row in df_historico_view.iterrows()
            ]
            
            registro_selecionado = st.selectbox(
                "Selecione o registro que deseja apagar:",
                options=opcoes_exclusao
            )
            
            if st.button("Remover registro selecionado", type="primary"):
                idx_para_remover = opcoes_exclusao.index(registro_selecionado)
                df_historico_filtrado = df_historico_view.drop(index=idx_para_remover).reset_index(drop=True)
                salvar_historico_baixas(df_historico_filtrado)
                st.success("Registro removido do histórico com sucesso.")
                st.rerun()
    else:
        st.info("Nenhum histórico de baixa registrado até o momento.")
