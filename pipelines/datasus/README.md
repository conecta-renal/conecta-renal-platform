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
