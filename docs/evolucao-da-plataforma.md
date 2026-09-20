# Evolução da plataforma

Revisão do que o Cutover faz hoje, do que ainda o impede de ser usado com dados e clientes reais e do
que vale construir primeiro. Cada item cita a **evidência**: uma medição, um teste ou uma leitura do código.
Onde a evidência é só uma inferência, o texto diz.

**Como ler as estimativas de esforço:** P é de dias, M de uma a duas semanas e G de várias semanas para
uma pessoa. São estimativas minhas, não medições.

## O que já foi corrigido nesta rodada

Estes itens saíram da lista porque foram medidos, corrigidos e cobertos por teste.

| Achado | Evidência | Correção |
|---|---|---|
| Uma sugestão barrada pelo portão não tinha saída | O modelo sugeriu `INT` para `population` em 3 de 3 execuções e o máximo é 7.761.620.146 | Correção por regra (`int` para `bigint`) e edição manual, com trilha de auditoria; editar cancela a aprovação |
| Um upload grande congelava o app para todos | Com um arquivo de 24,6 MB, `/healthz` foi de 2 ms para **3,6 s** durante o perfil | Perfil em thread: a mesma medição caiu para ~0,15 s |
| Injeção de fórmula no CSV baixado | Um nome de coluna `=HYPERLINK(...)` saía cru e o Excel o executaria | Células que começam com `=`, `+`, `-` ou `@` são neutralizadas |
| Chamada ao provedor sem limite de tempo | O cliente usava o padrão da biblioteca (10 min) | Timeout de 90 s (`DEEPSEEK_TIMEOUT_S`) e uma nova tentativa |

## Prioridade 1: o que trava o uso real

### 1. Formatos brasileiros de arquivo
**Evidência (testada):** um CSV com `01/02/2026;1.234,56;João` foi perfilado como **três colunas de texto**, e um
arquivo em latin-1 foi recusado com "O arquivo não está em UTF-8". Planilhas exportadas no Brasil quase
sempre usam data `dd/mm/aaaa`, vírgula decimal e, às vezes, Windows-1252.
**Impacto:** o perfil dá tipo errado, o modelo sugere `date` ou `decimal` sobre texto, e o código gerado
aborta a carga porque a conversão perde valores (o notebook trata isso como erro, com razão).
**Proposta:** detectar codificação (com fallback para Windows-1252), reconhecer `dd/mm/aaaa` e decimal com
vírgula no perfil, guardar o formato medido e usá-lo no `to_date(col, 'dd/MM/yyyy')` do notebook.
**Esforço:** M.

### 2. Validação em workspaces reais
**Evidência:** o código gerado só passou por sintaxe e por reconciliação em um motor independente
(SQLite). Nenhuma linha foi executada em Databricks ou Fabric.
**Proposta:** executar `docs/roteiro-validacao-workspace.md` e registrar os resultados. Só depois disso o
texto do produto pode deixar de dizer "não executado".
**Esforço:** P a M por destino, dependente de acesso a um workspace de teste.

### 3. Implantação segura
**Evidência:** o app roda em HTTP local, com SQLite e uploads em disco, cadastro aberto e sem
recuperação de senha nem confirmação de e-mail (não há rota para isso no código).
**Proposta:** Dockerfile com proxy reverso e HTTPS (`CUTOVER_COOKIE_SECURE=1`), armazenamento de objetos
para os uploads, Postgres no lugar de SQLite, redefinição de senha e cadastro por convite.
**Esforço:** M a G.

## Prioridade 2: o que aumenta o valor

### 4. Ligar a política de refinamento ao fluxo
**Evidência:** `ArtifactBranch` e `RefinementPolicy` existem e são testados, mas o fluxo ao vivo só exibe a
decisão (`accept` ou `refine`); ninguém age sobre ela. Uma sugestão reprovada hoje exige um clique humano.
**Proposta:** tentar primeiro a correção por regra (custo zero), e só chamar o modelo de novo, com escalonamento
de nível, quando nenhuma regra resolver. Isso reduz custo e latência na mesma medida.
**Esforço:** M.

### 5. Escala do perfil
**Evidência (medida):** 24,6 MB (380 mil linhas) levam 5,0 s e 276 MB de RAM no pico. O limite atual é de
25 MB, então está dentro do teto, mas o perfil lê o arquivo inteiro para a memória e guarda um hash por linha.
**Proposta:** leitura em fluxo e estimativas probabilísticas (HyperLogLog para distintos) se o limite subir.
Um job em fila, com progresso, evitaria que a requisição fique presa.
**Esforço:** M.

### 6. Relações reais entre datasets
**Evidência:** o consolidado compara colunas por **nome** e **tipo**; não compara valores. Duas colunas de
nomes diferentes que se relacionam (por exemplo `geo_id` e `alpha_2code`) passam despercebidas.
**Proposta:** comparar conjuntos de valores por assinatura (MinHash) para sugerir chaves estrangeiras com
uma medida de sobreposição.
**Esforço:** M.

### 7. Dados pessoais por conteúdo
**Evidência:** a sensibilidade é uma heurística por nome de coluna; os valores nunca são inspecionados, e o
relatório diz isso. Uma coluna `doc` com CPFs passa.
**Proposta:** detecção local por padrão e dígito verificador (CPF, CNPJ), sem enviar nada a um modelo, com o
resultado como medição e não como suposição.
**Esforço:** P a M.

### 8. Origens além de CSV
**Evidência:** só há upload de CSV. O README lista dez sistemas de origem (Cloudera, Oracle, Snowflake,
SAP e outros), mas nenhum conector de origem existe no código hoje.
**Proposta:** Parquet e Excel primeiro (baratos), depois um conector por origem, começando pela que o piloto usar.
**Esforço:** M por formato simples; G por conector.

## Prioridade 3: operação e segurança

### 9. Observabilidade de custo
**Evidência:** cada chamada vai para o livro-razão do Tollgate, mas não há tela para vê-lo. O custo só
aparece dentro de cada relatório.
**Proposta:** painel de custo por usuário e por período, orçamento mensal por conta e exportação da trilha.
**Esforço:** M.

### 10. Endurecer a autenticação
**Evidência:** a proteção contra CSRF é a checagem de origem (sem token), e o bloqueio de tentativas de login
vive em memória do processo, então zera ao reiniciar e não vale com mais de um processo.
**Proposta:** token CSRF, limite de tentativas em armazenamento compartilhado e dois fatores.
**Esforço:** M.

### 11. Execuções longas fora da requisição
**Evidência (inferência, não testada):** a execução ao vivo roda numa thread do processo web; um reinício no
meio de uma chamada a perde. Não medi esse cenário.
**Proposta:** fila de tarefas com retomada e botão de cancelar.
**Esforço:** M.

## O que eu não faria agora

- **Mais modelos ou provedores.** O gargalo não é o modelo: 12 de 15 sugestões passaram e as demais foram
  barradas por regra. Trocar de modelo antes de validar em um workspace real é otimizar a parte errada.
- **Executar a migração pelo Cutover.** Muda o perfil de risco do produto. A geração de código com
  reconciliação já entrega o valor; a execução exige credenciais, política e autorização humana.
- **Refinar o design.** A revisão de acessibilidade e o mobile já fecharam os problemas medidos.

## Ordem sugerida

1. **Formatos brasileiros** (1): destrava dados reais e reduz o retrabalho do modelo.
2. **Validação em workspaces** (2): converte "gerado" em "funciona", em paralelo com o item 1.
3. **Refinamento por regra primeiro** (4): custo e latência menores, reaproveitando o que já existe.
4. **Implantação segura** (3): condição para qualquer cliente externo.
5. O restante, guiado pelo que o piloto revelar.
