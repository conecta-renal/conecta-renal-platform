"""
Script de validação manual do pipeline de ingestão SIH-SUS.

Conecta no FTP do DATASUS, baixa APENAS UM arquivo (o mais recente
disponível para a UF configurada) para uma pasta temporária, exibe
estatísticas no terminal e apaga o arquivo em seguida — não persiste
nada em `output/` nem em qualquer outro local do disco.

Uso:
    python test_ingest_sih.py

Objetivo: validar a conexão FTP, a estrutura do arquivo (.dbc) e o filtro
de CIDs renais antes de rodar o pipeline completo (`ingest_sih.py`).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from ftplib import error_perm
from pathlib import Path

from ingest_sih import (
    CID_RENAIS,
    conectar_ftp,
    dbc_para_dataframe,
    filtrar_cids_renais,
)

UF_TESTE = "SP"
MESES_A_TENTAR = 3


def logger_simples() -> logging.Logger:
    logger = logging.getLogger("test_ingest_sih")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    return logger


def ultimos_meses(qtd: int) -> list[tuple[int, int]]:
    """Retorna os últimos `qtd` meses (mais recente primeiro), ignorando
    o mês corrente (geralmente ainda não publicado no DATASUS)."""
    hoje = date.today()
    ano, mes = hoje.year, hoje.month

    meses: list[tuple[int, int]] = []
    for _ in range(qtd):
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1
        meses.append((ano, mes))
    return meses


def encontrar_arquivo_mais_recente(ftp, uf: str, logger: logging.Logger) -> str | None:
    """Tenta localizar, entre os últimos MESES_A_TENTAR meses, o primeiro
    arquivo .dbc existente no FTP (assume que a conexão já está no
    diretório remoto correto). Retorna o nome do arquivo ou None."""
    for ano, mes in ultimos_meses(MESES_A_TENTAR):
        aa = ano % 100
        nome_arquivo = f"RD{uf}{aa:02d}{mes:02d}.dbc"

        try:
            tamanho = ftp.size(nome_arquivo)
            if tamanho is not None:
                logger.info("Arquivo encontrado: %s (%s bytes)", nome_arquivo, tamanho)
                return nome_arquivo
        except error_perm:
            logger.info("Não encontrado: %s. Tentando mês anterior...", nome_arquivo)
            continue

    return None


def main() -> None:
    logger = logger_simples()
    logger.info("Conectando ao FTP do DATASUS (host=ftp.datasus.gov.br, porta=21, usuário=anonymous)...")

    ftp = conectar_ftp(logger)
    logger.info("Conexão FTP estabelecida com sucesso.")

    try:
        nome_arquivo = encontrar_arquivo_mais_recente(ftp, UF_TESTE, logger)
        if nome_arquivo is None:
            logger.error(
                "Nenhum arquivo encontrado para UF=%s nos últimos %s meses.",
                UF_TESTE, MESES_A_TENTAR,
            )
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            local_path = Path(tmp_dir) / nome_arquivo

            logger.info("Baixando '%s' para pasta temporária...", nome_arquivo)
            with open(local_path, "wb") as fh:
                ftp.retrbinary(f"RETR {nome_arquivo}", fh.write)

            logger.info("Descomprimindo .dbc e convertendo para DataFrame...")
            df = dbc_para_dataframe(local_path)
            # `local_path` está em um diretório temporário que será apagado
            # automaticamente ao sair do bloco `with` — nada fica em disco.

        df_filtrado = filtrar_cids_renais(df)

        print("\n===== Validação do arquivo:", nome_arquivo, "=====\n")

        print("Colunas disponíveis:")
        print(list(df.columns))

        print(f"\nTotal de registros: {len(df)}")

        print("\n5 primeiras linhas:")
        print(df.head(5).to_string())

        if "DIAG_PRINC" in df.columns:
            valores_unicos = df["DIAG_PRINC"].astype(str).unique()[:20]
            print(f"\nValores únicos de DIAG_PRINC (primeiros 20 de {df['DIAG_PRINC'].nunique()}):")
            print(list(valores_unicos))
        else:
            print("\nColuna DIAG_PRINC não encontrada neste arquivo.")

        print(f"\nCIDs renais filtrados ({', '.join(CID_RENAIS)}):")
        print(f"Total de registros com CID renal: {len(df_filtrado)}")

        print("\n===================================================\n")

    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()


if __name__ == "__main__":
    main()
