# Ingestão SIH-SUS (DATASUS) — Conecta Renal

Script de ingestão do SIH-SUS (Sistema de Informações Hospitalares) a partir
do FTP público do DATASUS, com filtro por CIDs de interesse renal.

## Como rodar localmente

1. Crie um ambiente virtual e instale as dependências:
   ```bash
   cd pipelines/datasus
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. (Opcional) Configure as variáveis de ambiente — veja a seção abaixo.

3. Execute o script:
   ```bash
   python ingest_sih.py
   ```

Não é necessário usuário/senha: a conexão com `ftp.datasus.gov.br` é feita
via FTP anônimo (`anonymous` / senha vazia), que é o acesso público padrão
do DATASUS.

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
- **Arquivo DBF corrompido/ilegível**: é logado e o script segue para o
  próximo mês.
