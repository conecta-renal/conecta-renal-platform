"""
Ingestão do SIM (Sistema de Informações sobre Mortalidade) — Declarações
de Óbito — a partir do FTP público do DATASUS, filtrando registros com
CIDs de interesse renal para o Conecta Renal.

Uso:
    python ingest_sim.py

Variáveis de ambiente:
    DATASUS_UF             UF a ser baixada (default: SP)
    DATASUS_ANOS           Janela de anos anteriores à execução (default: 5)
    AZURE_STORAGE_ACCOUNT  Storage account do Data Lake (default: stconectarenaldev)
    AZURE_TENANT_ID        Tenant ID do Service Principal usado para autenticar no ADLS
    AZURE_CLIENT_ID        Client ID do Service Principal usado para autenticar no ADLS
    AZURE_CLIENT_SECRET    Client Secret do Service Principal usado para autenticar no ADLS

O resultado é gravado diretamente no Azure Data Lake Storage Gen2, no
container "bronze", particionado por ano (`sim/ano={ano}/data.parquet`)
— não em disco local.

Nota sobre o formato dos arquivos:
    Diferente do SIH/SIA-SUS/CNES, o SIM publica arquivos **anuais**, não
    mensais: `DO{UF}{AAAA}.dbc` (ex: `DOSP2024.dbc`). Também há defasagem
    maior de publicação (dados de mortalidade exigem investigação e
    codificação da causa de óbito) — o ano mais recente disponível costuma
    ficar 1-2 anos atrás do ano corrente.

    A extensão do arquivo varia entre `.dbc` e `.DBC` dependendo do ano
    (inconsistência histórica do próprio FTP do DATASUS) — por isso o
    pipeline lista o diretório uma vez por conexão e resolve o nome real
    do arquivo de forma case-insensitive, em vez de assumir a extensão.

    Layout confirmado contra um arquivo real do FTP (`DOSP2024.dbc`,
    351.616 óbitos, 87 colunas).
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from ftplib import FTP, error_perm
from pathlib import Path

import pandas as pd
import pyreaddbc
from azure.identity import ClientSecretCredential
from azure.storage.filedatalake import DataLakeServiceClient, FileSystemClient
from dbfread import DBF

FTP_HOST = "ftp.datasus.gov.br"
FTP_PORT = 21
FTP_USER = "anonymous"
FTP_PASSWORD = ""
FTP_REMOTE_DIR = "/dissemin/publicos/SIM/CID10/DORES"

CID_RENAIS = ("N18", "N17", "Z49", "Z940", "E11", "I10", "N04", "N03")

COLUNAS_RELEVANTES = [
    "DTOBITO", "IDADE", "SEXO", "RACACOR", "CODMUNRES", "CODESTAB",
    "CAUSABAS", "CAUSABAS_O", "CIRCOBITO", "ASSISTMED", "NECROPSIA",
]

MAX_TENTATIVAS = 3
BACKOFF_SEGUNDOS = 5

AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "stconectarenaldev")
AZURE_STORAGE_CONTAINER = "bronze"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = OUTPUT_DIR / "logs"
DOWNLOADS_DIR = OUTPUT_DIR / "_downloads"


def configurar_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"sim_{timestamp}.log"

    logger = logging.getLogger("ingest_sim")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def anos_para_processar(qtd_anos: int) -> list[int]:
    """Retorna os `qtd_anos` anos anteriores ao ano corrente (do mais
    antigo para o mais recente), já que o SIM publica arquivos anuais com
    defasagem — o ano corrente e o anterior geralmente ainda não estão
    disponíveis."""
    ano_atual = date.today().year
    return list(range(ano_atual - qtd_anos, ano_atual))


@dataclass
class ResultadoArquivo:
    nome_arquivo: str
    status: str  # "ok", "nao_encontrado", "corrompido", "erro"
    registros_originais: int = 0
    registros_filtrados: int = 0
    tamanho_parquet_bytes: int = 0
    tempo_execucao_segundos: float = 0.0


@dataclass
class ResumoExecucao:
    arquivos: list[ResultadoArquivo] = field(default_factory=list)

    @property
    def total_processados(self) -> int:
        return len(self.arquivos)

    @property
    def total_registros_baixados(self) -> int:
        return sum(a.registros_originais for a in self.arquivos)

    @property
    def total_registros_filtrados(self) -> int:
        return sum(a.registros_filtrados for a in self.arquivos)

    @property
    def tamanho_total_bytes(self) -> int:
        return sum(a.tamanho_parquet_bytes for a in self.arquivos)


def conectar_ftp(logger: logging.Logger) -> FTP:
    ultima_excecao: Exception | None = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            ftp = FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
            ftp.login(user=FTP_USER, passwd=FTP_PASSWORD)
            ftp.cwd(FTP_REMOTE_DIR)
            return ftp
        except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer erro de FTP
            ultima_excecao = exc
            logger.warning(
                "Falha ao conectar ao FTP (tentativa %s/%s): %s",
                tentativa, MAX_TENTATIVAS, exc,
            )
            if tentativa < MAX_TENTATIVAS:
                time.sleep(BACKOFF_SEGUNDOS)

    assert ultima_excecao is not None
    raise ultima_excecao


def listar_arquivos(ftp: FTP) -> dict[str, str]:
    """Lista o diretório uma vez e retorna um dict {NOME_MAIUSCULO: nome_real},
    para resolver a extensão .dbc/.DBC de forma case-insensitive."""
    arquivos = ftp.nlst()
    return {nome.upper(): nome for nome in arquivos}


def baixar_arquivo(ftp: FTP, nome_arquivo: str, local_path: Path, logger: logging.Logger) -> bool:
    """Baixa um arquivo do FTP (assume que o diretório remoto já é o
    diretório corrente da conexão) com retry. Retorna False se o arquivo
    não existir no servidor (550), sem lançar exceção."""
    ultima_excecao: Exception | None = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as fh:
                ftp.retrbinary(f"RETR {nome_arquivo}", fh.write)
            return True
        except error_perm as exc:
            if str(exc).startswith("550"):
                logger.warning("Arquivo não encontrado no FTP: %s", nome_arquivo)
                local_path.unlink(missing_ok=True)
                return False
            ultima_excecao = exc
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc

        logger.warning(
            "Falha ao baixar '%s' (tentativa %s/%s): %s",
            nome_arquivo, tentativa, MAX_TENTATIVAS, ultima_excecao,
        )
        if tentativa < MAX_TENTATIVAS:
            time.sleep(BACKOFF_SEGUNDOS)

    logger.error("Desistindo de baixar '%s' após %s tentativas.", nome_arquivo, MAX_TENTATIVAS)
    return False


def dbc_para_dataframe(dbc_path: Path) -> pd.DataFrame:
    """Descomprime um `.dbc` do DATASUS para `.dbf` (via pyreaddbc) e
    carrega o resultado em um DataFrame."""
    dbf_path = dbc_path.with_suffix(".dbf")
    pyreaddbc.dbc2dbf(str(dbc_path), str(dbf_path))
    try:
        tabela = DBF(str(dbf_path), load=True, encoding="latin-1", char_decode_errors="ignore")
        return pd.DataFrame(iter(tabela))
    finally:
        dbf_path.unlink(missing_ok=True)


def filtrar_cids_renais(df: pd.DataFrame) -> pd.DataFrame:
    causabas = df.get("CAUSABAS", pd.Series(dtype=str)).astype(str)
    causabas_o = df.get("CAUSABAS_O", pd.Series(dtype=str)).astype(str)
    mascara = causabas.str.startswith(CID_RENAIS) | causabas_o.str.startswith(CID_RENAIS)
    return df[mascara]


def selecionar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    colunas_existentes = [c for c in COLUNAS_RELEVANTES if c in df.columns]
    return df.reindex(columns=colunas_existentes)


def conectar_adls(logger: logging.Logger) -> FileSystemClient:
    """Autentica no Data Lake via Service Principal e retorna o client do
    container 'bronze', criando-o caso ainda não exista."""
    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )
    account_url = f"https://{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net"
    service_client = DataLakeServiceClient(account_url=account_url, credential=credential)

    filesystem_client = service_client.get_file_system_client(AZURE_STORAGE_CONTAINER)
    if not filesystem_client.exists():
        logger.info("Container '%s' não existe, criando...", AZURE_STORAGE_CONTAINER)
        filesystem_client.create_file_system()

    return filesystem_client


def salvar_parquet(filesystem_client: FileSystemClient, df: pd.DataFrame, ano: int) -> int:
    """Grava o DataFrame como Parquet no Data Lake (container bronze),
    particionado por ano. Retorna o tamanho em bytes do arquivo."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    conteudo = buffer.getvalue()

    caminho = f"sim/ano={ano}/data.parquet"
    file_client = filesystem_client.get_file_client(caminho)
    file_client.upload_data(conteudo, overwrite=True)

    return len(conteudo)


def processar_ano(
    ftp: FTP, arquivos_disponiveis: dict[str, str], filesystem_client: FileSystemClient,
    uf: str, ano: int, logger: logging.Logger,
) -> ResultadoArquivo:
    nome_esperado = f"DO{uf}{ano}.dbc"
    nome_arquivo = arquivos_disponiveis.get(nome_esperado.upper())

    inicio = time.monotonic()

    if nome_arquivo is None:
        logger.warning("Arquivo não encontrado no FTP: %s", nome_esperado)
        return ResultadoArquivo(nome_arquivo=nome_esperado, status="nao_encontrado")

    logger.info("Processando %s", nome_arquivo)
    local_path = DOWNLOADS_DIR / nome_arquivo

    baixou = baixar_arquivo(ftp, nome_arquivo, local_path, logger)
    if not baixou:
        return ResultadoArquivo(nome_arquivo=nome_arquivo, status="nao_encontrado")

    try:
        df_original = dbc_para_dataframe(local_path)
    except Exception as exc:  # noqa: BLE001 - descompressao/leitura pode falhar p/ arquivo corrompido
        logger.error("Arquivo corrompido, pulando '%s': %s", nome_arquivo, exc)
        local_path.unlink(missing_ok=True)
        return ResultadoArquivo(nome_arquivo=nome_arquivo, status="corrompido")

    total_original = len(df_original)

    df_filtrado = filtrar_cids_renais(df_original)
    df_filtrado = selecionar_colunas(df_filtrado)
    total_filtrado = len(df_filtrado)

    tamanho_parquet = salvar_parquet(filesystem_client, df_filtrado, ano)

    local_path.unlink(missing_ok=True)

    tempo_execucao = time.monotonic() - inicio

    logger.info(
        "OK %s | originais=%s | filtrados=%s | parquet=%s bytes | tempo=%.2fs",
        nome_arquivo, total_original, total_filtrado, tamanho_parquet, tempo_execucao,
    )

    return ResultadoArquivo(
        nome_arquivo=nome_arquivo,
        status="ok",
        registros_originais=total_original,
        registros_filtrados=total_filtrado,
        tamanho_parquet_bytes=tamanho_parquet,
        tempo_execucao_segundos=tempo_execucao,
    )


def imprimir_resumo(resumo: ResumoExecucao) -> None:
    tamanho_mb = resumo.tamanho_total_bytes / (1024 * 1024)
    print("\n===== Resumo da execução - SIM (Mortalidade) =====")
    print(f"Total de arquivos processados : {resumo.total_processados}")
    print(f"Total de registros baixados    : {resumo.total_registros_baixados}")
    print(f"Total de registros renais      : {resumo.total_registros_filtrados}")
    print(f"Tamanho total gravado          : {tamanho_mb:.2f} MB")
    print("====================================================\n")


def main() -> None:
    uf = os.getenv("DATASUS_UF", "SP").upper()
    qtd_anos = int(os.getenv("DATASUS_ANOS", "5"))

    logger = configurar_logger()
    logger.info("Iniciando ingestão SIM | UF=%s | janela=%s anos", uf, qtd_anos)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    resumo = ResumoExecucao()

    try:
        ftp = conectar_ftp(logger)
    except Exception as exc:  # noqa: BLE001
        logger.error("Não foi possível conectar ao FTP do DATASUS: %s", exc)
        return

    try:
        filesystem_client = conectar_adls(logger)
    except Exception as exc:  # noqa: BLE001
        logger.error("Não foi possível conectar ao Data Lake do Azure: %s", exc)
        ftp.close()
        return

    try:
        arquivos_disponiveis = listar_arquivos(ftp)
        for ano in anos_para_processar(qtd_anos):
            resultado = processar_ano(ftp, arquivos_disponiveis, filesystem_client, uf, ano, logger)
            resumo.arquivos.append(resultado)
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()

    logger.info("Ingestão finalizada.")
    imprimir_resumo(resumo)


if __name__ == "__main__":
    main()
