# Databricks notebook source
# MAGIC %md
# MAGIC # Ingestão SIA-SUS / APAC Tratamento Dialítico (job Databricks)
# MAGIC
# MAGIC Versão adaptada de `pipelines/datasus/ingest_atd.py` para rodar como
# MAGIC **Databricks Job** (equivalente ao papel de um Glue Job na AWS): cluster
# MAGIC efêmero que sobe só para a execução, roda a ingestão e desliga.
# MAGIC
# MAGIC Principais diferenças em relação à versão CLI/GitHub Actions:
# MAGIC - Parâmetros vêm de widgets (`uf`, `meses`) em vez de variáveis de ambiente.
# MAGIC - Autenticação no ADLS usa a **chave da storage account**, já disponível
# MAGIC   no secret scope `conecta-renal-adls` (criado pelo Terraform para o SQL
# MAGIC   Warehouse), em vez de credenciais de Service Principal — evita duplicar
# MAGIC   segredo só para este job.
# MAGIC
# MAGIC Mantém a mesma lógica de negócio (FTP → descompressão `.dbc` → seleção de
# MAGIC colunas → Parquet no bronze). Sem filtro de CID: o instrumento APAC de
# MAGIC Tratamento Dialítico já é, por natureza, exclusivo de pacientes em diálise.
# MAGIC Se `ingest_atd.py` mudar, replicar as mudanças relevantes aqui também.

# COMMAND ----------

# MAGIC %pip install dbfread pyreaddbc

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import io
import time
from datetime import date
from ftplib import FTP, error_perm

import pandas as pd
import pyreaddbc
from dbfread import DBF
from azure.storage.filedatalake import DataLakeServiceClient

FTP_HOST = "ftp.datasus.gov.br"
FTP_PORT = 21
FTP_USER = "anonymous"
FTP_PASSWORD = ""
FTP_REMOTE_DIR = "/dissemin/publicos/SIASUS/200801_/Dados"

COLUNAS_RELEVANTES = [
    "AP_CNSPCN", "AP_CMP", "AP_MUNPCN", "AP_SEXO", "AP_COIDADE", "AP_NUIDADE",
    "AP_CODUNI", "AP_UFMUN", "AP_CIDPRI",
    "ATD_CARACT", "ATD_DTPDR", "ATD_DTCLI", "ATD_ACEVAS", "ATD_MAISNE",
    "ATD_SITTRA", "ATD_SEAPTO", "ATD_HB", "ATD_FOSFOR", "ATD_KTVSEM",
    "ATD_TRU", "ATD_ALBUMI", "ATD_PTH", "ATD_HIV", "ATD_HCV", "ATD_HBSAG",
]

MAX_TENTATIVAS = 3
BACKOFF_SEGUNDOS = 5

AZURE_STORAGE_ACCOUNT = "stconectarenaldev"
AZURE_STORAGE_CONTAINER = "bronze"

# COMMAND ----------

dbutils.widgets.text("uf", "SP", "UF")
dbutils.widgets.text("meses", "3", "Janela de meses")

uf = dbutils.widgets.get("uf").upper()
qtd_meses = int(dbutils.widgets.get("meses"))
storage_key = dbutils.secrets.get(scope="conecta-renal-adls", key="storage-account-key")

print(f"Iniciando ingestão SIA-SUS (ATD) | UF={uf} | janela={qtd_meses} meses")

# COMMAND ----------


def meses_para_processar(qtd_meses: int) -> list[tuple[int, int]]:
    hoje = date.today()
    ano_ref, mes_ref = hoje.year, hoje.month
    referencias: list[tuple[int, int]] = []
    for _ in range(qtd_meses):
        mes_ref -= 1
        if mes_ref == 0:
            mes_ref = 12
            ano_ref -= 1
        referencias.append((ano_ref, mes_ref))
    referencias.reverse()
    return referencias


def conectar_ftp() -> FTP:
    ultima_excecao = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            ftp = FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
            ftp.login(user=FTP_USER, passwd=FTP_PASSWORD)
            ftp.cwd(FTP_REMOTE_DIR)
            return ftp
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            print(f"Falha ao conectar ao FTP (tentativa {tentativa}/{MAX_TENTATIVAS}): {exc}")
            if tentativa < MAX_TENTATIVAS:
                time.sleep(BACKOFF_SEGUNDOS)
    raise ultima_excecao


def baixar_bytes(ftp: FTP, nome_arquivo: str) -> bytes | None:
    """Baixa o arquivo para memória. Retorna None se não existir (550)."""
    ultima_excecao = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            buffer = io.BytesIO()
            ftp.retrbinary(f"RETR {nome_arquivo}", buffer.write)
            return buffer.getvalue()
        except error_perm as exc:
            if str(exc).startswith("550"):
                print(f"Arquivo não encontrado no FTP: {nome_arquivo}")
                return None
            ultima_excecao = exc
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc

        print(f"Falha ao baixar '{nome_arquivo}' (tentativa {tentativa}/{MAX_TENTATIVAS}): {ultima_excecao}")
        if tentativa < MAX_TENTATIVAS:
            time.sleep(BACKOFF_SEGUNDOS)

    print(f"Desistindo de baixar '{nome_arquivo}' após {MAX_TENTATIVAS} tentativas.")
    return None


def dbc_bytes_para_dataframe(conteudo_dbc: bytes, nome_arquivo: str) -> pd.DataFrame:
    dbc_path = f"/tmp/{nome_arquivo}"
    dbf_path = dbc_path.replace(".dbc", ".dbf")
    with open(dbc_path, "wb") as fh:
        fh.write(conteudo_dbc)
    try:
        pyreaddbc.dbc2dbf(dbc_path, dbf_path)
        tabela = DBF(dbf_path, load=True, encoding="latin-1", char_decode_errors="ignore")
        return pd.DataFrame(iter(tabela))
    finally:
        import os as _os
        _os.remove(dbc_path)
        _os.remove(dbf_path) if _os.path.exists(dbf_path) else None


def selecionar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    colunas_existentes = [c for c in COLUNAS_RELEVANTES if c in df.columns]
    return df.reindex(columns=colunas_existentes)


def salvar_parquet(filesystem_client, df: pd.DataFrame, ano: int, mes: int) -> int:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    conteudo = buffer.getvalue()
    caminho = f"atd/ano={ano}/mes={mes:02d}/data.parquet"
    file_client = filesystem_client.get_file_client(caminho)
    file_client.upload_data(conteudo, overwrite=True)
    return len(conteudo)


# COMMAND ----------

account_url = f"https://{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net"
service_client = DataLakeServiceClient(account_url=account_url, credential=storage_key)
filesystem_client = service_client.get_file_system_client(AZURE_STORAGE_CONTAINER)

ftp = conectar_ftp()

total_processados = 0
total_registros = 0
total_bytes = 0

try:
    for ano, mes in meses_para_processar(qtd_meses):
        aa = ano % 100
        nome_arquivo = f"ATD{uf}{aa:02d}{mes:02d}.dbc"
        print(f"Processando {nome_arquivo}...")

        conteudo_dbc = baixar_bytes(ftp, nome_arquivo)
        if conteudo_dbc is None:
            continue

        try:
            df_original = dbc_bytes_para_dataframe(conteudo_dbc, nome_arquivo)
        except Exception as exc:  # noqa: BLE001
            print(f"Arquivo corrompido, pulando '{nome_arquivo}': {exc}")
            continue

        df_final = selecionar_colunas(df_original)

        tamanho = salvar_parquet(filesystem_client, df_final, ano, mes)

        total_processados += 1
        total_registros += len(df_original)
        total_bytes += tamanho

        print(f"OK {nome_arquivo} | registros={len(df_original)} | parquet={tamanho} bytes")
finally:
    ftp.quit()

print("\n===== Resumo da execução - SIA-SUS ATD (Databricks Job) =====")
print(f"Total de arquivos processados      : {total_processados}")
print(f"Total de registros                 : {total_registros}")
print(f"Tamanho total gravado no Data Lake  : {total_bytes / (1024 * 1024):.2f} MB")
