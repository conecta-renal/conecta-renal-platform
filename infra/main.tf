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
# Databricks Job - ingestao SIH-SUS (equivalente a um Glue Job: cluster
# efemero que sobe so para a execucao e desliga ao final)
# ---------------------------------------------------------------------------

data "databricks_spark_version" "latest_lts" {
  long_term_support = true
}

data "databricks_node_type" "smallest" {
  local_disk = true
}

resource "databricks_notebook" "ingest_sih_job" {
  path     = "/Shared/conecta-renal/ingest_sih_job"
  language = "PYTHON"
  source   = "${path.module}/../pipelines/datasus/databricks/ingest_sih_job.py"
}

resource "databricks_job" "ingest_sih" {
  name = "job-ingest-sih-conecta-renal"

  job_cluster {
    job_cluster_key = "main"

    new_cluster {
      spark_version = data.databricks_spark_version.latest_lts.id
      node_type_id  = data.databricks_node_type.smallest.id
      num_workers   = 1
    }
  }

  task {
    task_key        = "ingest"
    job_cluster_key = "main"

    notebook_task {
      notebook_path = databricks_notebook.ingest_sih_job.path
      base_parameters = {
        uf    = "SP"
        meses = "3"
      }
    }
  }
}
