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
