"""
Ingestão do SIH-SUS (Sistema de Informações Hospitalares) a partir do FTP
público do DATASUS, filtrando registros com CIDs de interesse renal para
o Conecta Renal.

Uso:
    python ingest_sih.py

Variáveis de ambiente:
    DATASUS_UF     UF a ser baixada (default: SP)
    DATASUS_MESES  Janela de meses anteriores à execução (default: 24)

Nota sobre o formato dos arquivos:
    O FTP do DATASUS distribui o SIH-SUS em uma única pasta (sem
    subdiretórios por ano) e em formato `.dbc` — um DBF comprimido com um
    algoritmo proprietário (PKWare/blast), não legível diretamente pelo
    `dbfread`. Por isso cada arquivo é descomprimido para `.dbf` com
    `pyreaddbc.dbc2dbf` antes da leitura.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from ftplib import FTP, error_perm
from pathlib import Path

import pandas as pd
import pyreaddbc
from dbfread import DBF

FTP_HOST = "ftp.datasus.gov.br"
FTP_PORT = 21
FTP_USER = "anonymous"
FTP_PASSWORD = ""

# Pasta única no FTP com todos os arquivos de 2008 em diante (não há
# subpastas por ano). A pasta "DBF/{ano}" mencionada em versões antigas de
# documentação é um acervo legado, parado em 2014-05.
FTP_REMOTE_DIR = "/dissemin/publicos/SIHSUS/200801_/Dados"

CID_RENAIS = ("N18", "N17", "Z49", "Z940", "E11", "I10", "N04", "N03")

COLUNAS_RELEVANTES = [
    "N_AIH", "DT_INTER", "DT_SAIDA", "DIAG_PRINC", "DIAG_SECUN",
    "MUNIC_RES", "NASC", "SEXO", "IDADE", "MORTE", "DIAS_PERM",
    "VAL_TOT", "PROC_REA", "CNES", "ANO_CMPT", "MES_CMPT",
]

MAX_TENTATIVAS = 3
BACKOFF_SEGUNDOS = 5

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
BRONZE_DIR = OUTPUT_DIR / "bronze" / "sih"
LOGS_DIR = OUTPUT_DIR / "logs"
DOWNLOADS_DIR = OUTPUT_DIR / "_downloads"


def configurar_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"sih_{timestamp}.log"

    logger = logging.getLogger("ingest_sih")
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


def meses_para_processar(qtd_meses: int) -> list[tuple[int, int]]:
    """Retorna [(ano, mes), ...] para os `qtd_meses` meses anteriores à
    execução, do mais antigo para o mais recente. O mês corrente é
    ignorado, pois o DATASUS costuma publicar apenas meses fechados."""
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
    diag_princ = df.get("DIAG_PRINC", pd.Series(dtype=str)).astype(str)
    diag_secun = df.get("DIAG_SECUN", pd.Series(dtype=str)).astype(str)

    mascara = diag_princ.str.startswith(CID_RENAIS) | diag_secun.str.startswith(CID_RENAIS)
    return df[mascara]


def selecionar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    colunas_existentes = [c for c in COLUNAS_RELEVANTES if c in df.columns]
    return df.reindex(columns=colunas_existentes)


def salvar_parquet(df: pd.DataFrame, ano: int, mes: int) -> Path:
    destino_dir = BRONZE_DIR / f"ano={ano}" / f"mes={mes:02d}"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino_path = destino_dir / "data.parquet"
    df.to_parquet(destino_path, index=False)
    return destino_path


def processar_mes(ftp: FTP, uf: str, ano: int, mes: int, logger: logging.Logger) -> ResultadoArquivo:
    aa = ano % 100
    nome_arquivo = f"RD{uf}{aa:02d}{mes:02d}.dbc"
    local_path = DOWNLOADS_DIR / nome_arquivo

    inicio = time.monotonic()
    logger.info("Processando %s", nome_arquivo)

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

    destino_path = salvar_parquet(df_filtrado, ano, mes)
    tamanho_parquet = destino_path.stat().st_size

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
    print("\n===== Resumo da execução - SIH-SUS =====")
    print(f"Total de arquivos processados : {resumo.total_processados}")
    print(f"Total de registros baixados   : {resumo.total_registros_baixados}")
    print(f"Total de registros renais     : {resumo.total_registros_filtrados}")
    print(f"Tamanho total em disco        : {tamanho_mb:.2f} MB")
    print("=========================================\n")


def main() -> None:
    uf = os.getenv("DATASUS_UF", "SP").upper()
    qtd_meses = int(os.getenv("DATASUS_MESES", "24"))

    logger = configurar_logger()
    logger.info("Iniciando ingestão SIH-SUS | UF=%s | janela=%s meses", uf, qtd_meses)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    resumo = ResumoExecucao()

    try:
        ftp = conectar_ftp(logger)
    except Exception as exc:  # noqa: BLE001
        logger.error("Não foi possível conectar ao FTP do DATASUS: %s", exc)
        return

    try:
        for ano, mes in meses_para_processar(qtd_meses):
            resultado = processar_mes(ftp, uf, ano, mes, logger)
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
