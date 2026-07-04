# Arquitetura — Conecta Renal

Este documento descreve a arquitetura de dados e infraestrutura da plataforma
Conecta Renal.

## Visão geral

A plataforma segue uma arquitetura em camadas (medallion architecture) sobre
Azure Data Lake Storage Gen2, orquestrada pelo Azure Data Factory e processada
pelo Azure Databricks.

```
Fontes externas (DataSUS, LIS, WhatsApp)
        |
        v
   [ Ingestão ]  --(Azure Data Factory)--
        |
        v
   [ Bronze ]  dados brutos, formato original
        |
        v
   [ Silver ]  dados limpos e conformados
        |
        v
   [ Gold ]    dados agregados, prontos para consumo
        |
        v
   Power Apps / Power BI / Automação
```

## Componentes de infraestrutura

- **Resource Group**: `rg-conecta-renal-dev` — agrupa todos os recursos do ambiente.
- **Azure Data Lake Storage Gen2**: armazenamento hierárquico com os containers
  `bronze`, `silver` e `gold`.
- **Azure Data Factory**: orquestração de pipelines de ingestão e transformação,
  com managed identity habilitada.
- **Azure Databricks**: processamento e transformação dos dados entre as camadas.
- **Azure Key Vault**: armazenamento seguro de secrets de integrações externas
  (DataSUS, LIS, WhatsApp).
- **Microsoft Entra ID**: controle de acesso via grupos (`conecta-renal-admins`,
  `conecta-renal-engenheiros`, `conecta-renal-readonly`).

## Infraestrutura como código

Toda a infraestrutura é provisionada via Terraform, localizada em [`infra/`](../infra),
com pipeline de CI/CD em [`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml).

## Fluxo de dados: ingestão DATASUS (SIH-SUS e SIA-SUS)

Esta seção descreve, na prática, onde cada etapa dos pipelines DATASUS
acontece hoje — importante porque **nenhuma etapa roda "no GitHub"**: o
GitHub guarda só o código-fonte e, num dos dois caminhos abaixo, empresta
uma máquina temporária para executar o script. Todo dado real (baixado do
FTP, filtrado, gravado) passa a existir exclusivamente no Data Lake.

O fluxo é o mesmo para as duas fontes hoje implementadas — muda só o
subcaminho no bronze e o nome da tabela final:

| Fonte | Pasta no bronze | Tabela Delta |
|---|---|---|
| SIH-SUS (internações) | `bronze/sih/` | `bronze_sih` |
| SIA-SUS — ATD (diálise) | `bronze/atd/` | `bronze_atd` |
| CNES (estabelecimentos) | `bronze/cnes/` | `bronze_cnes` |
| SIM (mortalidade) | `bronze/sim/` (só por ano, sem mês) | `bronze_sim` |

```
FTP DATASUS (anônimo)
        |
        v
[ compute que roda o script de ingestão ]  <- duas opções, mesmo destino
        |
        v
ADLS Gen2 - container "bronze"
  bronze/{sih|atd}/ano={ano}/mes={mes}/data.parquet   (Parquet cru, um arquivo por mês)
        |
        v
[ SQL rodado manualmente no Databricks SQL Editor ]
        |
        v
ADLS Gen2 - container "bronze"
  bronze/delta/{sih|atd}/   (tabela Delta, catalogada no Unity Catalog)
        |
        v
Consulta via Databricks SQL Warehouse (sqlwh-conecta-renal-dev) / Power BI
```

> Ver `pipelines/datasus/README.md` para detalhes de cada fonte.

### Etapa 1 — Carga (bronze cru)

Duas formas de disparar, ambas escrevendo direto no ADLS via SDK do Azure
(nenhuma persiste dado no GitHub):

| Fonte | Onde dispara | Script | Onde processa | Arquivo |
|---|---|---|---|---|
| SIH-SUS | Databricks (Jobs e Pipelines → `job-ingest-sih-conecta-renal` → Run now) | `pipelines/datasus/databricks/ingest_sih_job.py` | Cluster serverless do Databricks | notebook |
| SIH-SUS | GitHub Actions (`ingest-sih.yml`, `workflow_dispatch`) | `pipelines/datasus/ingest_sih.py` | Runner temporário do GitHub (destruído ao final) | script CLI |
| SIA-SUS (ATD) | Databricks (Jobs e Pipelines → `job-ingest-atd-conecta-renal` → Run now) | `pipelines/datasus/databricks/ingest_atd_job.py` | Cluster serverless do Databricks | notebook |
| SIA-SUS (ATD) | GitHub Actions (`ingest-atd.yml`, `workflow_dispatch`) | `pipelines/datasus/ingest_atd.py` | Runner temporário do GitHub (destruído ao final) | script CLI |
| CNES | Databricks (Jobs e Pipelines → `job-ingest-cnes-conecta-renal` → Run now) | `pipelines/datasus/databricks/ingest_cnes_job.py` | Cluster serverless do Databricks | notebook |
| CNES | GitHub Actions (`ingest-cnes.yml`, `workflow_dispatch`) | `pipelines/datasus/ingest_cnes.py` | Runner temporário do GitHub (destruído ao final) | script CLI |
| SIM | Databricks (Jobs e Pipelines → `job-ingest-sim-conecta-renal` → Run now) | `pipelines/datasus/databricks/ingest_sim_job.py` | Cluster serverless do Databricks | notebook |
| SIM | GitHub Actions (`ingest-sim.yml`, `workflow_dispatch`) | `pipelines/datasus/ingest_sim.py` | Runner temporário do GitHub (destruído ao final) | script CLI |

### Etapa 2 — Criação/atualização da tabela Delta

**Manual hoje**: rodar o script SQL correspondente
(`create_bronze_sih_table.sql`, `create_bronze_atd_table.sql`,
`create_bronze_cnes_table.sql` ou `create_bronze_sim_table.sql`) no
Databricks SQL Editor (conectado ao warehouse `sqlwh-conecta-renal-dev`)
depois de cada carga nova. Lê o Parquet cru e recria a tabela Delta
correspondente, catalogada no Unity Catalog via a External Location
`ext-loc-conecta-renal-bronze` (definida em `infra/main.tf`).

### Próximos passos planejados

- [ ] **Automatizar a etapa 2**: hoje a criação/refresh da tabela Delta
  ainda é manual (rodar o SQL à mão após cada carga). Precisa virar um job
  disparado automaticamente após a ingestão — candidatos: encadear como
  segunda task nos `databricks_job.*` (Terraform), ou um Databricks Job
  separado agendado, ou um pipeline do Azure Data Factory orquestrando as
  duas etapas.
- [x] ~~Avaliar se a ingestão (etapa 1) também deve ganhar agendamento
  automático~~ — feito: os 4 Databricks Jobs (SIH, ATD, CNES, SIM) rodam
  sozinhos todo dia 5 de cada mês (horários escalonados entre 06h-09h,
  horário de Brasília), via bloco `schedule` no Terraform. Ainda podem ser
  disparados manualmente a qualquer momento.
