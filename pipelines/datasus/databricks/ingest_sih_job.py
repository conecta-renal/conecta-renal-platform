# Databricks notebook source
# MAGIC %md
# MAGIC # Ingestão SIH-SUS (job Databricks)
# MAGIC
# MAGIC Versão adaptada de `pipelines/datasus/ingest_sih.py` para rodar como
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
# MAGIC Mantém a mesma lógica de negócio (FTP → descompressão `.dbc` → filtro de
# MAGIC CID renal → Parquet no bronze). Se `ingest_sih.py` mudar, replicar as
# MAGIC mudanças relevantes aqui também.

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
FTP_REMOTE_DIR = "/dissemin/publicos/SIHSUS/200801_/Dados"

CID_RENAIS = ("N18", "N17", "Z49", "Z940", "E11", "I10", "N04", "N03")

COLUNAS_RELEVANTES = [
    "N_AIH", "DT_INTER", "DT_SAIDA", "DIAG_PRINC", "DIAG_SECUN",
    "MUNIC_RES", "NASC", "SEXO", "IDADE", "MORTE", "DIAS_PERM",
    "VAL_TOT", "PROC_REA", "CNES", "ANO_CMPT", "MES_CMPT",
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

print(f"Iniciando ingestão SIH-SUS | UF={uf} | janela={qtd_meses} meses")

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


def filtrar_cids_renais(df: pd.DataFrame) -> pd.DataFrame:
    diag_princ = df.get("DIAG_PRINC", pd.Series(dtype=str)).astype(str)
    diag_secun = df.get("DIAG_SECUN", pd.Series(dtype=str)).astype(str)
    mascara = diag_princ.str.startswith(CID_RENAIS) | diag_secun.str.startswith(CID_RENAIS)
    return df[mascara]


def selecionar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    colunas_existentes = [c for c in COLUNAS_RELEVANTES if c in df.columns]
    return df.reindex(columns=colunas_existentes)


def salvar_parquet(filesystem_client, df: pd.DataFrame, ano: int, mes: int) -> int:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    conteudo = buffer.getvalue()
    caminho = f"sih/ano={ano}/mes={mes:02d}/data.parquet"
    file_client = filesystem_client.get_file_client(caminho)
    file_client.upload_data(conteudo, overwrite=True)
    return len(conteudo)


# COMMAND ----------

account_url = f"https://{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net"
service_client = DataLakeServiceClient(account_url=account_url, credential=storage_key)
filesystem_client = service_client.get_file_system_client(AZURE_STORAGE_CONTAINER)

ftp = conectar_ftp()

total_processados = 0
total_registros_baixados = 0
total_registros_filtrados = 0
total_bytes = 0

try:
    for ano, mes in meses_para_processar(qtd_meses):
        aa = ano % 100
        nome_arquivo = f"RD{uf}{aa:02d}{mes:02d}.dbc"
        print(f"Processando {nome_arquivo}...")

        conteudo_dbc = baixar_bytes(ftp, nome_arquivo)
        if conteudo_dbc is None:
            continue

        try:
            df_original = dbc_bytes_para_dataframe(conteudo_dbc, nome_arquivo)
        except Exception as exc:  # noqa: BLE001
            print(f"Arquivo corrompido, pulando '{nome_arquivo}': {exc}")
            continue

        df_filtrado = filtrar_cids_renais(df_original)
        df_filtrado = selecionar_colunas(df_filtrado)

        tamanho = salvar_parquet(filesystem_client, df_filtrado, ano, mes)

        total_processados += 1
        total_registros_baixados += len(df_original)
        total_registros_filtrados += len(df_filtrado)
        total_bytes += tamanho

        print(
            f"OK {nome_arquivo} | originais={len(df_original)} | "
            f"filtrados={len(df_filtrado)} | parquet={tamanho} bytes"
        )
finally:
    ftp.quit()

print("\n===== Resumo da execução - SIH-SUS (Databricks Job) =====")
print(f"Total de arquivos processados : {total_processados}")
print(f"Total de registros baixados   : {total_registros_baixados}")
print(f"Total de registros renais     : {total_registros_filtrados}")
print(f"Tamanho total gravado         : {total_bytes / (1024 * 1024):.2f} MB")
