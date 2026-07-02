-- Cria a tabela Delta "bronze_sih" a partir dos arquivos Parquet gravados
-- pelo pipeline `ingest_sih.py` no container "bronze" do Data Lake.
--
-- Rodar manualmente no Databricks SQL Editor, conectado ao SQL Warehouse
-- "sqlwh-conecta-renal-dev" (provisionado via Terraform em infra/main.tf),
-- depois que o pipeline de ingestão já tiver gravado ao menos um mês de
-- dados no bronze.
--
-- Reexecutar este script substitui a tabela pelo estado mais recente do
-- bronze (útil para reprocessar depois de novas cargas do pipeline).

CREATE OR REPLACE TABLE bronze_sih
USING DELTA
LOCATION 'abfss://bronze@stconectarenaldev.dfs.core.windows.net/delta/sih'
AS
SELECT *
FROM parquet.`abfss://bronze@stconectarenaldev.dfs.core.windows.net/sih/*/*/*.parquet`;
