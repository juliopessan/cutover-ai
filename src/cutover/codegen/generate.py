from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./:@\- ]{1,300}$")
DELTA_TYPES = ("string", "int", "bigint", "double", "decimal", "boolean", "date", "timestamp")
TARGETS = ("databricks", "microsoft_fabric")
HEADROOM_DIGITS = 4
VARCHAR_BUCKETS = (16, 32, 64, 128, 256, 512, 1024, 4000, 8000)


class CodegenError(ValueError):
    """The approved mapping or the parameters cannot be turned into safe code."""


@dataclass(frozen=True)
class Params:
    table: str
    schema: str
    catalog: str | None
    source_path: str
    drop_duplicates: bool = False

    def validate(self, target: str) -> None:
        for label, value in (("tabela", self.table), ("schema", self.schema)):
            if not IDENT.match(value or ""):
                raise CodegenError(f"Nome de {label} inválido: use letras, dígitos e _ (começando por letra ou _).")
        if target == "databricks" and not IDENT.match(self.catalog or ""):
            raise CodegenError("Nome de catálogo inválido: use letras, dígitos e _ (começando por letra ou _).")
        if not SAFE_PATH.match(self.source_path or ""):
            raise CodegenError("Caminho de origem inválido: use letras, dígitos e . _ / : @ - (sem aspas).")


@dataclass(frozen=True)
class ColumnPlan:
    source: str
    target: str
    kind: str
    profile: dict[str, Any]


def default_params(filename: str, target: str) -> Params:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", filename.rsplit(".", 1)[0]).strip("_").lower() or "dataset"
    if not re.match(r"[a-z_]", stem[0]):
        stem = "t_" + stem
    table = stem[:100]
    if target == "databricks":
        return Params(table, "bronze", "main", f"/Volumes/main/bronze/landing/{filename}")
    return Params(table, "dbo", None, f"Files/landing/{filename}")


def plan_columns(profile: dict[str, Any], mappings: dict[str, Any]) -> list[ColumnPlan]:
    """Join the approved mapping with the measured profile, in source order. Refuses anything unsafe."""
    plans: list[ColumnPlan] = []
    seen: dict[str, str] = {}
    for column in profile["columns"]:
        entry = mappings.get(column["name"])
        if not isinstance(entry, dict) or "target" not in entry or "type" not in entry:
            raise CodegenError(f"A coluna {column['name']!r} não tem destino e tipo no mapeamento aprovado.")
        target, kind = str(entry["target"]), str(entry["type"])
        if not IDENT.match(target) or target != target.lower():
            raise CodegenError(f"Nome de destino inseguro para a coluna {column['name']!r}: {target!r}.")
        if kind not in DELTA_TYPES:
            raise CodegenError(f"Tipo não suportado para {column['name']!r}: {kind!r}.")
        if target in seen:
            raise CodegenError(f"Destino repetido: {target!r} ({seen[target]!r} e {column['name']!r}).")
        seen[target] = column["name"]
        plans.append(ColumnPlan(column["name"], target, kind, column))
    return plans


# ---- types -------------------------------------------------------------------------------------

def _decimal_shape(col: ColumnPlan) -> tuple[int, int]:
    digits, scale = col.profile.get("max_int_digits"), col.profile.get("max_scale")
    if digits is None or scale is None:
        return 38, 10
    return min(38, max(1, digits + scale + HEADROOM_DIGITS)), scale


def spark_type(col: ColumnPlan) -> str:
    if col.kind == "decimal":
        precision, scale = _decimal_shape(col)
        return f"DECIMAL({precision},{scale})"
    return col.kind.upper()


def tsql_type(col: ColumnPlan) -> str:
    if col.kind == "string":
        # The profile measures characters, but a UTF-8 VARCHAR(n) counts bytes and an accented letter takes
        # two, so size for the worst case of 2 bytes per character before rounding up to a bucket.
        wanted = max(int(col.profile.get("max_len") or 1), 1) * 2
        return f"VARCHAR({next((b for b in VARCHAR_BUCKETS if b >= wanted), 8000)})"
    if col.kind == "decimal":
        precision, scale = _decimal_shape(col)
        return f"DECIMAL({precision},{scale})"
    return {"int": "INT", "bigint": "BIGINT", "double": "FLOAT", "boolean": "BIT", "date": "DATE",
            "timestamp": "DATETIME2(6)"}[col.kind]


SPARK_ENCODINGS = {"utf-8": "UTF-8", "windows-1252": "windows-1252", "latin-1": "ISO-8859-1"}
NUMERIC_TARGETS = ("int", "bigint", "double", "decimal")


def column_formats(cols: list[ColumnPlan]) -> dict[str, dict[str, str]]:
    """The source formats the profile MEASURED, keyed by source column, for the load to parse with."""
    formats: dict[str, dict[str, str]] = {}
    for c in cols:
        entry: dict[str, str] = {}
        if c.kind in ("date", "timestamp") and c.profile.get("date_format"):
            entry["date"] = str(c.profile["date_format"])
        if c.kind in NUMERIC_TARGETS and c.profile.get("number_style") == "br":
            entry["number"] = "br"
        if entry:
            formats[c.source] = entry
    return formats


# ---- helpers -----------------------------------------------------------------------------------

def _sql_str(value: str, target: str = "microsoft_fabric") -> str:
    """A SQL string literal for the target dialect. Spark escapes with a backslash; T-SQL doubles the quote."""
    value = value.replace("\r", " ").replace("\n", " ")
    if target == "databricks":
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return "'" + value.replace("'", "''") + "'"


def _fqn(target: str, p: Params, *, quoted: bool) -> str:
    if target == "databricks":
        return f"`{p.catalog}`.`{p.schema}`.`{p.table}`" if quoted else f"{p.catalog}.{p.schema}.{p.table}"
    return f"[{p.schema}].[{p.table}]" if quoted else f"{p.schema}.{p.table}"


def _q(target: str, name: str) -> str:
    return f"`{name}`" if target == "databricks" else f"[{name}]"


# ---- DDL ---------------------------------------------------------------------------------------

def ddl(target: str, cols: list[ColumnPlan], p: Params, filename: str) -> str:
    header = [f"-- Estrutura de destino de {filename}, gerada do mapeamento APROVADO.",
              "-- Tipos de origem medidos no perfil; decimais incluem "
              f"{HEADROOM_DIGITS} dígitos de folga sobre o mínimo observado.",
              "-- Este CREATE falha se a tabela já existir: nada é sobrescrito."]
    lines = []
    for i, c in enumerate(cols):
        comma = "," if i < len(cols) - 1 else ""
        if target == "databricks":
            lines.append(f"  {_q(target, c.target)} {spark_type(c)} COMMENT {_sql_str('origem: ' + c.source, target)}{comma}")
        else:
            origin = c.source.replace("\r", " ").replace("\n", " ")
            lines.append(f"  {_q(target, c.target)} {tsql_type(c)} NULL{comma}  -- origem: {origin}")
    tail = "\n) USING DELTA;" if target == "databricks" else "\n);"
    return "\n".join(header) + f"\nCREATE TABLE {_fqn(target, p, quoted=True)} (\n" + "\n".join(lines) + tail + "\n"


# ---- reconciliation ----------------------------------------------------------------------------

def reconciliation(target: str, cols: list[ColumnPlan], p: Params, profile: dict[str, Any]) -> str:
    """Checks against numbers MEASURED on the source file. Each row says expected, actual and OK or DIVERGE."""
    spark = target == "databricks"
    table = _fqn(target, p, quoted=True)
    length = "LENGTH" if spark else "LEN"
    rows = profile["rows"] - (profile["duplicate_rows"] if p.drop_duplicates else 0)
    big = "COUNT(*)" if spark else "COUNT_BIG(*)"
    parts = [f"SELECT 'linhas' AS verificacao, {_sql_str(str(rows), target)} AS esperado, CAST({big} AS "
             f"{'STRING' if spark else 'VARCHAR(40)'}) AS obtido, CASE WHEN {big} = {rows} THEN 'OK' ELSE 'DIVERGE' END AS status FROM {table}"]

    def check(name: str, expected: str, actual: str, condition: str) -> str:
        cast = "STRING" if spark else "VARCHAR(400)"
        return (f"SELECT {_sql_str(name, target)}, {_sql_str(expected, target)}, CAST({actual} AS {cast}), "
                f"CASE WHEN {condition} THEN 'OK' ELSE 'DIVERGE' END FROM {table}")

    for c in cols:
        col, prof = _q(target, c.target), c.profile
        if not p.drop_duplicates:
            nulls = int(prof["nulls"])
            parts.append(check(f"nulos({c.target})", str(nulls),
                               f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)",
                               f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) = {nulls}"))
            if prof.get("distinct") is not None:
                parts.append(check(f"distintos({c.target})", str(prof["distinct"]), f"COUNT(DISTINCT {col})",
                                   f"COUNT(DISTINCT {col}) = {prof['distinct']}"))
        if c.kind in ("int", "bigint", "decimal", "double") and prof.get("min") is not None:
            for fn, key in (("MIN", "min"), ("MAX", "max")):
                parts.append(check(f"{fn.lower()}({c.target})", str(prof[key]), f"{fn}({col})",
                                   f"{fn}({col}) = {prof[key]}"))
        elif c.kind == "date" and prof.get("min"):
            for fn, key in (("MIN", "min"), ("MAX", "max")):
                literal = f"DATE {_sql_str(prof[key], target)}" if spark else f"CAST({_sql_str(prof[key], target)} AS DATE)"
                parts.append(check(f"{fn.lower()}({c.target})", str(prof[key]), f"{fn}({col})",
                                   f"{fn}({col}) = {literal}"))
        elif c.kind == "string" and prof.get("max_len"):
            parts.append(check(f"tamanho_max({c.target})", str(prof["max_len"]), f"MAX({length}({col}))",
                               f"MAX({length}({col})) = {prof['max_len']}"))
    head = ["-- Reconciliação: compara o destino com os números MEDIDOS no arquivo de origem.",
            f"-- SHA-256 do arquivo de origem: {profile['sha256']}",
            "-- Qualquer linha com status DIVERGE precisa ser explicada antes de usar a tabela."]
    return "\n".join(head) + "\n" + "\nUNION ALL\n".join(parts) + ";\n"


# ---- load notebook -----------------------------------------------------------------------------

def _py_columns(cols: list[ColumnPlan]) -> str:
    rows = [f"    ({json.dumps(c.source, ensure_ascii=False)}, {json.dumps(c.target)}, {json.dumps(spark_type(c))})," for c in cols]
    return "COLUMNS = [\n" + "\n".join(rows) + "\n]"


def notebook_cells(target: str, cols: list[ColumnPlan], p: Params, filename: str, profile: dict[str, Any]) -> list[str]:
    fqn = _fqn(target, p, quoted=False)
    table_expr = json.dumps(fqn if target == "databricks" else p.table)
    title = "Databricks" if target == "databricks" else "Microsoft Fabric (Lakehouse)"
    return [
        f'''# Carga de {filename} para {title}
# Gerado pelo Cutover a partir do mapeamento APROVADO. Revise antes de rodar: este código NÃO foi
# executado em um ambiente real. Ele só cria e carrega a tabela de destino; nunca apaga nada.
# SHA-256 esperado do arquivo de origem: {profile["sha256"]}''',
        f'''from pyspark.sql import functions as F

SOURCE_PATH = {json.dumps(p.source_path)}
TARGET_TABLE = {table_expr}
DELIMITER = {json.dumps(profile.get("delimiter") or ",")}
ENCODING = {json.dumps(SPARK_ENCODINGS.get(profile.get("encoding", "utf-8"), "UTF-8"))}   # codificação medida no arquivo de origem
# Formatos medidos na origem: data com o padrão do Spark; "br" = ponto de milhar e vírgula decimal (1.234,56).
FORMATS = {json.dumps(column_formats(cols), ensure_ascii=False)}
DROP_EXACT_DUPLICATES = {p.drop_duplicates}   # o perfil mediu {profile["duplicate_rows"]} linhas duplicadas
EXPECTED_ROWS = {profile["rows"] - (profile["duplicate_rows"] if p.drop_duplicates else 0)}   # medido no arquivo de origem''',
        _py_columns(cols),
        '''# 1) Leitura: linhas com número de campos diferente do cabeçalho são descartadas, como no perfil.
raw = (spark.read.format("csv")
       .option("header", True).option("delimiter", DELIMITER).option("encoding", ENCODING)
       .option("mode", "DROPMALFORMED").option("inferSchema", False)
       .load(SOURCE_PATH))''',
        '''# 2) Transformação: renomeia, apara espaços (o perfil também apara) e converte para o tipo aprovado.
def bq(name):
    return "`" + name.replace("`", "``") + "`"

trimmed = {src: F.trim(F.col(bq(src))) for src, _, _ in COLUMNS}

def convert(src, kind):
    column, fmt = trimmed[src], FORMATS.get(src, {})
    if fmt.get("number") == "br" and kind != "STRING":
        # 1.234,56 vira 1234.56: tira os pontos de milhar e troca a vírgula decimal por ponto.
        column = F.regexp_replace(F.regexp_replace(column, r"\\.", ""), ",", ".")
    if kind == "DATE" and "date" in fmt:
        return F.to_date(column, fmt["date"])
    if kind == "TIMESTAMP" and "date" in fmt:
        return F.to_timestamp(column, fmt["date"])
    return column.cast(kind)

converted = [convert(src, kind).alias(dst) for src, dst, kind in COLUMNS]
out = raw.select(*converted)
if DROP_EXACT_DUPLICATES:
    out = out.dropDuplicates()''',
        '''# 3) Segurança da conversão: um valor que existia na origem e virou nulo foi PERDIDO na conversão.
lost = raw.select(*[
    F.sum(F.when((trimmed[src] != "") & convert(src, kind).isNull(), 1).otherwise(0)).alias(dst)
    for src, dst, kind in COLUMNS
]).first().asDict()
lost = {k: v for k, v in lost.items() if v}
if lost:
    raise ValueError(f"Conversão perdeu valores (coluna: linhas): {lost}. Ajuste o tipo ou o formato antes de carregar.")''',
        '''# 4) Contagem contra o perfil medido.
rows = out.count()
print(f"linhas carregáveis: {rows} (esperado {EXPECTED_ROWS})")
if rows != EXPECTED_ROWS:
    raise ValueError("A contagem difere do perfil da origem. Investigue antes de escrever.")''',
        '''# 5) Escrita: só em tabela inexistente ou vazia, para que reexecutar não duplique dados.
if spark.catalog.tableExists(TARGET_TABLE) and spark.table(TARGET_TABLE).limit(1).count() > 0:
    raise RuntimeError(f"{TARGET_TABLE} já tem dados. Nada foi escrito.")
out.write.format("delta").mode("append").saveAsTable(TARGET_TABLE)
print("carga concluída; rode 03_reconciliacao para conferir os números.")''',
    ]


def render_databricks_notebook(cells: list[str]) -> str:
    return "# Databricks notebook source\n" + "\n\n# COMMAND ----------\n\n".join(cells) + "\n"


def render_ipynb(cells: list[str]) -> str:
    body = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}, "kernel_info": {"name": "synapse_pyspark"}},
        "cells": [{"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                   "source": cell.splitlines(keepends=True)} for cell in cells],
    }
    return json.dumps(body, ensure_ascii=False, indent=1) + "\n"


# ---- README and bundle -------------------------------------------------------------------------

def readme(target: str, cols: list[ColumnPlan], p: Params, filename: str, profile: dict[str, Any], run: dict[str, Any]) -> str:
    where = "Databricks (Unity Catalog)" if target == "databricks" else "Microsoft Fabric"
    risks = []
    if profile["duplicate_rows"]:
        risks.append(f"- {profile['duplicate_rows']} linhas duplicadas: a carga mantém todas por padrão "
                     "(`DROP_EXACT_DUPLICATES = False`); decida antes de rodar.")
    if any(c.profile["type"] == "mixed" for c in cols):
        risks.append("- Colunas com tipos misturados foram mapeadas conforme o mapeamento aprovado; confira a conversão.")
    if profile.get("privacy_hints"):
        names = ", ".join(h["column"] for h in profile["privacy_hints"])
        risks.append(f"- Possíveis dados pessoais (heurística por nome): {names}. Trate conforme a LGPD antes de carregar.")
    for f in profile.get("flags", []):
        if f["kind"] == "identical_columns":
            risks.append(f"- Colunas com conteúdo idêntico: {', '.join(f['items'])}. Confirme se uma é redundante.")
    risks_text = "\n".join(risks) or "- Nenhum risco adicional apontado pelo perfil."
    edited_note = ""
    if run.get("edited"):
        edited_note = (f"> **Mapeamento corrigido.** A sugestão do modelo foi alterada {len(run.get('edit_log') or [])} vez(es) "
                       "antes da aprovação; a original e cada mudança ficam registradas no Cutover.\n\n")
    steps = ["1. Envie o arquivo de origem para o caminho indicado em `SOURCE_PATH` e confira o SHA-256 abaixo.",
             "2. Execute `01_ddl` (cria a tabela; falha se ela já existir).",
             f"3. Importe e execute `02_carga` ({'.py como notebook do Databricks' if target == 'databricks' else '.ipynb no Lakehouse do Fabric'}).",
             "4. Execute `03_reconciliacao` e resolva qualquer linha com `DIVERGE`."]
    return f"""# Pacote de migração: {filename} para {where}

Gerado pelo Cutover em {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} a partir da execução #{run['id']},
**aprovada por {run.get('decided_by') or '—'} em {run.get('decided_at') or '—'} UTC**.

{edited_note}> **Não verificado em ambiente real.** O código foi gerado por templates e validado só quanto à
> sintaxe (SQL com sqlglot, Python com `ast`). Não foi executado em um workspace do {where}.
> Rode primeiro em um ambiente de teste. Nada aqui apaga ou sobrescreve dados.
> Roteiro de validação passo a passo: `docs/roteiro-validacao-workspace.md` no repositório do Cutover.

## Destino
`{_fqn(target, p, quoted=False)}` · origem: `{p.source_path}`
SHA-256 do arquivo de origem: `{profile['sha256']}` ({profile['rows']:,} linhas, {len(cols)} colunas).

## Ordem de execução
{chr(10).join(steps)}

## Mapeamento aplicado
| Origem | Destino | Tipo |
|---|---|---|
""" + "\n".join(f"| {c.source} | {c.target} | {spark_type(c) if target == 'databricks' else tsql_type(c)} |" for c in cols) + f"""

## Pontos de atenção
{risks_text}

## Como as verificações funcionam
Os valores esperados em `03_reconciliacao` foram **medidos no arquivo de origem** (linhas, nulos,
distintos, mínimo, máximo e tamanho). Eles só valem se o arquivo carregado for o de SHA-256 acima.
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_bundle(*, target: str, dataset: dict[str, Any], profile: dict[str, Any], run: dict[str, Any],
                 params: Params) -> dict[str, str]:
    """Return ``{filename: content}`` for one target. Raises CodegenError unless the run is approved."""
    if target not in TARGETS:
        raise CodegenError("Destino desconhecido.")
    if run.get("decision") != "approved":
        raise CodegenError("O mapeamento precisa estar aprovado antes de gerar código.")
    params.validate(target)
    # The uploaded filename lands in comments; a line break would end the comment and start code.
    filename = re.sub(r"[\x00-\x1f\x7f]", " ", str(dataset["filename"]))
    cols = plan_columns(profile, run["mappings"])
    cells = notebook_cells(target, cols, params, filename, profile)
    if target == "databricks":
        files = {"01_ddl.sql": ddl(target, cols, params, filename),
                 "02_carga.py": render_databricks_notebook(cells)}
    else:
        files = {"01_ddl_warehouse.sql": ddl(target, cols, params, filename),
                 "02_carga_lakehouse.ipynb": render_ipynb(cells)}
    files["03_reconciliacao.sql"] = reconciliation(target, cols, params, profile)
    files["README.md"] = readme(target, cols, params, filename, profile, run)
    manifest = {
        "gerado_por": "cutover", "gerado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "destino": target, "dataset": filename, "sha256_origem": profile["sha256"],
        "execucao": run["id"], "aprovado_por": run.get("decided_by"), "aprovado_em": run.get("decided_at"),
        # The approval covers this exact mapping; the hash lets anyone check that the code was built from it.
        "mapeamento_sha256": _sha(json.dumps(run["mappings"], sort_keys=True, ensure_ascii=False)),
        "mapeamento_editado": bool(run.get("edited")), "edicoes": len(run.get("edit_log") or []),
        "codificacao_origem": profile.get("encoding", "utf-8"), "formatos_medidos": column_formats(cols),
        "parametros": {"tabela": params.table, "schema": params.schema, "catalogo": params.catalog,
                       "caminho_origem": params.source_path, "remover_duplicatas": params.drop_duplicates},
        "arquivos": {name: _sha(text) for name, text in files.items()},
        "executado": False,
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    return files


def zip_bundle(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()
