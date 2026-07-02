variable "subscription_id" {
  type        = string
  description = "ID da assinatura (subscription) Azure onde os recursos do Conecta Renal serão provisionados."
}

variable "tenant_id" {
  type        = string
  description = "ID do tenant Microsoft Entra ID associado à assinatura Azure."
}

variable "client_id" {
  type        = string
  description = "Client ID (App ID) do Service Principal usado para autenticação do Terraform na Azure."
}

variable "client_secret" {
  type        = string
  description = "Client Secret do Service Principal usado para autenticação do Terraform na Azure."
  sensitive   = true
}

variable "location" {
  type        = string
  description = "Região Azure onde os recursos serão provisionados."
  default     = "brazilsouth"
}

variable "environment" {
  type        = string
  description = "Nome do ambiente de deploy (ex: dev, staging, prod), usado em nomes de recursos e tags."
  default     = "dev"
}

variable "project_name" {
  type        = string
  description = "Nome do projeto, usado como prefixo/sufixo na nomenclatura dos recursos e em tags."
  default     = "conecta-renal"
}
