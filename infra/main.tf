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

locals {
  common_tags = {
    project     = var.project_name
    environment = var.environment
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
  sku                 = "standard"

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
