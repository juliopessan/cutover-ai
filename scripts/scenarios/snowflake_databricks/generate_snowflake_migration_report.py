#!/usr/bin/env python3
"""
Gerador de relatório HTML consolidado da migração Snowflake → Databricks.
Usa SEMPRE o template padrão em `templates/dashboard.template.html`.
"""

import json
from pathlib import Path


def load_json(file_path: Path) -> dict:
    """Carrega arquivo JSON com fallback."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except Exception:
        return {}


def generate_html_report() -> str:
    """Gera relatório HTML usando o template padrão em `templates/dashboard.template.html`."""

    artifacts_dir = Path("outputs/snowflake-databricks")
    sf_summary = load_json(artifacts_dir / "synthetic_data/summary.json")
    account_meta = load_json(artifacts_dir / "synthetic_data/account_metadata.json")
    databases_payload = load_json(artifacts_dir / "synthetic_data/databases.json")
    lineage = load_json(artifacts_dir / "synthetic_data/data_lineage.json")
    rbac = load_json(artifacts_dir / "synthetic_data/rbac_grants.json")

    migration_plan = load_json(artifacts_dir / "migration_plan/migration_plan.json")
    compat_report = load_json(artifacts_dir / "migration_plan/compatibility_report.json")

    total_dbs = sf_summary.get("total_databases", 0)
    total_schemas = sf_summary.get("total_schemas", 0)
    total_tables = sf_summary.get("total_tables", 0)
    total_jobs = sf_summary.get("total_lineage_jobs", 0)
    total_grants = sf_summary.get("total_rbac_grants", 0)

    phases = migration_plan.get("phases", {})

    template_path = Path("templates/dashboard.template.html")
    if not template_path.exists():
        return "<html><body><h1>Template não encontrado</h1></body></html>"

    tpl = template_path.read_text(encoding="utf-8")

    exec_summary = f"""
<section>
  <div class='sec-label'>Resumo Executivo</div>
  <h2>Plano de Migração Snowflake → Databricks</h2>
  <p class='sec-intro'>Conta: <strong>{account_meta.get('account_name','N/A')}</strong> — {account_meta.get('edition','N/A')} em {account_meta.get('cloud_provider','N/A')} • {total_dbs} databases • {total_schemas} schemas • {total_tables} tabelas</p>
  <div class='grid-2'>
    <div class='grid-item'><h3>Jobs / Linhagem</h3><p>{total_jobs} tasks/streams/pipes mapeados</p></div>
    <div class='grid-item'><h3>RBAC</h3><p>{total_grants} grants a migrar para Unity Catalog</p></div>
  </div>
</section>
"""

    plan_html = """
<section>
  <div class='sec-label'>Plano</div>
  <h2>Fases e Tarefas</h2>
"""
    for phase_key, phase_data in phases.items():
        title = phase_data.get('title', phase_key)
        tasks = phase_data.get('tasks', [])
        plan_html += f"<div class='grid-2'><div class='grid-item'><h3>{title}</h3><ul>"
        for t in tasks:
            plan_html += f"<li class='mono'>{t.get('name','task')}</li>"
        plan_html += "</ul></div></div>"
    plan_html += "</section>"

    compat_html = """
<section>
  <div class='sec-label'>Compatibilidade</div>
  <h2>Validação Snowflake → Databricks</h2>
"""
    if compat_report.get('issues'):
        compat_html += "<div class='grid-2'><div class='grid-item'><h3>Problemas</h3><ul>"
        for issue in compat_report.get('issues', [])[:10]:
            compat_html += f"<li>{issue}</li>"
        compat_html += "</ul></div></div>"
    if compat_report.get('warnings'):
        compat_html += "<div class='grid-2'><div class='grid-item'><h3>Avisos</h3><ul>"
        for w in compat_report.get('warnings', [])[:10]:
            compat_html += f"<li>{w}</li>"
        compat_html += "</ul></div></div>"
    compat_html += "</section>"

    main_sections = exec_summary + plan_html + compat_html

    rendered = tpl.replace("{{PAGE_TITLE}}", "Migração Snowflake → Databricks")
    rendered = rendered.replace("{{PAGE_DESCRIPTION}}", "Relatório executivo de migração e validação Snowflake → Databricks")
    rendered = rendered.replace("{{LOADING_TEXT}}", "Preparando relatório…")
    rendered = rendered.replace("{{LOGO_TEXT}}", "DataMigration")
    rendered = rendered.replace("{{LOGO_SUFFIX}}", "Factory")
    rendered = rendered.replace("{{NAV_LINKS}}", "<a href='#top'>Início</a>")
    rendered = rendered.replace("{{EYEBROW}}", "Migração — Snowflake para Databricks")
    rendered = rendered.replace("{{HERO_TITLE}}", "Migração Snowflake → Databricks")
    rendered = rendered.replace("{{HERO_SUBTITLE}}", f"{total_dbs} databases • {total_schemas} schemas • {total_tables} tabelas • {total_jobs} jobs")
    rendered = rendered.replace("{{HERO_BUTTONS}}", "<a class='btn btn-primary' href='#meter'>Ver Métricas</a>")
    rendered = rendered.replace("{{METER_TITLE}}", "Visão Geral")
    rendered = rendered.replace("{{METER_SUBTITLE}}", "Resumo rápido")

    meter_cells = f"<div class='meter-cell'><div class='val ember'>{total_tables}</div><div class='lbl'>Tabelas</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_dbs}</div><div class='lbl'>Databases</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_jobs}</div><div class='lbl'>Jobs</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_grants}</div><div class='lbl'>Grants RBAC</div></div>"
    rendered = rendered.replace("{{METER_CELLS}}", meter_cells)

    rendered = rendered.replace("{{MAIN_SECTIONS}}", main_sections)
    rendered = rendered.replace("{{CTA_TITLE}}", "Próximos Passos")
    rendered = rendered.replace("{{CTA_SUBTITLE}}", "Revisar compatibilidade e executar piloto em schema não-crítico")
    rendered = rendered.replace("{{CTA_LINK}}", "#top")
    rendered = rendered.replace("{{CTA_BUTTON_TEXT}}", "Iniciar Piloto")
    rendered = rendered.replace("{{FOOTER_LEFT}}", "Relatório confidencial — Data Migration Factory")
    rendered = rendered.replace("{{FOOTER_RIGHT}}", "© 2026 Avanade")

    return rendered


def main():
    """Gera e salva relatório HTML."""
    output_dir = Path("outputs/snowflake-databricks")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("🎨 Gerando relatório HTML (Snowflake → Databricks)...\n")

    html = generate_html_report()

    output_file = output_dir / "migration_report.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Relatório gerado com sucesso!")
    print(f"\n📄 Arquivo: {output_file}")
    print(f"📊 Abra em seu navegador para visualizar\n")


if __name__ == "__main__":
    main()
