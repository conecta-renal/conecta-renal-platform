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

## Passos manuais realizados fora da pipeline

A pipeline (`terraform.yml` / `bootstrap.yml`) cobre a maior parte do
provisionamento, mas algumas ações precisaram ser feitas manualmente via
Azure CLI/Portal, fora de qualquer workflow. **Ao replicar este ambiente
para produção, refaça os passos abaixo antes de rodar a pipeline:**

1. **Criação do Service Principal usado pelo Terraform/GitHub Actions**
   ```bash
   az ad sp create-for-rbac --name "github-actions-conecta-renal" \
     --role Contributor \
     --scopes /subscriptions/<SUBSCRIPTION_ID>
   ```
   O `appId`/`password`/`tenant` retornados viram os secrets `AZURE_CLIENT_ID`,
   `AZURE_CLIENT_SECRET` e `AZURE_TENANT_ID` no GitHub.

2. **Registro do Resource Provider `Microsoft.Storage` na assinatura**
   Necessário antes de criar qualquer Storage Account (inclusive o backend
   do Terraform). Sem isso, `az storage account create` falha com erro
   `SubscriptionNotFound` (mensagem enganosa — o problema real é o provider
   não registrado).
   ```bash
   az provider register --namespace Microsoft.Storage
   az provider show --namespace Microsoft.Storage --query registrationState -o tsv
   # aguardar até retornar "Registered" (pode levar alguns minutos)
   ```

3. **Concessão de permissão Microsoft Graph ao Service Principal para criar
   grupos no Entra ID** (`azuread_group.*` no `main.tf`)
   Sem isso, o `terraform apply` falha com
   `Authorization_RequestDenied: Insufficient privileges to complete the operation`.
   ```bash
   az ad app permission add --id <APP_ID_DO_SERVICE_PRINCIPAL> \
     --api 00000003-0000-0000-c000-000000000000 \
     --api-permissions 62a82d76-70ea-41e2-9197-370581804d09=Role
   # 62a82d76-70ea-41e2-9197-370581804d09 = Group.ReadWrite.All (Application)

   az ad app permission admin-consent --id <APP_ID_DO_SERVICE_PRINCIPAL>
   ```
   ⚠️ `Group.ReadWrite.All` dá ao Service Principal permissão para
   criar/editar/excluir **qualquer** grupo do tenant, não só os grupos do
   projeto. Avalie se em produção vale a pena restringir esse escopo
   (ex: criar os grupos manualmente e remover os recursos `azuread_group`
   do Terraform), dependendo da política de segurança da organização.

4. **Concessão de role RBAC de dados ao Service Principal no storage
   account** (necessário para `pipelines/datasus/ingest_sih.py` escrever no
   Data Lake)
   O role `Contributor` (atribuído ao Service Principal na assinatura, para
   o Terraform gerenciar recursos) **não** dá acesso a ler/escrever dados
   dentro do storage account — Azure Storage separa permissões de
   gerenciamento (plano de controle) das de dados (plano de dados). Sem a
   role abaixo, o pipeline falha ao tentar gravar no container `bronze`.
   ```bash
   storageId=$(az storage account show --name stconectarenaldev \
     --resource-group rg-conecta-renal-dev --query id -o tsv)

   az role assignment create \
     --assignee <APP_ID_DO_SERVICE_PRINCIPAL> \
     --role "Storage Blob Data Contributor" \
     --scope "$storageId"
   ```
   Essa concessão é escopada apenas ao storage account `stconectarenaldev`
   (não à assinatura toda), então o impacto de segurança é limitado a esse
   recurso.

5. **Criação da tabela Delta `bronze_sih` a partir do Parquet gravado pelo
   pipeline** (não é infraestrutura, é uma operação de dado — por isso não
   está no Terraform)
   Depois que `pipelines/datasus/ingest_sih.py` já tiver gravado ao menos um
   mês de dados no container `bronze`, rode manualmente no **Databricks SQL
   Editor** (conectado ao SQL Warehouse `sqlwh-conecta-renal-dev`, criado
   pelo Terraform) o script `pipelines/datasus/sql/create_bronze_sih_table.sql`.
   Ele cria/atualiza a tabela `bronze_sih` em formato Delta, permitindo
   consulta SQL direta (Databricks SQL, Power BI, etc.) sobre os dados do
   bronze. Precisa ser reexecutado após novas cargas do pipeline para
   refletir os dados mais recentes (não há, ainda, automação de refresh).

## Contribuição

Padrão de nomenclatura de branches:

- `feature/<nome-da-feature>` — novas funcionalidades
- `fix/<nome-do-bug>` — correções de bugs
- `infra/<nome-da-mudanca>` — mudanças de infraestrutura (Terraform, CI/CD)

Pull Requests para `main` disparam automaticamente `terraform plan` via
GitHub Actions. Merges em `main` disparam `terraform apply`.

## Licença

Distribuído sob a licença MIT.

.
