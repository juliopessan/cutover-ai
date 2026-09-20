# Roteiro de validação do código de migração em workspaces reais

Este roteiro transforma "gerado" em "funciona". Hoje o código que o Cutover gera para Databricks e
Microsoft Fabric passou por checagem de sintaxe e por uma reconciliação testada em um motor
independente (SQLite), mas **nunca foi executado em um workspace real**. É isso que este roteiro fecha.

Ele serve para quem vai rodar os testes e para quem vai decidir se o código pode ser usado.

## 0. O que "funciona" quer dizer aqui

O código funciona quando, em um workspace de teste, **os cinco critérios** abaixo forem verdadeiros para os
dois destinos:

1. O DDL executa sem erro e cria a tabela **vazia**, com os tipos e os comentários de origem esperados.
2. O notebook de carga termina sem erro e a contagem carregada é igual à do perfil.
3. A reconciliação (`03_reconciliacao.sql`) devolve **todas as linhas com `OK`**, sem nenhum `DIVERGE`.
4. Os **testes negativos** (seção 5) se comportam como descrito: o código recusa em vez de corromper.
5. Nada fora do schema de teste foi criado, alterado ou apagado.

**O que este roteiro não prova:** desempenho com volumes grandes, comportamento com dados reais ou
sensíveis, integração com pipelines de orquestração e permissões de produção. Os datasets são
sintéticos e pequenos de propósito.

## 1. Antes de começar

**Ambiente de teste, nunca produção.** Use um workspace, um catálogo (Databricks) ou um Lakehouse
(Fabric) criado só para isto. Todo objeto criado aqui deve poder ser apagado no fim.

**Dados.** Somente os datasets sintéticos da seção 2. Não use dados de clientes.

**Credenciais.** Ficam no seu login do workspace. Nenhuma chave é colocada no código gerado nem no
repositório.

**Tempo.** Reserve de 2 a 4 horas por destino na primeira execução (estimativa, não medida).

| Destino | Precisa ter |
|---|---|
| Databricks | Workspace com Unity Catalog; permissão para criar schema, tabela e volume em um catálogo de teste; um cluster ou SQL warehouse com runtime recente |
| Microsoft Fabric | Workspace com capacidade Fabric (ou trial); permissão para criar Lakehouse e importar notebook |

**Registre as versões.** Anote o runtime do Databricks ou a data e a região do Fabric. Um erro sem
versão é difícil de reproduzir.

## 2. Datasets do teste

Todos existem no repositório ou são gerados por script. Os números abaixo foram medidos.

| Dataset | Onde está | Linhas | Colunas | Verificações na reconciliação | O que exercita |
|---|---|---|---|---|---|
| `ref__populations.csv` | `tests/fixtures/cloudera_covid/` | 266 | 2 | 8 | **`BIGINT`**: o máximo é 7.761.620.146, acima do limite de `INT` |
| `ref__country_codes.csv` | `tests/fixtures/cloudera_covid/` | 255 | 6 | 22 | **UTF-8** (`Côte d'Ivoire`, `Réunion`), `DECIMAL` e `INT` |
| `vendas_limpo.csv` | `python scripts/samples/generate_sales_csv.py` | 40.000 | 8 | — | Volume médio, datas, nenhum alerta |
| `vendas_com_defeitos.csv` | mesmo script | 40.200 | 10 | — | Nomes inválidos renomeados, coluna mista como `STRING`, **200 duplicatas** |

Comece pelos dois primeiros: são pequenos e cobrem as diferenças de tipo mais delicadas. Só passe
para os de vendas depois que eles fecharem.

> **Atenção com `ref__populations.csv`.** No benchmark, o modelo sugeriu `INT` para `population` em
> 3 de 3 execuções, e a verificação `type_fits_data` barrou todas (o máximo é 7.761.620.146). Isso é o
> portão funcionando, mas significa que você **pode não conseguir aprovar** a sugestão: a aprovação só é
> aceita com todas as verificações passando, e **hoje não existe edição manual do mapeamento**.
> Rejeite e rode de novo (custa frações de centavo, e há um limite diário de execuções). Se o modelo
> insistir em `INT`, comece por `ref__country_codes.csv`, registre a limitação no resultado e trate o
> caso `BIGINT` como pendente até existir uma forma de corrigir o tipo antes de aprovar.

## 3. Preparação no Cutover (igual para os dois destinos)

1. Rode `make serve`, crie uma conta e envie o CSV com o destino desejado.
2. Em **Sugerir mapeamento com IA**, rode e **aprove** a sugestão. A aprovação só é aceita se as
   verificações passaram; se elas reprovarem, rejeite e rode de novo (veja o aviso da seção 2).
3. Em **Gerar código de migração**, escolha o destino e ajuste catálogo, schema, tabela e o caminho
   do arquivo de origem para o que existe no seu workspace de teste.
4. Baixe o `.zip` e descompacte.
5. Confira o `manifest.json`: `"executado": false`, o SHA-256 do arquivo de origem e o hash de cada arquivo.
6. Calcule o SHA-256 do CSV que você vai subir e confirme que é o mesmo do manifesto:

```bash
shasum -a 256 ref__populations.csv
```

Se o hash diferir, **pare**: os valores esperados da reconciliação só valem para aquele arquivo.

## 4. Execução

### 4.1 Databricks

| Passo | Ação | Resultado esperado | Evidência |
|---|---|---|---|
| D1 | Crie o schema e o volume de teste: `CREATE SCHEMA IF NOT EXISTS <catalogo>.<schema>;` e `CREATE VOLUME IF NOT EXISTS <catalogo>.<schema>.landing;` | Sem erro | Captura de tela |
| D2 | Envie o CSV para `/Volumes/<catalogo>/<schema>/landing/` (Catalog Explorer, Upload) | Arquivo listado com o tamanho em bytes igual ao do arquivo local | Tamanho no Explorer |
| D3 | Execute `01_ddl.sql` em um SQL warehouse | Tabela criada, **vazia** | Saída do comando |
| D4 | `DESCRIBE TABLE EXTENDED <catalogo>.<schema>.<tabela>` | Tipos como no DDL e comentários `origem: ...` em cada coluna | Saída |
| D5 | Importe `02_carga.py` como notebook (Workspace, Import, formato de origem) e execute todas as células | Mensagens `linhas carregáveis: N (esperado N)` e `carga concluída` | Saída das células |
| D6 | Execute `03_reconciliacao.sql` | Todas as linhas com `status = OK` | Resultado inteiro, sem cortes |
| D7 | `SELECT * FROM <tabela> LIMIT 10` e compare 3 linhas com o CSV à mão | Valores iguais, colunas renomeadas | Captura |

### 4.2 Microsoft Fabric

| Passo | Ação | Resultado esperado | Evidência |
|---|---|---|---|
| F1 | Crie um Lakehouse de teste no workspace | Lakehouse criado | Captura |
| F2 | Envie o CSV para `Files/landing/` | Arquivo listado | Captura |
| F3 | Importe `02_carga_lakehouse.ipynb` (Workspace, Import, Notebook), **anexe o Lakehouse** e execute todas as células | Mensagens `linhas carregáveis: N (esperado N)` e `carga concluída` | Saída das células |
| F4 | No **SQL analytics endpoint** do Lakehouse, execute `03_reconciliacao.sql` | Todas as linhas com `status = OK` | Resultado inteiro |
| F5 | Em um Warehouse de teste, execute `01_ddl_warehouse.sql` | Tabela criada sem erro | Saída |
| F6 | `SELECT TOP 10 * FROM <tabela>` e compare 3 linhas com o CSV | Valores iguais | Captura |

O passo F5 só confirma que o DDL de Warehouse é aceito; o notebook grava no Lakehouse, não no Warehouse.

## 5. Testes negativos: o código precisa recusar

Estes testes provam as garantias de segurança. Em todos, **o comportamento correto é falhar** ou
divergir, e nunca carregar dado ruim em silêncio. Rode cada um em uma tabela nova.

| Nº | Como provocar | Comportamento esperado |
|---|---|---|
| N1 | Execute o notebook de carga uma segunda vez | Aborta com `... já tem dados. Nada foi escrito.` e a contagem da tabela não muda |
| N2 | Execute o DDL uma segunda vez | Erro de "tabela já existe"; nada é sobrescrito |
| N3 | Em uma cópia do CSV numérico, troque um valor por `999999999999` e recarregue | A reconciliação mostra `DIVERGE` em `max(...)` |
| N4 | Em `ref__country_codes.csv`, troque um `numeric_code` por `abc` | O notebook aborta com `Conversão perdeu valores (coluna: linhas)`; **nada é escrito** |
| N5 | Apague a última linha do CSV antes de subir | O notebook aborta com `A contagem difere do perfil da origem`; nada é escrito |
| N6 | Aponte `SOURCE_PATH` para um arquivo que não existe | Erro claro de caminho inexistente, sem tabela parcial |
| N7 | Use `ref__country_codes.csv` (com `Côte d'Ivoire` e `Réunion`) | Carga e reconciliação OK, incluindo `tamanho_max(country)`; acentos preservados no `SELECT` |

O N7 confirma que letras acentuadas são lidas e gravadas corretamente em UTF-8 e que `LEN` conta
caracteres, como a reconciliação assume. Se só `tamanho_max` divergir, o problema é a semântica de
`LEN`, e não a carga.

**O que o N7 não exercita:** o estouro de bytes de um `VARCHAR(n)` em UTF-8. Ele só apareceria se o valor
**mais longo** da coluna tivesse acentos, e neste dataset o mais longo é ASCII (38 caracteres). O gerador
protege esse caso dimensionando `VARCHAR` para 2 bytes por caractere, mas isso foi verificado apenas em
teste unitário. Para exercitá-lo no Fabric Warehouse, crie um CSV em que o maior valor tenha acentos
(por exemplo, um nome de 40 caracteres com vários `ã` e `ç`) e rode o DDL de Warehouse.

## 6. O que pode falhar e como reconhecer

Estes são os pontos que o gerador **não** consegue confirmar sem um ambiente real. Se algo quebrar,
provavelmente é um deles.

| Suspeita | Sintoma | Onde corrigir |
|---|---|---|
| O Fabric não aceita o `.ipynb` gerado (metadados mínimos) | Erro ao importar, ou o notebook abre sem kernel | `render_ipynb` em `generate.py` |
| `spark.catalog.tableExists` com nome de três partes no Databricks | `ParseException` ou `AnalysisException` na célula 5 | Célula de escrita em `notebook_cells` |
| `DROPMALFORMED` descarta um número diferente de linhas que o perfil | `linhas carregáveis` diferente do esperado em arquivo com aspas ou quebras de linha internas | Leitura em `notebook_cells`; comparar com `rows_discarded` do perfil |
| Datas fora do formato ISO viram nulo | A conversão perde valores (célula 3) e aborta | Adicionar formato explícito de origem |
| `LEN` no T-SQL diverge de caracteres | `DIVERGE` só em `tamanho_max` | `reconciliation` em `generate.py` |
| Diferença de comparação numérica (`FLOAT` vs `DECIMAL`) | `DIVERGE` em `min` ou `max` de coluna decimal | Tipos em `spark_type` e `tsql_type` |
| O caminho `Files/...` precisa ser `abfss://` ou relativo ao Lakehouse anexado | Erro de caminho na leitura | Parâmetro `SOURCE_PATH` |

## 7. Registro dos resultados

Copie a tabela e preencha uma por destino e por dataset.

```text
Destino: ______________   Dataset: ______________________   Data: ___/___/______
Versão (runtime do Databricks ou data/região do Fabric): ________________________
SHA-256 do CSV subido: ____________________________________________________________
Pacote gerado com a execução nº: ______   Aprovada por: ________________________

Passo   Esperado                                   Obtido            OK?   Evidência
D1/F1   ...                                        ...               [ ]
...
N1      Carga recusa a segunda execução            ...               [ ]
...
Reconciliação: ___ de ___ linhas OK   (esperado: todas)
```

Para cada falha, anexe: a mensagem **completa** do erro, o nome do arquivo do pacote e a versão do
ambiente. Sem isso o problema não é reprodutível.

## 8. Como tratar uma falha

Classifique antes de mexer no código:

1. **Erro de ambiente** (permissão, caminho, capacidade): corrija no ambiente e repita. Não altera o gerador.
2. **Limitação da plataforma** (sintaxe ou tipo não suportado): documente e ajuste o gerador para o dialeto.
3. **Bug do gerador**: escreva primeiro um teste em `tests/test_codegen.py` que reproduza o erro,
   depois corrija `cutover/codegen/generate.py`. Os testes de injeção e de reconciliação existentes
   têm de continuar passando.

## 9. Critérios de aceite e o que muda depois

O código pode ser considerado **executado com sucesso** em um destino quando:

- os passos D1 a D7 (ou F1 a F6) passaram nos datasets `ref__country_codes.csv` e, quando o modelo
  sugerir `BIGINT` e permitir a aprovação, `ref__populations.csv`;
- a reconciliação fechou com todas as linhas `OK` (22 de 22 e, se aprovado, 8 de 8);
- os testes N1 a N7 se comportaram como descrito;
- o resultado está registrado na tabela da seção 7, com a versão do ambiente.

**Só depois disso** é honesto alterar o texto do produto. Hoje a tela de geração, a landing, o README e o
`AGENTS.md` dizem "não executado em ambiente real". Ao concluir, troque por uma frase que cite o
destino, a versão e a data do teste, e mantenha o aviso para o destino que ainda não foi validado.
Não generalize um teste em Databricks para o Fabric, nem o contrário.

## 10. Limpeza

Ao terminar, apague apenas o que você criou: as tabelas de teste, o volume `landing` e o schema
(Databricks), ou o Lakehouse e o Warehouse de teste (Fabric). Confirme que nenhum objeto de outro
projeto foi tocado e que o CSV subido não ficou em armazenamento compartilhado.
