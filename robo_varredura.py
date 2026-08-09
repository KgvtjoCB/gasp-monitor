from datetime import datetime
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

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


def conectar_google_sheets():
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT")
    if not creds_json:
        raise ValueError(
            "Variável de ambiente GCP_SERVICE_ACCOUNT não encontrada."
        )

    creds_dict = json.loads(creds_json)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("BD_GASP_Monitor").sheet1


def executar_varredura():
    print(
        f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] Iniciando varredura automática no Datajud..."
    )

    try:
        sheet = conectar_google_sheets()
        dados = sheet.get_all_records()
    except Exception as e:
        print(f"Erro ao conectar com a planilha Google: {e}")
        return

    if not dados:
        print("Planilha vazia. Encerrando execução.")
        return

    headers = {
        "Authorization": f"APIKey {API_KEY}",
        "Content-Type": "application/json",
    }
    houve_alteracao = False

    for idx, row in enumerate(dados, start=2):  # start=2 ignora a linha do cabeçalho
        numero = str(row.get("processo", "")).strip()
        ppl = str(row.get("nome_ppl", "")).strip()
        status_atual = str(row.get("status", "")).strip()

        # Executa a varredura apenas para registros pendentes
        if status_atual.lower() == "analisado":
            continue

        payload = {"query": {"match": {"numeroProcesso": numero}}}

        try:
            res = requests.post(URL_API, json=payload, headers=headers)
            dados_cnj = res.json()
            hits = dados_cnj.get("hits", {}).get("hits", [])

            if hits:
                movs = hits[0]["_source"].get("movimentos", [])
                for m in movs:
                    cod = m.get("codigo")
                    nome_mov = str(m.get("nome", "")).lower()

                    if (cod in CODIGOS_ALVO) or any(
                        t in nome_mov for t in TERMOS_ALVO
                    ):
                        print(
                            f"[ALERTA] Desimpedimento identificado para {ppl} (Processo: {numero})."
                        )
                        houve_alteracao = True
                        break
        except Exception as e:
            print(f"Erro ao consultar o processo {numero}: {e}")

    if not houve_alteracao:
        print("Varredura concluída sem novas alterações registradas.")


if __name__ == "__main__":
    executar_varredura()
