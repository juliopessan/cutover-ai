#!/usr/bin/env python3
"""
Generate comprehensive migration report in HTML and Markdown.
HTML SEMPRE usa o template padrão em `templates/dashboard.template.html`.
"""

import json
from pathlib import Path
from datetime import datetime


def load_json(file_path):
    """Load JSON file"""
    with open(file_path) as f:
        return json.load(f)


def generate_html_report(catalog, migration_plan, validation):
    """Gera relatório HTML usando o template padrão em `templates/dashboard.template.html`."""

    template_path = Path("templates/dashboard.template.html")
    if not template_path.exists():
        return "<html><body><h1>Template não encontrado</h1></body></html>"

    tpl = template_path.read_text(encoding="utf-8")

    capacity = migration_plan.get("metadata", {}).get("capacity") or migration_plan.get("capacity", {})

    exec_summary = f"""
<section>
  <div class='sec-label'>Resumo Executivo</div>
  <h2>Migração Cloudera → Microsoft Fabric</h2>
  <p class='sec-intro'>Cluster: <strong>{catalog['cluster_name']}</strong> • {capacity['total_databases']} databases • {capacity['total_tables']} tabelas • {capacity['total_rows']:,} linhas • {capacity['total_size_gb']:.1f} GB</p>
  <div class='grid-2'>
    <div class='grid-item'><h3>Capacity Units</h3><p>{capacity['estimated_cu']} CUs estimadas</p></div>
    <div class='grid-item'><h3>Custo Mensal</h3><p>USD ${capacity['monthly_cost_usd']:,.0f} (~${capacity['monthly_cost_usd'] * 12:,.0f}/ano)</p></div>
  </div>
</section>
"""

    db_rows_html = ""
    for db in catalog["databases"]:
        db_tables = len(db["tables"])
        db_rows = sum(t["row_count"] for t in db["tables"])
        db_size = sum(t["storage_size_gb"] for t in db["tables"])
        db_rows_html += f"<tr><td><strong>{db['name']}</strong></td><td class='mono'>{db_tables}</td><td class='mono'>{db_rows:,}</td><td class='mono'>{db_size:.2f}</td></tr>"

    databases_html = f"""
<section>
  <div class='sec-label'>Cat\u00e1logo</div>
  <h2>Detalhe de Databases</h2>
  <table class='data-table'>
    <thead><tr><th>Database</th><th>Tabelas</th><th>Linhas</th><th>Tamanho (GB)</th></tr></thead>
    <tbody>{db_rows_html}</tbody>
  </table>
</section>
"""

    validation_rows = ""
    for check in validation["validations"]:
        evidence = ""
        if isinstance(check.get("evidence"), dict):
            evidence = "<br>" + "<br>".join(f"{k}: {v}" for k, v in check["evidence"].items())
        validation_rows += f"<tr><td>{check['check']}</td><td>{check['status']}</td><td>{check['message']}{evidence}</td></tr>"

    validation_html = f"""
<section>
  <div class='sec-label'>Valida\u00e7\u00e3o</div>
  <h2>Resultados dos Checks</h2>
  <p class='sec-intro'>Total: {validation['total_checks']} • Passou: {validation['passed']} • Falhou: {validation['failed']}</p>
  <table class='data-table'>
    <thead><tr><th>Check</th><th>Status</th><th>Detalhes</th></tr></thead>
    <tbody>{validation_rows}</tbody>
  </table>
</section>
"""

    deployment_steps = migration_plan.get("deployment_plan", [])
    total_duration = sum(step["duration_hours"] for step in deployment_steps)
    deployment_html = "<section><div class='sec-label'>Plano</div><h2>Deployment Plan</h2>"
    deployment_html += f"<p class='sec-intro'>Dura\u00e7\u00e3o total: {total_duration:.1f}h (~{total_duration/8:.1f} dias \u00fateis)</p>"
    for step in deployment_steps:
        deployment_html += f"<div class='grid-2'><div class='grid-item'><h3>Passo {step['step']}: {step['task']}</h3><p>{step['description']}</p><p class='mono'>Fase: {step['phase']} • Dura\u00e7\u00e3o: {step['duration_hours']:.1f}h • Risco: {step['risk'].upper()}</p></div></div>"
    deployment_html += "</section>"

    risk_assessment = migration_plan.get("risk_assessment", [])
    risk_html = "<section><div class='sec-label'>Riscos</div><h2>Avalia\u00e7\u00e3o de Riscos</h2><table class='data-table'><thead><tr><th>ID</th><th>Categoria</th><th>Severidade</th><th>Descri\u00e7\u00e3o</th><th>Mitiga\u00e7\u00e3o</th></tr></thead><tbody>"
    for risk in risk_assessment:
        risk_html += f"<tr><td class='mono'>{risk['risk_id']}</td><td>{risk['category']}</td><td>{risk['severity'].upper()}</td><td>{risk['description']}</td><td>{risk['mitigation']}</td></tr>"
    risk_html += "</tbody></table></section>"

    main_sections = exec_summary + databases_html + validation_html + deployment_html + risk_html

    rendered = tpl.replace("{{PAGE_TITLE}}", "Migração Cloudera → Microsoft Fabric (Legacy)")
    rendered = rendered.replace("{{PAGE_DESCRIPTION}}", "Relatório executivo abrangente de migração e validação")
    rendered = rendered.replace("{{LOADING_TEXT}}", "Preparando relatório…")
    rendered = rendered.replace("{{LOGO_TEXT}}", "DataMigration")
    rendered = rendered.replace("{{LOGO_SUFFIX}}", "Factory")
    rendered = rendered.replace("{{NAV_LINKS}}", "<a href='#top'>Início</a>")
    rendered = rendered.replace("{{EYEBROW}}", "Migração — Cloudera para Microsoft Fabric")
    rendered = rendered.replace("{{HERO_TITLE}}", "Migração Cloudera → Microsoft Fabric")
    rendered = rendered.replace("{{HERO_SUBTITLE}}", f"{capacity['total_databases']} databases • {capacity['total_tables']} tabelas • {capacity['total_rows']:,} linhas")
    rendered = rendered.replace("{{HERO_BUTTONS}}", "<a class='btn btn-primary' href='#meter'>Ver Métricas</a>")
    rendered = rendered.replace("{{METER_TITLE}}", "Visão Geral")
    rendered = rendered.replace("{{METER_SUBTITLE}}", "Resumo rápido")

    meter_cells = f"<div class='meter-cell'><div class='val ember'>{capacity['total_tables']}</div><div class='lbl'>Tabelas</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{capacity['total_databases']}</div><div class='lbl'>Databases</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{validation['passed']}</div><div class='lbl'>Checks OK</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{validation['failed']}</div><div class='lbl'>Checks Falhos</div></div>"
    rendered = rendered.replace("{{METER_CELLS}}", meter_cells)

    rendered = rendered.replace("{{MAIN_SECTIONS}}", main_sections)
    rendered = rendered.replace("{{CTA_TITLE}}", "Próximos Passos")
    rendered = rendered.replace("{{CTA_SUBTITLE}}", "Revisar capacity planning e executar piloto")
    rendered = rendered.replace("{{CTA_LINK}}", "#top")
    rendered = rendered.replace("{{CTA_BUTTON_TEXT}}", "Iniciar Piloto")
    rendered = rendered.replace("{{FOOTER_LEFT}}", "Relatório confidencial — Data Migration Factory")
    rendered = rendered.replace("{{FOOTER_RIGHT}}", "© 2026 Avanade")

    return rendered


def generate_markdown_report(catalog, migration_plan, validation):
    """Generate Markdown report"""
    
    capacity = migration_plan.get("metadata", {}).get("capacity") or migration_plan.get("capacity", {})
    
    md = f"""# Cloudera to Fabric Migration Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Executive Summary

| Metric | Value |
|--------|-------|
| Cluster | {catalog['cluster_name']} |
| Source | Cloudera Hive |
| Target | Microsoft Fabric |
| Databases | {capacity.get('total_databases', 'N/A')} |
| Tables | {capacity.get('total_tables', 'N/A')} |
| Total Rows | {capacity.get('total_rows', 'N/A'):,} |
| Data Volume | {capacity.get('total_size_gb', 'N/A'):.1f} GB |

## Capacity Planning

- **Estimated Capacity Units:** {capacity.get('estimated_cu', 'N/A')} CUs
- **Daily Cost:** ${capacity.get('daily_cost_usd', 'N/A'):,} USD
- **Monthly Cost:** ${capacity.get('monthly_cost_usd', 'N/A'):,} USD
- **Annual Cost:** ${capacity.get('monthly_cost_usd', 0) * 12:,.0f} USD

## Database Details

| Database | Tables | Rows | Size (GB) |
|----------|--------|------|-----------|
"""
    
    for db in catalog["databases"]:
        db_tables = len(db["tables"])
        db_rows = sum(t["row_count"] for t in db["tables"])
        db_size = sum(t["storage_size_gb"] for t in db["tables"])
        md += f"| {db['name']} | {db_tables} | {db_rows:,} | {db_size:.2f} |\n"
    
    md += f"""

## Table Catalog

"""
    
    for db in catalog["databases"]:
        md += f"### {db['name'].upper()}\n\n"
        for table in db["tables"]:
            md += f"#### {table['table_name']}\n"
            md += f"- **Rows:** {table['row_count']:,}\n"
            md += f"- **Size:** {table['storage_size_gb']:.2f} GB\n"
            md += f"- **Columns:** {len(table['columns'])}\n"
            md += f"- **Partitions:** {', '.join(table['partitions']) if table['partitions'] else 'None'}\n\n"
    
    md += f"""
## Validation Results

- **Total Checks:** {validation['total_checks']}
- **Passed:** {validation['passed']} ✅
- **Failed:** {validation['failed']} ❌

| Check | Status | Details |
|-------|--------|---------|
"""
    
    for check in validation["validations"]:
        md += f"| {check['check']} | {check['status']} | {check['message']} |\n"
    
    deployment_steps = migration_plan.get("deployment_plan", [])
    total_duration = sum(step["duration_hours"] for step in deployment_steps)
    
    md += f"""

## Deployment Plan

**Total Duration:** {total_duration:.1f} hours (~{total_duration/8:.1f} business days)

| # | Phase | Task | Duration | Risk |
|---|-------|------|----------|------|
"""
    
    for step in deployment_steps:
        md += f"| {step['step']} | {step['phase']} | {step['task']} | {step['duration_hours']:.1f}h | {step['risk'].upper()} |\n"
    
    md += f"""

## Risk Assessment

| ID | Category | Severity | Description | Mitigation |
|----|----------|----------|-------------|-----------|
"""
    
    risk_assessment = migration_plan.get("risk_assessment", [])
    for risk in risk_assessment:
        md += f"| {risk['risk_id']} | {risk['category']} | {risk['severity'].upper()} | {risk['description']} | {risk['mitigation']} |\n"
    
    md += f"""

## Next Steps

1. Review capacity planning and cost estimates
2. Validate schema mappings
3. Plan data migration windows
4. Set up Fabric workspace and lakehouses
5. Configure Data Factory pipelines
6. Execute UAT and validation
7. Plan cutover strategy

---

**Status:** Planning Phase  
**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    return md


def main():
    print("📄 Generating comprehensive reports...")
    
    # Load data
    catalog = load_json("outputs/sap-cloudera-legacy/synthetic_data/cloudera_metastore.json")
    migration_plan = load_json("outputs/sap-cloudera-legacy/migration_output/migration_plan.json")
    validation = load_json("outputs/sap-cloudera-legacy/migration_output/validation_report.json")
    
    # Generate reports
    html_report = generate_html_report(catalog, migration_plan, validation)
    md_report = generate_markdown_report(catalog, migration_plan, validation)
    
    # Save reports
    output_dir = Path("outputs/sap-cloudera-legacy/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    html_file = output_dir / "migration_report.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_report)
    
    md_file = output_dir / "migration_report.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_report)
    
    print(f"✅ HTML Report: {html_file}")
    print(f"✅ Markdown Report: {md_file}")


if __name__ == "__main__":
    main()

