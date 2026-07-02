# Conecta Renal Platform

![Terraform](https://img.shields.io/badge/Terraform-%3E%3D1.5-844FBA?logo=terraform&logoColor=white)
![Azure](https://img.shields.io/badge/Azure-Cloud-0078D4?logo=microsoftazure&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Sobre o projeto

**Conecta Renal** é uma plataforma de orquestração clínica voltada para o
acompanhamento de pacientes renais. A plataforma integra dados de múltiplas
fontes (prontuários, exames laboratoriais, DataSUS, comunicação via WhatsApp)
em um pipeline de dados moderno na Azure, utilizando Databricks para
processamento e Power BI/Power Apps para visualização e ação clínica.

## Arquitetura

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

Mais detalhes em [docs/arquitetura.md](docs/arquitetura.md).

## Pré-requisitos

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) instalado e autenticado
- [Terraform](https://developer.hashicorp.com/terraform/downloads) `>= 1.5.0`
- Acesso a uma assinatura (subscription) Azure com permissões para criar recursos
- Um Service Principal com permissão `Contributor` na assinatura (usado pelo Terraform)

## Configuração do ambiente local

1. Clone o repositório:
   ```bash
   git clone <url-do-repositorio>
   cd conecta-renal-platform
   ```

2. Faça login na Azure:
   ```bash
   az login --tenant <TENANT_ID>
   ```

3. Copie o arquivo de exemplo de variáveis e preencha com valores reais:
   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars
   ```
   Edite `terraform.tfvars` com os valores da sua assinatura, tenant e
   Service Principal. **Nunca faça commit deste arquivo** (já está no `.gitignore`).

4. Inicialize o Terraform:
   ```bash
   terraform init
   ```

## Rodando o `terraform plan` localmente

Dentro da pasta `infra/`, com o `terraform.tfvars` já configurado:

```bash
terraform fmt -check
terraform validate
terraform plan
```

## Variáveis de ambiente necessárias

| Variável            | Descrição                                              |
|---------------------|---------------------------------------------------------|
| `subscription_id`   | ID da assinatura Azure                                  |
| `tenant_id`         | ID do tenant Microsoft Entra ID                          |
| `client_id`         | Client ID do Service Principal usado pelo Terraform      |
| `client_secret`     | Client Secret do Service Principal usado pelo Terraform  |
| `location`          | Região Azure (padrão: `brazilsouth`)                     |
| `environment`       | Ambiente de deploy (padrão: `dev`)                        |
| `project_name`      | Nome do projeto (padrão: `conecta-renal`)                 |

No GitHub Actions, essas credenciais são fornecidas via **Secrets**:
`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.

## Estrutura de pastas

```
conecta-renal-platform/
├── infra/                        # Infraestrutura como código (Terraform)
│   ├── main.tf                   # Definição dos recursos Azure
│   ├── variables.tf              # Variáveis de entrada
│   ├── outputs.tf                # Outputs expostos após o apply
│   └── terraform.tfvars.example  # Exemplo de valores para as variáveis
├── .github/
│   └── workflows/
│       └── terraform.yml         # Pipeline de CI/CD (plan em PR, apply em main)
├── docs/
│   └── arquitetura.md            # Documentação da arquitetura
├── README.md
└── .gitignore
```

## Contribuição

Padrão de nomenclatura de branches:

- `feature/<nome-da-feature>` — novas funcionalidades
- `fix/<nome-do-bug>` — correções de bugs
- `infra/<nome-da-mudanca>` — mudanças de infraestrutura (Terraform, CI/CD)

Pull Requests para `main` disparam automaticamente `terraform plan` via
GitHub Actions. Merges em `main` disparam `terraform apply`.

## Licença

Distribuído sob a licença MIT.
