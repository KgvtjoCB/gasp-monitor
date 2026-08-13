from datetime import datetime
import hashlib
import json
import os
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
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

# ID da Planilha do CACTUS onde fica a aba _USUARIOS
ID_PLANILHA_CACTUS = "1JO6Pr6SZ3ywvBqgV2epQGI2R5D1YUuK_5keY-qZ59l0"

st.set_page_config(
    page_title="Monitor de Restrições - GASP", page_icon="⚖️", layout="wide"
)

# ==============================================================================
# ESTILIZAÇÃO CSS CUSTOMIZADA (IDENTIDADE VISUAL CACTUS)
# ==============================================================================
st.markdown("""
<style>
    /* Fundo geral off-white */
    .stApp {
        background-color: #f4f6f9;
    }
    
    /* Rótulos dos campos em Caixa Alta, Negrito e Grafite */
    .stTextInput label, .stDateInput label, .stSelectbox label {
        font-weight: 700 !important;
        text-transform: uppercase !important;
        font-size: 0.75rem !important;
        color: #4b5563 !important;
        letter-spacing: 0.025em;
    }

    /* Container do Formulário de Cadastro e Login */
    div[data-testid="stForm"] {
        background-color: #ffffff;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }

    /* Botões Primários (Azul Marinho CACTUS) */
    .stButton > button[kind="primary"], div[data-testid="stForm"] .stButton > button {
        background-color: #12284C !important;
        color: white !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 0.5rem 1.5rem !important;
    }
    .stButton > button[kind="primary"]:hover, div[data-testid="stForm"] .stButton > button:hover {
        background-color: #1a3666 !important;
    }

    /* Botão Secundário (Vazado / Outline) */
    .stButton > button[kind="secondary"] {
        background-color: transparent !important;
        color: #12284C !important;
        border: 1px solid #12284C !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    .stButton > button[kind="secondary"]:hover {
        background-color: #f3f4f6 !important;
    }

    /* Caixas de Texto com bordas arredondadas */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        border-radius: 6px !important;
        border-color: #d1d5db !important;
    }
</style>
""", unsafe_allow_html=True)

conn = st.connection("gsheets", type=GSheetsConnection)

# ==============================================================================
# FUNÇÕES DE AUTENTICAÇÃO E CRIPTOGRAFIA
# ==============================================================================
def gerar_hash_sha256(texto):
    """Gera a hash SHA-256 equivalente ao Utilities.computeDigest do GAS"""
    return hashlib.sha256(str(texto).encode('utf-8')).hexdigest()

def obter_credenciais_gcp():
    """Busca as credenciais do GCP nos Secrets testando múltiplos formatos de chaves"""
    # Teste 1: Chave GCP_SERVICE_ACCOUNT direta
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        raw_val = st.secrets["GCP_SERVICE_ACCOUNT"]
        return json.loads(raw_val) if isinstance(raw_val, str) else dict(raw_val)
    
    # Teste 2: Configuração gsheets nativa do Streamlit
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        g_secrets = st.secrets["connections"]["gsheets"]
        if "service_account_json" in g_secrets:
            return json.loads(g_secrets["service_account_json"])
        return dict(g_secrets)
        
    raise ValueError("Chave de credenciais GCP não encontrada nos Secrets do Streamlit.")

def conectar_gspread_cactus():
    """Conecta à planilha do CACTUS utilizando gspread"""
    creds_dict = obter_credenciais_gcp()
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(ID_PLANILHA_CACTUS).worksheet("_USUARIOS")

def autenticar_usuario_cactus(email_digitado, senha_digitada):
    try:
        sheet_usuarios = conectar_gspread_cactus()
        registros = sheet_usuarios.get_all_records()
        
        if not registros:
            return False, "Base de usuários vazia.", None

        df_usuarios = pd.DataFrame(registros)
        for col in df_usuarios.columns:
            df_usuarios[col] = df_usuarios[col].astype(str)

        email_limpo = str(email_digitado).strip().lower()
        hash_senha = gerar_hash_sha256(senha_digitada)

        usuario_match = df_usuarios[
            (df_usuarios['EMAIL'].str.strip().str.lower() == email_limpo) & 
            (df_usuarios['SENHA_HASH'].str.strip() == hash_senha)
        ]

        if not usuario_match.empty:
            nome_usuario = usuario_match.iloc[0]['NOME']
            return True, "Autenticado com sucesso", nome_usuario
        else:
            return False, "E-mail ou senha incorretos.", None
    except Exception as e:
        return False, f"Erro de conexão com o CACTUS: {e}", None

# Gerenciamento da Sessão de Login
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
if "nome_usuario" not in st.session_state:
    st.session_state["nome_usuario"] = ""

# ==============================================================================
# TELA DE LOGIN (ESTILO CARD CACTUS)
# ==============================================================================
if not st.session_state["autenticado"]:
    col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])

    with col_l2:
        st.write("") 
        st.write("")
        with st.form(key="form_login_cactus"):
            st.markdown("""
            <div style="background-color: #12284C; color: white; padding: 20px; margin: -1.5rem -1.5rem 1.5rem -1.5rem; text-align: center; border-radius: 8px 8px 0 0;">
                <h3 style="color: white; margin: 0; font-size: 20px; font-weight: 700;">🛡️ Cactus - Acesso</h3>
                <span style="font-size: 13px; opacity: 0.85;">Sistema de Monitoramento (GASP)</span>
            </div>
            """, unsafe_allow_html=True)

            email_input = st.text_input("E-MAIL", placeholder="seu.email@gmail.com")
            senha_input = st.text_input("SENHA", type="password", placeholder="••••••••")

            btn_login = st.form_submit_button("➔ Entrar no sistema", use_container_width=True)

            if btn_login:
                if not email_input or not senha_input:
                    st.error("Preencha o e-mail e a senha.")
                else:
                    sucesso, msg, nome = autenticar_usuario_cactus(email_input, senha_input)
                    if sucesso:
                        st.session_state["autenticado"] = True
                        st.session_state["nome_usuario"] = nome
                        st.success(f"Bem-vindo, {nome}!")
                        st.rerun()
                    else:
                        st.error(msg)

# ==============================================================================
# PAINEL PRINCIPAL (SÓ RENDERIZA APÓS AUTENTICAÇÃO)
# ==============================================================================
if st.session_state["autenticado"]:
    
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        st.markdown(f"""
        <div style="background-color: #ffffff; padding: 10px 16px; border-radius: 8px; border: 1px solid #e5e7eb; display: inline-block;">
            <span style="color: #12284C; font-weight: 700;">🌵 CACTUS</span> 
            <span style="color: #9ca3af;"> | </span> 
            <span style="color: #16a34a; font-weight: 600; font-size: 13px;">● Online</span> 
            <span style="color: #9ca3af;"> | </span> 
            <span style="color: #374151; font-weight: 600; font-size: 14px;">👤 {st.session_state['nome_usuario']}</span>
        </div>
        """, unsafe_allow_html=True)
    with col_hdr2:
        if st.button("🚪 Sair do Sistema", type="secondary"):
            st.session_state["autenticado"] = False
            st.session_state["nome_usuario"] = ""
            st.rerun()

    st.title("⚖️ Monitoramento de Restrições Impeditivas (BETA)")
    st.markdown("Gerência de Administração do Sistema Penitenciário — Acompanhamento de processos")

    # ==========================================================================
    # FUNÇÕES DE BANCO DE DADOS
    # ==========================================================================
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
            "processo", "nome_ppl", "data_insercao", 
            "data_mandado", "orgao_julgador", "status"
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

    # ==========================================================================
    # DESIGN DA PÁGINA (ABAS)
    # ==========================================================================
    aba_monitoramento, aba_historico = st.tabs(["📊 Monitoramento ativo", "🚨 Histórico de baixas"])

    # --------------------------------------------------------------------------
    # ABA 1: MONITORAMENTO ATIVO
    # --------------------------------------------------------------------------
    with aba_monitoramento:

        with st.form(key="form_cadastro", clear_on_submit=True):
            st.markdown("""
            <div style="background-color: #12284C; color: white; padding: 16px; margin: -1.5rem -1.5rem 1.5rem -1.5rem; text-align: center; border-radius: 8px 8px 0 0;">
                <h3 style="color: white; margin: 0; font-size: 18px; font-weight: 600;">🛡️ CADASTRAR NOVA RESTRIÇÃO IMPEDITIVA</h3>
                <span style="font-size: 13px; font-weight: 400; opacity: 0.85;">Preencha os dados do mandado/interno para monitoramento processual</span>
            </div>
            """, unsafe_allow_html=True)

            col1, col2, col3, col4, col5 = st.columns([1.5, 2, 1, 1, 1])

            with col1:
                num_processo = st.text_input(
                    "Nº Processo (só números):",
                    placeholder="Ex: 50353902620258080048",
                    max_chars=20,
                )

            with col2:
                nome_ppl = st.text_input(
                    "Nome do interno (PPL):",
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
                    "Últ. verif. BNMP:",
                    value=datetime.now(),
                    format="DD/MM/YYYY",
                    help="Data em que foi realizada a última consulta no BNMP."
                )

            with col5:
                status_inicial = st.selectbox(
                    "Status do registro:", options=["Pendente", "Analisado"], index=0
                )

            submit = st.form_submit_button("➔ Salvar Cadastro")

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
        st.subheader("📊 Planilha de dados consolidados")

        df_banco = carregar_dados()
        df_exibicao = df_banco.copy()

        # ----------------------------------------------------------------------
        # TOOLBAR INSTITUCIONAL (Busca, Ordem expandida e Badge)
        # ----------------------------------------------------------------------
        col_busca, col_ordem, col_badge = st.columns([4, 2, 1])

        with col_busca:
            termo_busca = st.text_input(
                "Buscar",
                placeholder="🔍 Pesquisar processo, nome ou órgão...",
                label_visibility="collapsed"
            )

        with col_ordem:
            opcao_ordem = st.selectbox(
                "Ordenar",
                options=[
                    "Data de inserção (mais recente)",
                    "Data de inserção (mais antiga)",
                    "Últ. verificação BNMP (mais recente)",
                    "Últ. verificação BNMP (mais antiga)",
                    "Nome do preso (A-Z)",
                    "Nome do preso (Z-A)",
                    "Órgão Julgador (A-Z)",
                    "Órgão Julgador (Z-A)",
                    "Status (Pendentes 1º)",
                    "Status (Analisados 1º)"
                ],
                label_visibility="collapsed"
            )

        # Aplicação do Filtro
        if not df_exibicao.empty and termo_busca:
            termo_limpo = termo_busca.strip().lower()
            df_exibicao = df_exibicao[
                df_exibicao["nome_ppl"].str.lower().str.contains(termo_limpo) |
                df_exibicao["processo"].str.contains(termo_limpo) |
                df_exibicao["orgao_julgador"].str.lower().str.contains(termo_limpo) |
                df_exibicao["status"].str.lower().str.contains(termo_limpo)
            ]

        # Aplicação da Ordenação
        if not df_exibicao.empty:
            if opcao_ordem == "Data de inserção (mais recente)":
                df_exibicao["dt_tmp"] = pd.to_datetime(df_exibicao["data_insercao"], format="%d/%m/%Y", errors="coerce")
                df_exibicao = df_exibicao.sort_values(by="dt_tmp", ascending=False).drop(columns=["dt_tmp"])
            elif opcao_ordem == "Data de inserção (mais antiga)":
                df_exibicao["dt_tmp"] = pd.to_datetime(df_exibicao["data_insercao"], format="%d/%m/%Y", errors="coerce")
                df_exibicao = df_exibicao.sort_values(by="dt_tmp", ascending=True).drop(columns=["dt_tmp"])
            elif opcao_ordem == "Últ. verificação BNMP (mais recente)":
                df_exibicao["dt_tmp"] = pd.to_datetime(df_exibicao["data_mandado"], format="%d/%m/%Y", errors="coerce")
                df_exibicao = df_exibicao.sort_values(by="dt_tmp", ascending=False).drop(columns=["dt_tmp"])
            elif opcao_ordem == "Últ. verificação BNMP (mais antiga)":
                df_exibicao["dt_tmp"] = pd.to_datetime(df_exibicao["data_mandado"], format="%d/%m/%Y", errors="coerce")
                df_exibicao = df_exibicao.sort_values(by="dt_tmp", ascending=True).drop(columns=["dt_tmp"])
            elif opcao_ordem == "Nome do preso (A-Z)":
                df_exibicao = df_exibicao.sort_values(by="nome_ppl", ascending=True)
            elif opcao_ordem == "Nome do preso (Z-A)":
                df_exibicao = df_exibicao.sort_values(by="nome_ppl", ascending=False)
            elif opcao_ordem == "Órgão Julgador (A-Z)":
                df_exibicao = df_exibicao.sort_values(by="orgao_julgador", ascending=True)
            elif opcao_ordem == "Órgão Julgador (Z-A)":
                df_exibicao = df_exibicao.sort_values(by="orgao_julgador", ascending=False)
            elif opcao_ordem == "Status (Pendentes 1º)":
                df_exibicao = df_exibicao.sort_values(by="status", ascending=False)
            elif opcao_ordem == "Status (Analisados 1º)":
                df_exibicao = df_exibicao.sort_values(by="status", ascending=True)
                
            df_exibicao = df_exibicao.reset_index(drop=True)

        with col_badge:
            total_registros = len(df_exibicao)
            st.markdown(
                f"""
                <div style="text-align: right; margin-top: 2px;">
                    <span style="background-color: #1a1a1a; color: #ffffff; padding: 6px 14px; border-radius: 12px; font-weight: 600; font-size: 13px; display: inline-block;">
                        {total_registros} registro{'s' if total_registros != 1 else ''}
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.write("")

        if not df_banco.empty:
            st.markdown(
                "<span style='color: #4b5563; font-size: 14px;'>Edite na tabela abaixo. Clique no cabeçalho das colunas para ordenação rápida. Para <b>excluir</b>, selecione a linha e pressione <b>Delete</b>.</span>", 
                unsafe_allow_html=True
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
                    "data_mandado": st.column_config.TextColumn("ÚLTIMA VERIF. BNMP"),
                    "orgao_julgador": st.column_config.TextColumn("ÓRGÃO JULGADOR"),
                    "status": st.column_config.SelectboxColumn(
                        "STATUS",
                        options=["Pendente", "Analisado"],
                        required=True,
                    ),
                },
                use_container_width=True,
                num_rows="dynamic",
                hide_index=True,
            )

            col_btn_salvar, col_btn_varredura = st.columns([1, 1])

            with col_btn_salvar:
                if st.button("💾 Salvar edições na planilha"):
                    salvar_dados_planilha(df_editado)
                    st.success("Alterações salvas com sucesso.")
                    st.rerun()

            with col_btn_varredura:
                executar_varredura = st.button(
                    "🔍 Executar varredura Datajud", type="primary"
                )

            # ==================================================================
            # VARREDURA DATAJUD COM TIMEOUT E RETENTATIVA AUTOMÁTICA
            # ==================================================================
            if executar_varredura:
                headers = {
                    "Authorization": f"APIKey {API_KEY}",
                    "Content-Type": "application/json",
                }
                alertas = []
                alteracao_dados = False
                processos_com_timeout = []

                df_execucao = df_banco.copy()
                indices_pendentes = df_execucao[
                    df_execucao["status"].str.strip().str.lower() == "pendente"
                ].index

                if len(indices_pendentes) == 0:
                    st.info("Não há processos com status 'Pendente' para consultar.")
                else:
                    bar_progresso = st.progress(0)
                    total_proc = len(indices_pendentes)

                    with st.spinner(f"Consultando a API do TJES para {total_proc} processo(s)..."):
                        for idx_count, idx in enumerate(indices_pendentes):
                            bar_progresso.progress((idx_count + 1) / total_proc)

                            numero_limpo = formatar_numero_processo(df_execucao.at[idx, "processo"])
                            ppl = df_execucao.at[idx, "nome_ppl"]

                            if not numero_limpo or len(numero_limpo) != 20:
                                continue

                            payload = {"query": {"term": {"numeroProcesso": numero_limpo}}}

                            # Tentativa de consulta com timeout expandido para 35 segundos
                            res = None
                            for tentativa in range(2):
                                try:
                                    res = requests.post(URL_API, json=payload, headers=headers, timeout=35)
                                    if res.status_code == 200:
                                        break
                                except requests.exceptions.RequestException:
                                    if tentativa == 1:
                                        processos_com_timeout.append(f"{ppl} ({numero_limpo})")

                            if res and res.status_code == 200:
                                try:
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
                                except Exception:
                                    pass

                    bar_progresso.empty()

                    if alteracao_dados:
                        salvar_dados_planilha(df_execucao)

                    if processos_com_timeout:
                        st.warning(f"⚠️ O servidor do Datajud/TJES não respondeu a tempo para {len(processos_com_timeout)} processo(s). A varredura dos demais foi concluída normalmente.")

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

    # --------------------------------------------------------------------------
    # ABA 2: HISTÓRICO DE BAIXAS
    # --------------------------------------------------------------------------
    with aba_historico:
        st.subheader("📋 Registro de baixas detectadas")
        st.markdown("<span style='color: #4b5563; font-size: 14px;'>Abaixo estão listados todos os processos que tiveram movimentação de soltura/extinção detectada. Para <b>excluir um registro</b>, selecione a linha na tabela, pressione <b>Delete</b> no teclado e clique em <b>Salvar alterações</b>.</span>", unsafe_allow_html=True)
        
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
