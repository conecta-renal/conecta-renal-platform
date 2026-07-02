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
`.dbc` descomprimido tem **120 colunas**:

```
UF_ZI, ANO_CMPT, MES_CMPT, ESPEC, CGC_HOSP, N_AIH, IDENT, CEP, MUNIC_RES,
NASC, SEXO, UTI_MES_IN, UTI_MES_AN, UTI_MES_AL, UTI_MES_TO, MARCA_UTI,
UTI_INT_IN, UTI_INT_AN, UTI_INT_AL, UTI_INT_TO, DIAR_ACOM, QT_DIARIAS,
PROC_SOLIC, PROC_REA, VAL_SH, VAL_SP, VAL_SADT, VAL_RN, VAL_ACOMP, VAL_ORTP,
VAL_SANGUE, VAL_SADTSR, VAL_TRANSP, VAL_OBSANG, VAL_PED1AC, VAL_TOT, VAL_UTI,
US_TOT, DT_INTER, DT_SAIDA, DIAG_PRINC, DIAG_SECUN, COBRANCA, NATUREZA,
NAT_JUR, GESTAO, RUBRICA, IND_VDRL, MUNIC_MOV, COD_IDADE, IDADE, DIAS_PERM,
MORTE, NACIONAL, NUM_PROC, CAR_INT, TOT_PT_SP, CPF_AUT, HOMONIMO,
NUM_FILHOS, INSTRU, CID_NOTIF, CONTRACEP1, CONTRACEP2, GESTRISCO, INSC_PN,
SEQ_AIH5, CBOR, CNAER, VINCPREV, GESTOR_COD, GESTOR_TP, GESTOR_CPF,
GESTOR_DT, CNES, CNPJ_MANT, INFEHOSP, CID_ASSO, CID_MORTE, COMPLEX, FINANC,
FAEC_TP, REGCT, RACA_COR, ETNIA, SEQUENCIA, REMESSA, AUD_JUST, SIS_JUST,
VAL_SH_FED, VAL_SP_FED, VAL_SH_GES, VAL_SP_GES, VAL_UCI, MARCA_UCI,
DIAGSEC1..DIAGSEC9, TPDISEC1..TPDISEC9, FONTE_ORC
```

O pipeline mantém apenas as 16 colunas abaixo (definidas em
`COLUNAS_RELEVANTES` no `ingest_sih.py`) — as demais são descartadas na
gravação do Parquet:

| Coluna       | Descrição                                                |
|--------------|-----------------------------------------------------------|
| `N_AIH`      | Número da AIH (Autorização de Internação Hospitalar)       |
| `DT_INTER`   | Data de internação (`AAAAMMDD`)                            |
| `DT_SAIDA`   | Data de saída/alta (`AAAAMMDD`)                            |
| `DIAG_PRINC` | CID-10 do diagnóstico principal                            |
| `DIAG_SECUN` | CID-10 do diagnóstico secundário (um único código)          |
| `MUNIC_RES`  | Código IBGE do município de residência do paciente          |
| `NASC`       | Data de nascimento (`AAAAMMDD`)                            |
| `SEXO`       | Sexo do paciente (1 = masculino, 3 = feminino)               |
| `IDADE`      | Idade do paciente na internação                             |
| `MORTE`      | Indicador de óbito (1 = sim, 0 = não)                       |
| `DIAS_PERM`  | Dias de permanência (tempo de internação)                   |
| `VAL_TOT`    | Valor total pago pela AIH                                   |
| `PROC_REA`   | Código do procedimento realizado                            |
| `CNES`       | Código CNES do estabelecimento de saúde                     |
| `ANO_CMPT`   | Ano de competência da AIH                                   |
| `MES_CMPT`   | Mês de competência da AIH                                   |

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
