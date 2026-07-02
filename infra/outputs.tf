output "resource_group_name" {
  description = "Nome do Resource Group onde os recursos do Conecta Renal foram provisionados."
  value       = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Nome da conta de armazenamento (Data Lake Gen2) usada para os dados bronze/silver/gold."
  value       = azurerm_storage_account.datalake.name
}

output "storage_account_primary_endpoint" {
  description = "Endpoint primário (data lake gen2 / dfs) da conta de armazenamento."
  value       = azurerm_storage_account.datalake.primary_dfs_endpoint
}

output "databricks_workspace_url" {
  description = "URL de acesso ao workspace do Azure Databricks."
  value       = azurerm_databricks_workspace.main.workspace_url
}

output "data_factory_name" {
  description = "Nome do recurso Azure Data Factory provisionado."
  value       = azurerm_data_factory.main.name
}

output "key_vault_uri" {
  description = "URI do Azure Key Vault usado para armazenar secrets das APIs externas (DataSUS, LIS, WhatsApp)."
  value       = azurerm_key_vault.main.vault_uri
}

output "databricks_sql_warehouse_name" {
  description = "Nome do SQL Warehouse do Databricks usado para consultas SQL sobre as tabelas (ex: Power BI, SQL Editor)."
  value       = databricks_sql_endpoint.main.name
}
