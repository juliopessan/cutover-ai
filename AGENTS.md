# Cutover: guia para agentes

Este arquivo vale para qualquer agente de código (Claude Code, Codex, Cursor). Se existir um `CLAUDE.md`, ele tem prioridade para o Claude Code; sem ele, este é o guia.

## Missão

O Cutover faz **AI-IS**: assessment do estado atual (AS-IS) dos dados com IA, entregue **sem migrar de plataforma**. Hoje cobre perfilamento determinístico de CSVs e sugestão de mapeamento com IA sob portão de custo. A **execução** de migração está fora do escopo: depois da aprovação humana, `cutover.codegen` gera DDL, notebook de carga e SQL de reconciliação para Databricks e Fabric, mas o Cutover nunca os executa.

Princípio central: **o que é medido nunca se mistura com o que é afirmado**. Números calculados vêm de código determinístico; modelos só analisam, sugerem e explicam, e nada que um modelo sugere é aplicado sem aprovação humana.

## Comandos

Rode da raiz do repositório.

```bash
make install          # venv + dependências (dev, governance, scenarios, deepseek)
make test             # pytest
make lint             # ruff em src/cutover e tests + mypy no pacote todo
make serve            # app web em http://127.0.0.1:8000 (carrega o .env)
make benchmark        # perfilamento determinístico, sem IA
make llm-benchmark    # 15 chamadas REAIS à DeepSeek (custa frações de centavo)
make pipelines        # simuladores de cenário (Cloudera/Fabric, Snowflake/Databricks)
```

O CI (`.github/workflows/ci.yml`) roda ruff em `src/cutover tests`, mypy no pacote inteiro, pytest e o build do wheel, em Python 3.11 e 3.12.

## Estrutura

```text
src/cutover/          SDK e app (core, contracts, economics, governance, providers, refinement,
                      plugins, targets, telemetry, validation, web, cli.py)
src/cutover/web/      FastAPI: landing, autenticação, upload, execução ao vivo, /relatorio
tests/                pytest; fixtures/cloudera_covid traz seeds Apache-2.0 (veja o NOTICE)
scripts/benchmarks/   benchmarks reproduzíveis que alimentam a landing e o relatório
scripts/scenarios/    simuladores por cenário (leem templates/ e gravam em outputs/, ignorado pelo git)
docs/                 notas e o relatório em PDF; docs/reports/
```

## Regras que não podem ser quebradas

**Segredos e dados**
- `.env` nunca vai para o git (já está no `.gitignore`). Chaves ficam em variáveis de ambiente; `.env.example` documenta os nomes, sem valores.
- `samples/`, `cutover-data/` e `outputs/` são locais e ignorados. Uploads de usuários nunca entram no repositório.
- **Nenhuma linha de dados vai a um modelo.** Só nomes e tipos de colunas. Se uma mudança ampliar o que é enviado, pare e peça confirmação.
- Dados sintéticos são gerados a partir de esquema e estatística, nunca copiados de produção.
- Nunca execute operações destrutivas em sistemas de origem.

**Governança de custo**
- Toda chamada de LLM passa pelo gateway do Tollgate (`cutover.governance.build_gateway`), normalmente via `GovernedAgent`. Nunca chame o provedor direto.
- O teto de saída do nível vira o `max_tokens` da chamada. Tokens e custo vêm do provedor; um stream sem `usage` deve falhar, nunca ser estimado em silêncio.
- Toda sugestão de modelo sai com `requires_approval` e passa por verificações determinísticas (`check_mapping`). Cada execução é persistida em `mapping_runs`, e a aprovação humana só é aceita se todas as verificações passaram (`cutover.web.runs.decide`). O pass rate vem dessas verificações, nunca de uma nota que o modelo dá a si mesmo.

**Correção do mapeamento** (`correct_mapping`, `runs.revise`)
- Uma sugestão reprovada pode ser corrigida por regra determinística ou à mão, **sem chamar o modelo**. Uma regra só troca um tipo por outro que os dados medidos comprovadamente comportam.
- Editar **sempre** cancela a aprovação (o estado volta a `pending`), guarda a sugestão original e registra quem, quando e por quê. Não crie um caminho que edite sem isso.
- O código gerado grava o hash do mapeamento aprovado e se ele foi editado no `manifest.json`.
- Trabalho pesado de CPU (perfil de arquivo) roda em `asyncio.to_thread`; senão um upload grande congela o app inteiro (medido: `/healthz` de 2 ms para 3,6 s).
- CSVs que o usuário baixa passam por `csv_safe`: uma célula começando com `=`, `+`, `-` ou `@` é uma fórmula para o Excel.

**Geração de código** (`cutover/codegen/`)
- Determinística, por templates. Nenhum modelo escreve código de migração.
- Só gera a partir de uma execução **aprovada**; a rota devolve 409 caso contrário.
- Todo identificador é validado (`^[A-Za-z_][A-Za-z0-9_]*$`), o escape de string é específico do dialeto (Spark usa `\'`, T-SQL usa `''`) e o nome do arquivo enviado é saneado antes de entrar em comentários. Há testes de injeção; mantenha-os.
- Os valores esperados na reconciliação vêm do **perfil medido**. `tests/test_codegen.py` carrega o CSV num motor independente (SQLite) e roda o SQL gerado; um dado adulterado precisa dar `DIVERGE`.
- O código gerado **não foi executado** em Databricks ou Fabric reais. Não afirme o contrário na UI, nos docs ou nas mensagens.

**Medido versus assumido** (vale para UI, README, relatório e mensagens)
- Não apresente como medido o que não foi calculado. Premissas e estimativas aparecem sinalizadas como tais.
- Não invente métricas, depoimentos, preços ou clientes. Sem medição, a seção correspondente não aparece.
- Em UI, as cores barro e menta são reservadas: barro significa "não verificado ou lacuna", menta significa "medido". Nenhuma outra coisa as usa, nem botão nem decoração.

**DeepSeek**
- A API aceita `deepseek-flash` e `deepseek-v4-pro`; rejeita `deepseek-v4-flash-0731`. Os modelos raciocinam, e tokens de raciocínio contam como saída.
- Os preços por milhão de tokens vêm de `DEEPSEEK_PRICE_INPUT_PER_M` e `DEEPSEEK_PRICE_OUTPUT_PER_M`. Confirme que valem para o modelo em uso.

## Testes

- Testes nunca chamam a rede: use um provedor falso (veja `tests/test_live.py`). Só `make llm-benchmark` e a execução ao vivo falam com a DeepSeek.
- Toda rota, verificação e transição de estado nova precisa de teste.
- Para regerar os benchmarks: **primeiro commite o código**, depois rode `make benchmark`, `make llm-benchmark` e `python scripts/benchmarks/project_stats.py` com a árvore limpa, e só então commite os JSONs. Assim o commit registrado é o do código medido.

## Acessibilidade e UI

- Contraste: texto pequeno precisa de 4.5:1. `tests/test_web.py::test_contrast_tokens_meet_wcag_aa_on_the_light_ground` trava os tokens; se mudar a paleta, rode os testes.
- Toda página tem um único `<h1>`, um `<main>` e o link "Pular para o conteúdo" (`base.html`).
- O anel de foco sobre o ledger escuro usa `--ledger-ink`; `--ink` é invisível ali.
- Tabelas de relatório ficam dentro de `.scroller`, para rolarem em vez de espremerem colunas no celular.
- CSS e JS são referenciados por `{{ asset('arquivo') }}`, que versiona pelo mtime e evita cache velho após deploy.

## Ambiente: editable install no macOS

O macOS marca o `.pth` do `pip install -e` como oculto e o Python 3.14 **ignora `.pth` ocultos**, então `import cutover` falha em silêncio. Os alvos do `make` rodam com `PYTHONPATH=src` e o `make install` desfaz a flag com `chflags nohidden`. Se `import cutover` falhar fora do make, é isso.

## Convenções

- Texto voltado ao usuário (app, README, relatório) em português do Brasil, com acentuação correta. Código, comandos e identificadores em inglês.
- Commits no estilo convencional (`feat:`, `fix:`, `docs:`, `chore:`).
- Aprofunde o que existe antes de criar: reutilize `GovernedAgent`, `build_gateway`, `check_mapping` e os componentes do `ledger.css`.
- Mudou a landing ou o relatório: verifique no navegador, inclusive em largura de celular (sem rolagem horizontal), e regere `docs/assets/landing.png` se o topo da landing mudou.

## Definição de pronto

`make test` e `make lint` passam; nenhuma chave, `.env` ou dado de usuário no commit; toda afirmação numérica na UI ou nos docs tem fonte reproduzível; e a mudança está descrita no README quando altera o que o produto faz.

## Limitações conhecidas

O app é de nó único (SQLite e uploads em disco), sem HTTPS por padrão, com cadastro aberto e limite de execuções ao vivo por usuário. O score que escolhe o nível é heurístico e precisa de calibração. A execução da migração não existe (fora do escopo); o código gerado não foi rodado em workspaces reais, e o notebook só passou por checagem de sintaxe. O baseline manual é informado pelo analista, não medido por um instrumento independente.
