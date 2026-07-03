# Pipelines DATASUS — Conecta Renal

Scripts de ingestão de fontes do DATASUS, a partir do FTP público, para o
Conecta Renal. Quatro fontes implementadas até agora:

| Fonte | Script | Filtro | Destino no bronze |
|---|---|---|---|
| **SIH-SUS** (internações hospitalares) | `ingest_sih.py` | CIDs de interesse renal | `bronze/sih/ano={ano}/mes={mes}/` |
| **SIA-SUS — APAC Tratamento Dialítico** (acompanhamento de diálise) | `ingest_atd.py` | Nenhum (instrumento já é 100% população renal) | `bronze/atd/ano={ano}/mes={mes}/` |
| **CNES** (cadastro de estabelecimentos) | `ingest_cnes.py` | Nenhum (cadastro completo) | `bronze/cnes/ano={ano}/mes={mes}/` |
| **SIM** (mortalidade) | `ingest_sim.py` | CIDs de interesse renal | `bronze/sim/ano={ano}/` (anual, sem partição por mês) |

Todos seguem a mesma estrutura de código (conexão FTP com retry, download,
descompressão `.dbc`→`.dbf`, escrita direta no ADLS) — a maior parte das
seções abaixo vale para todos, com diferenças pontuadas onde existem.

## SIH-SUS: Ingestão de internações hospitalares

Script de ingestão do SIH-SUS (Sistema de Informações Hospitalares) a partir
do FTP público do DATASUS, com filtro por CIDs de interesse renal.

## Como rodar localmente

1. Use **Python 3.10, 3.11 ou 3.12**. A dependência `pyreaddbc` (usada para
   descomprimir os arquivos `.dbc`) é uma extensão nativa C e pode não ter
   wheel pré-compilada para versões muito recentes do Python (ex: 3.14) —
   nesse caso, o `pip install` tentaria compilar do zero e falharia sem um
   compilador C/Visual Studio instalado.

2. Crie um ambiente virtual e instale as dependências:
   ```bash
   cd pipelines/datasus
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. (Opcional) Configure as variáveis de ambiente — veja a seção abaixo.

4. Execute o script:
   ```bash
   python ingest_sih.py
   ```

Não é necessário usuário/senha: a conexão com `ftp.datasus.gov.br` é feita
via FTP anônimo (`anonymous` / senha vazia), que é o acesso público padrão
do DATASUS.

## Sobre o formato dos arquivos no FTP

O FTP do DATASUS distribui o SIH-SUS em uma **única pasta**, sem
subdiretórios por ano — `/dissemin/publicos/SIHSUS/200801_/Dados` — contendo
todos os meses de 2008 em diante. Os arquivos estão em formato **`.dbc`**,
um DBF comprimido com algoritmo proprietário (PKWare/blast), não legível
diretamente por bibliotecas de DBF puro. Por isso o script descomprime cada
`.dbc` para `.dbf` (usando `pyreaddbc.dbc2dbf`) antes de carregar com
`dbfread`.

Existe também uma pasta legada `/dissemin/publicos/SIHSUS/DBF/{ano}/`,
organizada por ano — mas ela está parada desde 2014-05 e não recebe mais
atualizações; não é usada por este pipeline.

## Colunas disponíveis no arquivo original

O layout `RD` (AIH Reduzida) do SIH-SUS traz muito mais colunas do que o
Conecta Renal usa. Confirmado contra um arquivo real (`RDSP2604.dbc`), o
`.dbc` descomprimido tem **114 colunas**.

As descrições abaixo vêm do **Informe Técnico oficial do DATASUS**
("Disseminação de Informações do Sistema de Informações Hospitalares (SIH)
— Informe Técnico referente ao processamento 2016-03", arquivo
`IT_SIHSUS_1603.pdf`), disponível na própria pasta de documentação do FTP:
`/dissemin/publicos/SIHSUS/200801_/Doc/IT_SIHSUS_1603.pdf`.

### Identificação do estabelecimento e da AIH

| Coluna | Tipo | Descrição |
|---|---|---|
| `UF_ZI` | char(6) | Município Gestor |
| `ANO_CMPT` | char(4) | Ano de processamento da AIH (`aaaa`) |
| `MES_CMPT` | char(2) | Mês de processamento da AIH (`mm`) |
| `ESPEC` | char(2) | Especialidade do leito |
| `CGC_HOSP` | char(14) | CNPJ do estabelecimento |
| `N_AIH` | char(13) | Número da AIH |
| `IDENT` | char(1) | Identificação do tipo da AIH |
| `CNES` | char(7) | Código CNES do hospital |
| `CNPJ_MANT` | char(14) | CNPJ da mantenedora |
| `SEQUENCIA` | numeric(9) | Sequencial da AIH na remessa |
| `REMESSA` | char(21) | Número da remessa |

### Paciente

| Coluna | Tipo | Descrição |
|---|---|---|
| `CEP` | char(8) | CEP do paciente |
| `MUNIC_RES` | char(6) | Município de residência do paciente |
| `NASC` | char(8) | Data de nascimento do paciente (`aaaammdd`) |
| `SEXO` | char(1) | Sexo do paciente |
| `COD_IDADE` | char(1) | Unidade de medida da idade |
| `IDADE` | numeric(2) | Idade |
| `NACIONAL` | char(2) | Código da nacionalidade do paciente |
| `HOMONIMO` | char(1) | Indica se o paciente da AIH é homônimo do paciente de outra AIH |
| `NUM_FILHOS` | numeric(2) | Número de filhos do paciente |
| `INSTRU` | char(1) | Grau de instrução do paciente |
| `CBOR` | char(3) | Ocupação do paciente, segundo a CBO |
| `VINCPREV` | char(1) | Vínculo com a Previdência |
| `RACA_COR` | char(4) | Raça/cor do paciente |
| `ETNIA` | char(4) | Etnia do paciente, se raça/cor for indígena |

### Internação, diagnóstico e desfecho

| Coluna | Tipo | Descrição |
|---|---|---|
| `DT_INTER` | char(8) | Data de internação (`aaaammdd`) |
| `DT_SAIDA` | char(8) | Data de saída (`aaaammdd`) |
| `DIAG_PRINC` | char(4) | CID-10 do diagnóstico principal |
| `DIAG_SECUN` | char(4) | CID-10 do diagnóstico secundário (preenchido com zeros a partir de 2015-01) |
| `DIAGSEC1`..`DIAGSEC9` | char(4) | Diagnósticos secundários adicionais 1 a 9 |
| `TPDISEC1`..`TPDISEC9` | char(1) | Tipo de cada diagnóstico secundário 1 a 9 |
| `CID_NOTIF` | char(4) | CID de notificação (compulsória) |
| `CID_ASSO` | char(4) | CID causa associado |
| `CID_MORTE` | char(4) | CID da morte |
| `MORTE` | numeric(1) | Indica óbito |
| `DIAS_PERM` | numeric(5) | Dias de permanência |
| `CAR_INT` | char(2) | Caráter da internação |
| `COBRANCA` | char(2) | Motivo de saída/permanência |
| `INFEHOSP` | char(1) | Status de infecção hospitalar |
| `IND_VDRL` | char(1) | Indica realização de exame VDRL |
| `GESTRISCO` | char(1) | Indicador se é gestante de risco |
| `INSC_PN` | char(12) | Número da gestante no pré-natal |
| `CONTRACEP1` | char(2) | Tipo de contraceptivo utilizado |
| `CONTRACEP2` | char(2) | Segundo tipo de contraceptivo utilizado |

### UTI / UCI

| Coluna | Tipo | Descrição |
|---|---|---|
| `UTI_MES_IN`, `UTI_MES_AN`, `UTI_MES_AL` | numeric(2) | Zerados (não utilizados atualmente) |
| `UTI_MES_TO` | numeric(3) | Quantidade de dias de UTI no mês |
| `MARCA_UTI` | char(2) | Indica o tipo de UTI utilizada pelo paciente |
| `UTI_INT_IN`, `UTI_INT_AN`, `UTI_INT_AL` | numeric(2) | Zerados (não utilizados atualmente) |
| `UTI_INT_TO` | numeric(3) | Quantidade de diárias em unidade intermediária |
| `VAL_UCI` | numeric(10,2) | Valor de UCI |
| `MARCA_UCI` | char(2) | Tipo de UCI utilizada pelo paciente |

### Procedimento e valores financeiros

| Coluna | Tipo | Descrição |
|---|---|---|
| `PROC_SOLIC` | char(10) | Procedimento solicitado |
| `PROC_REA` | char(10) | Procedimento realizado |
| `DIAR_ACOM` | numeric(3) | Quantidade de diárias de acompanhante |
| `QT_DIARIAS` | numeric(3) | Quantidade de diárias |
| `VAL_SH` | numeric(13,2) | Valor de serviços hospitalares |
| `VAL_SP` | numeric(13,2) | Valor de serviços profissionais |
| `VAL_TOT` | numeric(14,2) | Valor total da AIH |
| `VAL_UTI` | numeric(8,2) | Valor de UTI |
| `US_TOT` | numeric(10,2) | Valor total, em dólar |
| `VAL_SH_FED` | numeric(10,2) | Complemento federal de serviços hospitalares (incluído no valor total) |
| `VAL_SP_FED` | numeric(10,2) | Complemento federal de serviços profissionais (incluído no valor total) |
| `VAL_SH_GES` | numeric(10,2) | Complemento do gestor (estadual/municipal) de serviços hospitalares (incluído no valor total) |
| `VAL_SP_GES` | numeric(10,2) | Complemento do gestor (estadual/municipal) de serviços profissionais (incluído no valor total) |
| `VAL_SADT`, `VAL_RN`, `VAL_ACOMP`, `VAL_ORTP`, `VAL_SANGUE`, `VAL_SADTSR`, `VAL_TRANSP`, `VAL_OBSANG`, `VAL_PED1AC` | numeric | Zerados (não utilizados atualmente, mantidos por compatibilidade de layout) |
| `TOT_PT_SP` | numeric(6) | Zerado (não utilizado atualmente) |
| `RUBRICA` | numeric(5) | Zerado (não utilizado atualmente) |
| `NUM_PROC` | char(4) | Zerado (não utilizado atualmente) |
| `CPF_AUT` | char(11) | Zerado (não utilizado atualmente) |

### Gestão, financiamento e auditoria

| Coluna | Tipo | Descrição |
|---|---|---|
| `NATUREZA` | char(2) | Natureza jurídica do hospital (com conteúdo só até 2012-05; substituído por `NAT_JUR`) |
| `NAT_JUR` | char(4) | Natureza jurídica do estabelecimento, conforme classificação CONCLA |
| `GESTAO` | char(1) | Indica o tipo de gestão do hospital |
| `MUNIC_MOV` | char(6) | Município do estabelecimento |
| `SEQ_AIH5` | char(3) | Sequencial de longa permanência (AIH tipo 5) |
| `CNAER` | char(3) | Código de acidente de trabalho |
| `GESTOR_COD` | char(3) | Motivo de autorização da AIH pelo gestor |
| `GESTOR_TP` | char(1) | Tipo de gestor |
| `GESTOR_CPF` | char(11) | CPF do gestor |
| `GESTOR_DT` | char(8) | Data da autorização dada pelo gestor (`aaaammdd`) |
| `COMPLEX` | char(2) | Complexidade do procedimento |
| `FINANC` | char(2) | Tipo de financiamento |
| `FAEC_TP` | char(6) | Subtipo de financiamento FAEC |
| `REGCT` | char(4) | Regra contratual |
| `AUD_JUST` | char(50) | Justificativa do auditor para aceitação da AIH sem número do Cartão Nacional de Saúde |
| `SIS_JUST` | char(50) | Justificativa do estabelecimento para aceitação da AIH sem número do Cartão Nacional de Saúde |
| `FONTE_ORC` | — | **Não documentado** no Informe Técnico 2016-03 (campo presente no arquivo real, mas adicionado em atualização posterior do layout não coberta por esse informe). Não usar sem confirmar o significado em uma versão mais recente da documentação do DATASUS. |

O pipeline mantém apenas as 16 colunas abaixo (definidas em
`COLUNAS_RELEVANTES` no `ingest_sih.py`) — as demais são descartadas na
gravação do Parquet: `N_AIH`, `DT_INTER`, `DT_SAIDA`, `DIAG_PRINC`,
`DIAG_SECUN`, `MUNIC_RES`, `NASC`, `SEXO`, `IDADE`, `MORTE`, `DIAS_PERM`,
`VAL_TOT`, `PROC_REA`, `CNES`, `ANO_CMPT`, `MES_CMPT` (ver descrições nas
tabelas acima).

> Nota: o arquivo também traz até 9 diagnósticos secundários adicionais
> (`DIAGSEC1`..`DIAGSEC9`), não capturados pelo filtro atual (que olha só
> `DIAG_PRINC`/`DIAG_SECUN`). Se o Conecta Renal precisar considerar
> comorbidades renais reportadas nesses campos extras, o filtro de CID e a
> lista de `COLUNAS_RELEVANTES` precisam ser revistos.

## Variáveis de ambiente disponíveis

| Variável                | Descrição                                                        | Default              |
|--------------------------|-------------------------------------------------------------------|-----------------------|
| `DATASUS_UF`            | UF (sigla) cujos arquivos serão baixados                          | `SP`                  |
| `DATASUS_MESES`         | Janela de meses anteriores à execução (SIH-SUS, ATD, CNES)         | `24`                  |
| `DATASUS_ANOS`          | Janela de anos anteriores à execução (SIM apenas, ver seção do SIM) | `5`                   |
| `AZURE_STORAGE_ACCOUNT` | Storage account (ADLS Gen2) onde os dados serão gravados           | `stconectarenaldev`   |
| `AZURE_TENANT_ID`       | Tenant ID do Service Principal usado para autenticar no ADLS       | *(obrigatório)*       |
| `AZURE_CLIENT_ID`       | Client ID do Service Principal usado para autenticar no ADLS       | *(obrigatório)*       |
| `AZURE_CLIENT_SECRET`   | Client Secret do Service Principal usado para autenticar no ADLS   | *(obrigatório)*       |

Exemplo:

```bash
DATASUS_UF=RJ DATASUS_MESES=12 \
AZURE_TENANT_ID=... AZURE_CLIENT_ID=... AZURE_CLIENT_SECRET=... \
python ingest_sih.py
```

> O Service Principal usado precisa da role `Storage Blob Data Contributor`
> no storage account de destino (permissão de dados, separada da role de
> gerenciamento `Contributor` usada pelo Terraform) — sem ela, a escrita no
> ADLS falha com erro de autorização.

## Saída gerada

- **Dados (camada bronze)**: gravados diretamente no Azure Data Lake
  Storage Gen2, container `bronze`, em
  `sih/ano={ano}/mes={mes}/data.parquet` — um arquivo Parquet por ano/mês,
  já filtrado pelos CIDs renais e com apenas as colunas relevantes para o
  Conecta Renal. Não é gravado nada em disco local (além de arquivos
  temporários que são apagados ao final de cada mês processado).
- **Logs**: `output/logs/sih_{timestamp}.log` — um log local por execução,
  com detalhes de cada arquivo processado (registros originais, registros
  filtrados, tamanho do parquet, tempo de execução).
- Um resumo final também é impresso no console ao término da execução.

## Rodando via GitHub Actions

O workflow `.github/workflows/ingest-sih.yml` roda o pipeline sob demanda
(`workflow_dispatch`), usando os secrets `AZURE_TENANT_ID`,
`AZURE_CLIENT_ID` e `AZURE_CLIENT_SECRET` já cadastrados no repositório —
não expõe nenhuma credencial no log. Parâmetros `uf` e `meses` podem ser
ajustados na tela de execução manual (Actions → Ingest SIH-SUS → Run
workflow).

## Rodando via Databricks Job

Existe também uma versão adaptada do pipeline em
`databricks/ingest_sih_job.py`, empacotada como **Databricks Job**
(`job-ingest-sih-conecta-renal`, provisionado via Terraform) — o
equivalente, dentro do Azure, a um Glue Job da AWS: um cluster efêmero que
sobe só para a execução e desliga ao final.

Para disparar manualmente: **Databricks → Workflows → Jobs →
job-ingest-sih-conecta-renal → Run now** (os parâmetros `uf` e `meses`
podem ser ajustados na tela de execução). Não há agendamento automático
configurado por padrão — é disparado sob demanda, mas pode-se adicionar um
`schedule` ao recurso `databricks_job` no Terraform se quiser rodar em
intervalos fixos (ex: mensalmente).

Diferenças em relação à versão CLI/GitHub Actions:
- Usa a chave da storage account (via secret scope `conecta-renal-adls`,
  já usado pelo SQL Warehouse) em vez de credenciais de Service Principal.
- Parâmetros vêm de widgets do notebook, não de variáveis de ambiente.
- É uma cópia adaptada da lógica de `ingest_sih.py` — mudanças relevantes
  em um devem ser replicadas no outro.

## Consultando os dados

Os dados no bronze são arquivos Parquet crus — para consultá-los via SQL
(Databricks SQL Editor, Power BI, etc.), rode o script
`sql/create_bronze_sih_table.sql` no **Databricks SQL Editor**, conectado ao
SQL Warehouse `sqlwh-conecta-renal-dev` (provisionado via Terraform). Ele
cria a tabela Delta `bronze_sih` a partir do Parquet, pronta para consulta.
Veja a seção "Passos manuais realizados fora da pipeline" no README raiz do
projeto para mais detalhes.

## SIA-SUS: Acompanhamento de Tratamento Dialítico (ATD)

Script `ingest_atd.py` — ingestão do arquivo **APAC de Tratamento
Dialítico** do SIA-SUS (Sistema de Informações Ambulatoriais), que traz
dados clínicos de acompanhamento de diálise: `ATD_HB` (hemoglobina),
`ATD_FOSFOR` (fósforo), `ATD_KTVSEM` (Kt/V semanal), `ATD_TRU` (taxa de
redução de ureia), `ATD_ALBUMI` (albumina), `ATD_PTH` (hormônio da
paratireoide), tipo de acesso vascular, aptidão a transplante, entre
outros.

Segue exatamente o mesmo padrão de execução do SIH (`python ingest_atd.py`,
mesmas variáveis de ambiente `DATASUS_UF`/`DATASUS_MESES`/`AZURE_*`), com
duas diferenças:

- **Caminho no FTP**: mesma pasta base do SIA-SUS
  (`/dissemin/publicos/SIASUS/200801_/Dados`), arquivos nomeados
  `ATD{UF}{AA}{MM}.dbc` (ex: `ATDSP2604.dbc`).
- **Sem filtro de CID**: o instrumento "APAC de Tratamento Dialítico" já é,
  por natureza, exclusivo de pacientes em diálise — todo registro do
  arquivo já é população-alvo do Conecta Renal, então o pipeline mantém
  todos os registros (só seleciona as colunas relevantes).

Layout confirmado contra um arquivo real do FTP (`ATDSP2604.dbc`, 29.665
registros, 65 colunas), batendo exatamente com o Informe Técnico oficial
do SIA-SUS.

Grava em `bronze/atd/ano={ano}/mes={mes}/data.parquet`. Para consultar via
SQL, rode `sql/create_bronze_atd_table.sql` no Databricks SQL Editor
(cria a tabela Delta `bronze_atd`), mesmo processo do `bronze_sih`.

Mesma automação do SIH: workflow `.github/workflows/ingest-atd.yml`
(`workflow_dispatch`) e Databricks Job `job-ingest-atd-conecta-renal`
(`databricks/ingest_atd_job.py`, provisionado via Terraform).

## CNES: Cadastro de Estabelecimentos

Script `ingest_cnes.py` — ingestão do arquivo de **Estabelecimentos (ST)**
do CNES. O CNES tem 13 sub-arquivos (Estabelecimentos, Profissionais,
Leitos, Equipamentos, etc.); este pipeline traz só o cadastro principal,
usado para enriquecer os códigos CNES já referenciados no SIH e no ATD
(ex: nome/tipo/localização do estabelecimento onde o paciente foi
atendido).

Diferenças em relação ao SIH:
- **Caminho no FTP**: `/dissemin/publicos/CNES/200508_/Dados/ST` — o CNES
  usa uma subpasta própria por tipo de arquivo (`ST`, `PF`, `LT`, etc.),
  diferente da pasta única do SIH/SIA-SUS. Arquivos nomeados
  `ST{UF}{AA}{MM}.dbc`.
- **Sem filtro**: é um cadastro, não um registro clínico — mantém todos
  os estabelecimentos.

Layout confirmado contra um arquivo real do FTP (`STSP2605.dbc`, 113.631
estabelecimentos, 208 colunas), próximo do Informe Técnico oficial do
CNES (que documenta 203).

Grava em `bronze/cnes/ano={ano}/mes={mes}/data.parquet`. Para consultar
via SQL, rode `sql/create_bronze_cnes_table.sql` (cria a tabela Delta
`bronze_cnes`).

Mesma automação do SIH: workflow `.github/workflows/ingest-cnes.yml`
(`workflow_dispatch`) e Databricks Job `job-ingest-cnes-conecta-renal`
(`databricks/ingest_cnes_job.py`, provisionado via Terraform).

## SIM: Mortalidade

Script `ingest_sim.py` — ingestão das Declarações de Óbito do SIM
(Sistema de Informações sobre Mortalidade), filtrando por CIDs de
interesse renal no campo `CAUSABAS` (causa básica do óbito).

Diferenças importantes em relação ao SIH:
- **Publicação anual, não mensal**: arquivos `DO{UF}{AAAA}.dbc` (ex:
  `DOSP2024.dbc`). Por isso a variável de ambiente é `DATASUS_ANOS`
  (default: 5), não `DATASUS_MESES`, e o destino no bronze é particionado
  só por ano: `bronze/sim/ano={ano}/data.parquet` (sem subpasta de mês).
- **Defasagem maior**: dados de mortalidade exigem investigação e
  codificação da causa de óbito — o ano mais recente disponível costuma
  ficar 1-2 anos atrás do ano corrente (confirmamos que 2024 é o ano mais
  recente disponível para SP; 2025 ainda não publicado).
- **Extensão inconsistente**: os arquivos variam entre `.dbc` e `.DBC`
  dependendo do ano (histórico do próprio FTP do DATASUS). O pipeline
  lista o diretório uma vez por execução e resolve o nome real do arquivo
  de forma case-insensitive, em vez de assumir a extensão.

Layout confirmado contra um arquivo real do FTP (`DOSP2024.dbc`, 351.616
óbitos, 87 colunas; 11.485 filtrados como CID renal).

Grava em `bronze/sim/ano={ano}/data.parquet`. Para consultar via SQL,
rode `sql/create_bronze_sim_table.sql` (cria a tabela Delta `bronze_sim`).

Mesma automação do SIH: workflow `.github/workflows/ingest-sim.yml`
(`workflow_dispatch`, com input `anos` em vez de `meses`) e Databricks Job
`job-ingest-sim-conecta-renal` (`databricks/ingest_sim_job.py`,
provisionado via Terraform).

## CIDs filtrados (SIH-SUS e SIM)

Registros em que `DIAG_PRINC`/`DIAG_SECUN` (SIH-SUS) ou
`CAUSABAS`/`CAUSABAS_O` (SIM) começam com algum dos seguintes CIDs são
mantidos (os demais são descartados):

```
N18, N17, Z49, Z940, E11, I10, N04, N03
```

## Comportamento em caso de erro

- **Erros de conexão FTP**: até 3 tentativas, com espera de 5 segundos entre
  elas.
- **Arquivo não encontrado no FTP** (mês sem publicação, UF/ano inválido
  etc.): é logado e o script segue para o próximo mês, sem interromper a
  execução.
- **Arquivo `.dbc` corrompido/ilegível** (falha na descompressão ou na
  leitura do DBF resultante): é logado e o script segue para o próximo mês.
