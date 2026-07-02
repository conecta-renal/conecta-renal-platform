# Conecta Renal - infraestrutura Azure via Terraform
terraform {
  required_version = ">= 1.5.0"

  backend "azurerm" {
    # Os valores de resource_group_name, storage_account_name, container_name
    # e key são fornecidos em tempo de init via -backend-config
    # (ver .github/workflows/terraform.yml), para não fixar valores sensíveis
    # ou específicos de ambiente diretamente no código.
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~>2.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~>1.0"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
  }

  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  client_id       = var.client_id
  client_secret   = var.client_secret
}

provider "azuread" {
  tenant_id     = var.tenant_id
  client_id     = var.client_id
  client_secret = var.client_secret
}

provider "databricks" {
  host                        = azurerm_databricks_workspace.main.workspace_url
  azure_client_id             = var.client_id
  azure_client_secret         = var.client_secret
  azure_tenant_id             = var.tenant_id
  azure_workspace_resource_id = azurerm_databricks_workspace.main.id
}

locals {
  common_tags = {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------

resource "azurerm_resource_group" "main" {
  name     = "rg-conecta-renal-dev"
  location = var.location
  tags     = local.common_tags
}

# ---------------------------------------------------------------------------
# Azure Data Lake Storage Gen2 (ADLS)
# ---------------------------------------------------------------------------

resource "azurerm_storage_account" "datalake" {
  name                     = "stconectarenaldev"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true

  tags = local.common_tags
}

resource "azurerm_storage_container" "bronze" {
  name                  = "bronze"
  storage_account_name  = azurerm_storage_account.datalake.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "silver" {
  name                  = "silver"
  storage_account_name  = azurerm_storage_account.datalake.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "gold" {
  name                  = "gold"
  storage_account_name  = azurerm_storage_account.datalake.name
  container_access_type = "private"
}

# ---------------------------------------------------------------------------
# Azure Data Factory (ADF)
# ---------------------------------------------------------------------------

resource "azurerm_data_factory" "main" {
  name                = "adf-conecta-renal-dev"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Azure Databricks Workspace
# ---------------------------------------------------------------------------

resource "azurerm_databricks_workspace" "main" {
  name                = "dbw-conecta-renal-dev"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "premium"

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Azure Key Vault
# ---------------------------------------------------------------------------

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                       = "kv-conecta-renal-dev"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  access_policy {
    tenant_id = var.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Purge", "Recover"
    ]
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Microsoft Entra ID - Grupos
# ---------------------------------------------------------------------------

resource "azuread_group" "admins" {
  display_name     = "conecta-renal-admins"
  security_enabled = true
}

resource "azuread_group" "engenheiros" {
  display_name     = "conecta-renal-engenheiros"
  security_enabled = true
}

resource "azuread_group" "readonly" {
  display_name     = "conecta-renal-readonly"
  security_enabled = true
}

# ---------------------------------------------------------------------------
# Databricks SQL Warehouse + acesso ao ADLS (Hive metastore classico)
# ---------------------------------------------------------------------------

resource "databricks_sql_endpoint" "main" {
  name             = "sqlwh-conecta-renal-dev"
  cluster_size     = "2X-Small"
  auto_stop_mins   = 10
  min_num_clusters = 1
  max_num_clusters = 1

  # Serverless: nao consome a cota de VM da assinatura (roda em capacidade
  # gerenciada do proprio Databricks). Necessario aqui porque a assinatura
  # tem cota regional de apenas 4 vCPUs totais em brazilsouth - um
  # warehouse classico (com VM dedicada) trava indefinidamente em
  # "CREATING" tentando provisionar VMs que a cota nao permite.
  enable_serverless_compute = true
  warehouse_type            = "PRO"
}

# O Databricks tem seu proprio modelo de permissoes (separado do RBAC do
# Azure). Sem isso, o warehouse fica visivel/utilizavel apenas para o
# Service Principal que o criou via Terraform, nao para os usuarios
# humanos do workspace (mesmo sendo admins da assinatura Azure).
resource "databricks_permissions" "sql_endpoint_usage" {
  sql_endpoint_id = databricks_sql_endpoint.main.id

  access_control {
    group_name       = "users"
    permission_level = "CAN_USE"
  }
}

# Secret scope + secret com a chave da conta de armazenamento, usados para
# dar ao SQL Warehouse acesso de leitura/escrita ao ADLS via
# databricks_sql_global_config abaixo. A chave nunca fica em texto puro no
# codigo: e lida diretamente do state do recurso azurerm_storage_account.
resource "databricks_secret_scope" "adls" {
  name = "conecta-renal-adls"
}

resource "databricks_secret" "adls_storage_key" {
  scope        = databricks_secret_scope.adls.id
  key          = "storage-account-key"
  string_value = azurerm_storage_account.datalake.primary_access_key
}

resource "databricks_sql_global_config" "this" {
  security_policy = "DATA_ACCESS_CONTROL"

  data_access_config = {
    "spark.hadoop.fs.azure.account.key.${azurerm_storage_account.datalake.name}.dfs.core.windows.net" = "{{secrets/${databricks_secret_scope.adls.name}/${databricks_secret.adls_storage_key.key}}}"
  }
}

# ---------------------------------------------------------------------------
# Unity Catalog - acesso ao ADLS via External Location
#
# O workspace usa Unity Catalog (confirmado: catalogo "dbw_conecta_renal_dev"
# ja existe por padrao). Warehouses serverless *exigem* Unity Catalog para
# acessar dados externos (abfss://) - o databricks_sql_global_config acima
# (baseado em chave de storage, estilo Hive metastore classico) nao se
# aplica aqui. Sem uma External Location registrada, qualquer CREATE
# TABLE/leitura apontando para o storage account falha com
# NO_PARENT_EXTERNAL_LOCATION_FOR_PATH.
# ---------------------------------------------------------------------------

resource "azurerm_databricks_access_connector" "adls" {
  name                = "dbac-conecta-renal-adls"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags
}

resource "azurerm_role_assignment" "access_connector_storage" {
  scope                = azurerm_storage_account.datalake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.adls.identity[0].principal_id
}

resource "databricks_storage_credential" "adls" {
  name = "cred-conecta-renal-adls"

  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.adls.id
  }

  depends_on = [azurerm_role_assignment.access_connector_storage]
}

resource "databricks_external_location" "bronze" {
  name            = "ext-loc-conecta-renal-bronze"
  url             = "abfss://bronze@${azurerm_storage_account.datalake.name}.dfs.core.windows.net/"
  credential_name = databricks_storage_credential.adls.name

  depends_on = [databricks_storage_credential.adls]
}

# Concede a todos os usuarios da conta permissao para ler/escrever arquivos
# e criar tabelas externas sobre essa External Location - sem isso, so o
# Service Principal que a criou consegue usa-la (mesma questao de
# visibilidade do SQL Warehouse/Job).
resource "databricks_grants" "bronze_external_location" {
  external_location = databricks_external_location.bronze.name

  grant {
    principal  = "account users"
    privileges = ["CREATE_EXTERNAL_TABLE", "READ_FILES", "WRITE_FILES"]
  }
}

# ---------------------------------------------------------------------------
# Databricks Job - ingestao SIH-SUS (equivalente a um Glue Job: compute
# efemero que sobe so para a execucao e desliga ao final)
# ---------------------------------------------------------------------------

resource "databricks_notebook" "ingest_sih_job" {
  path     = "/Shared/conecta-renal/ingest_sih_job"
  language = "PYTHON"
  source   = "${path.module}/../pipelines/datasus/databricks/ingest_sih_job.py"
}

resource "databricks_job" "ingest_sih" {
  name = "job-ingest-sih-conecta-renal"

  # Sem job_cluster/new_cluster: o task roda em compute serverless. Mesma
  # razao do SQL Warehouse acima - a assinatura tem cota de apenas 4 vCPUs
  # totais em brazilsouth, insuficiente para um cluster classico (driver +
  # worker), que travaria indefinidamente tentando provisionar VMs.
  task {
    task_key = "ingest"

    notebook_task {
      notebook_path = databricks_notebook.ingest_sih_job.path
      base_parameters = {
        uf    = "SP"
        meses = "3"
      }
    }
  }
}

# Mesma questao de visibilidade do SQL Warehouse: sem isso, so o Service
# Principal que criou o job (via Terraform) consegue ve-lo/roda-lo.
resource "databricks_permissions" "job_usage" {
  job_id = databricks_job.ingest_sih.id

  access_control {
    group_name       = "users"
    permission_level = "CAN_MANAGE_RUN"
  }
}
