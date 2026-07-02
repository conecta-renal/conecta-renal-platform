# Ingestão SIH-SUS (DATASUS) — Conecta Renal

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

| Variável         | Descrição                                                        | Default |
|-------------------|-------------------------------------------------------------------|---------|
| `DATASUS_UF`      | UF (sigla) cujos arquivos serão baixados                          | `SP`    |
| `DATASUS_MESES`   | Janela de meses anteriores à data de execução a serem processados | `24`    |

Exemplo:

```bash
DATASUS_UF=RJ DATASUS_MESES=12 python ingest_sih.py
```

## Saída gerada

- **Dados (camada bronze)**: `output/bronze/sih/ano={ano}/mes={mes}/data.parquet`
  — um arquivo Parquet por ano/mês, já filtrado pelos CIDs renais e com
  apenas as colunas relevantes para o Conecta Renal.
- **Logs**: `output/logs/sih_{timestamp}.log` — um log por execução, com
  detalhes de cada arquivo processado (registros originais, registros
  filtrados, tamanho do parquet, tempo de execução).
- Um resumo final também é impresso no console ao término da execução.

## CIDs filtrados

Registros em que `DIAG_PRINC` ou `DIAG_SECUN` começam com algum dos
seguintes CIDs são mantidos (os demais são descartados):

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
