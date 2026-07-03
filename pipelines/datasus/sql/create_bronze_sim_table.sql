-- Cria a tabela Delta "bronze_sim" a partir dos arquivos Parquet gravados
-- pelo pipeline `ingest_sim.py` no container "bronze" do Data Lake
-- (SIM - Mortalidade, já filtrado por CIDs renais).
--
-- Rodar manualmente no Databricks SQL Editor, conectado ao SQL Warehouse
-- "sqlwh-conecta-renal-dev" (provisionado via Terraform em infra/main.tf),
-- depois que o pipeline de ingestão já tiver gravado ao menos um ano de
-- dados no bronze.
--
-- Reexecutar este script substitui a tabela pelo estado mais recente do
-- bronze (útil para reprocessar depois de novas cargas do pipeline).
--
-- Nota: diferente do SIH/ATD/CNES (particionados por ano E mês), o SIM é
-- particionado só por ano (`sim/ano={ano}/data.parquet`), pois o DATASUS
-- publica o SIM anualmente.

CREATE OR REPLACE TABLE bronze_sim
USING DELTA
LOCATION 'abfss://bronze@stconectarenaldev.dfs.core.windows.net/delta/sim'
AS
SELECT *
FROM parquet.`abfss://bronze@stconectarenaldev.dfs.core.windows.net/sim/*/*.parquet`;
