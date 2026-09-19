#!/usr/bin/env python3
"""
Gerador de relatório HTML consolidado da migração Cloudera → Fabric.
"""

import json
from datetime import datetime
from pathlib import Path


def load_json(file_path: Path) -> dict:
    """Carrega arquivo JSON com fallback."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except:
        return {}


def generate_html_report() -> str:
    """Gera relatório HTML usando o template padrão em `templates/dashboard.template.html`."""

    artifacts_dir = Path("outputs/cloudera-fabric")
    cloudera_summary = load_json(artifacts_dir / "synthetic_data/summary.json")
    cluster_meta = load_json(artifacts_dir / "synthetic_data/cluster_metadata.json")
    hive_data = load_json(artifacts_dir / "synthetic_data/hive_databases.json")
    lineage = load_json(artifacts_dir / "synthetic_data/data_lineage.json")
    permissions = load_json(artifacts_dir / "synthetic_data/user_permissions.json")

    migration_summary = load_json(artifacts_dir / "migration_plan/summary.json")
    migration_plan = load_json(artifacts_dir / "migration_plan/migration_plan.json")
    compat_report = load_json(artifacts_dir / "migration_plan/compatibility_report.json")

    # Basic statistics
    total_tables = cloudera_summary.get("total_tables", 0)
    total_dbs = cloudera_summary.get("total_databases", 0)
    total_jobs = cloudera_summary.get("total_lineage_jobs", 0)
    total_perms = cloudera_summary.get("total_user_permissions", 0)

    phases = migration_plan.get("phases", {})
    total_tasks = sum(len(p.get("tasks", [])) for p in phases.values())

    # Load template
    template_path = Path("templates/dashboard.template.html")
    if not template_path.exists():
        # fallback to simple page
        return "<html><body><h1>Template não encontrado</h1></body></html>"

    tpl = template_path.read_text(encoding="utf-8")

    # Build MAIN_SECTIONS content (kept concise, compatible with template)
    exec_summary = f"""
<section>
  <div class='sec-label'>Resumo Executivo</div>
  <h2>Plano de Migração</h2>
  <p class='sec-intro'>Cluster: <strong>{cluster_meta.get('cluster_name','N/A')}</strong> — {cluster_meta.get('version','N/A')} • {total_dbs} DBs • {total_tables} tabelas</p>
  <div class='grid-2'>
    <div class='grid-item'><h3>Jobs / Linhagem</h3><p>{total_jobs} transformações mapeadas</p></div>
    <div class='grid-item'><h3>Permissões</h3><p>{total_perms} entradas de permissão</p></div>
  </div>
</section>
"""

    # Plan sections
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

    # Compatibility
    compat_html = """
<section>
  <div class='sec-label'>Compatibilidade</div>
  <h2>Validação</h2>
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

    # Combine main sections
    main_sections = exec_summary + plan_html + compat_html

    # Simple replacements
    rendered = tpl.replace("{{PAGE_TITLE}}", "Migração Cloudera → Microsoft Fabric")
    rendered = rendered.replace("{{PAGE_DESCRIPTION}}", "Relatório executivo de migração e validação")
    rendered = rendered.replace("{{LOADING_TEXT}}", "Preparando relatório…")
    rendered = rendered.replace("{{LOGO_TEXT}}", "DataMigration")
    rendered = rendered.replace("{{LOGO_SUFFIX}}", "Factory")
    rendered = rendered.replace("{{NAV_LINKS}}", "<a href='#top'>Início</a>")
    rendered = rendered.replace("{{EYEBROW}}", "Migração — Cloudera para Microsoft Fabric")
    rendered = rendered.replace("{{HERO_TITLE}}", "Migração Cloudera → Microsoft Fabric")
    rendered = rendered.replace("{{HERO_SUBTITLE}}", f"{total_dbs} bancos • {total_tables} tabelas • {total_jobs} jobs")
    rendered = rendered.replace("{{HERO_BUTTONS}}", "<a class='btn btn-primary' href='#meter'>Ver Métricas</a>")
    rendered = rendered.replace("{{METER_TITLE}}", "Visão Geral")
    rendered = rendered.replace("{{METER_SUBTITLE}}", "Resumo rápido")
    # Build meter cells
    meter_cells = f"<div class='meter-cell'><div class='val ember'>{total_tables}</div><div class='lbl'>Tabelas</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_dbs}</div><div class='lbl'>Databases</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_jobs}</div><div class='lbl'>Jobs</div></div>"
    meter_cells += f"<div class='meter-cell'><div class='val'>{total_perms}</div><div class='lbl'>Permissões</div></div>"
    rendered = rendered.replace("{{METER_CELLS}}", meter_cells)

    rendered = rendered.replace("{{MAIN_SECTIONS}}", main_sections)
    rendered = rendered.replace("{{CTA_TITLE}}", "Próximos Passos")
    rendered = rendered.replace("{{CTA_SUBTITLE}}", "Revisar compatibilidade e executar piloto")
    rendered = rendered.replace("{{CTA_LINK}}", "#top")
    rendered = rendered.replace("{{CTA_BUTTON_TEXT}}", "Iniciar Piloto")
    rendered = rendered.replace("{{FOOTER_LEFT}}", "Relatório confidencial — Data Migration Factory")
    rendered = rendered.replace("{{FOOTER_RIGHT}}", "© 2026 Avanade")

    return rendered
    
    if compat_report.get("warnings"):
        html += """                <h3 style="color: #ff9800; margin-bottom: 10px;">🟡 Avisos</h3>
                <ul style="margin-left: 20px;">
"""
        for warning in compat_report.get("warnings", [])[:5]:
            html += f"                    <li>{warning}</li>\n"
        html += """                </ul>
"""
    
    html += f"""            </div>
            
            <!-- Próximos Passos -->
            <div class="section">
                <h2 class="section-title">🚀 Próximos Passos</h2>
                <div style="background: #f0f7ff; padding: 20px; border-radius: 8px; border-left: 4px solid #0078d4;">
                    <ol style="margin-left: 20px; line-height: 1.8;">
                        <li><strong>Revisar compatibilidade:</strong> Endereçar os {compat_report.get('warnings_count', 0)} avisos listados acima</li>
                        <li><strong>Provisionar ambiente:</strong> Criar workspace Fabric, lakehouses e pipelines</li>
                        <li><strong>Planejar estratégia de dados:</strong> Definir retenção, particionamento e compressão</li>
                        <li><strong>Configurar segurança:</strong> Mapear permissões Cloudera para Azure RBAC + Fabric</li>
                        <li><strong>Executar piloto:</strong> Migrar um banco de dados não-crítico como PoC</li>
                        <li><strong>Validar performance:</strong> Testar queries críticas em Fabric antes de cutover</li>
                    </ol>
                </div>
            </div>
            
            <!-- Métrica de Esforço -->
            <div class="section">
                <h2 class="section-title">📅 Estimativa de Esforço</h2>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;">
                    <div class="metric">
                        <div class="metric-label">Duração Estimada</div>
                        <div class="metric-value">{migration_plan.get('summary', {}).get('estimated_effort_weeks', 'N/A')} semanas</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Data Planejada de Go-Live</div>
                        <div class="metric-value">{migration_plan.get('summary', {}).get('go_live_date', 'N/A')}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Custo Estimado</div>
                        <div class="metric-value">USD ${sum(t.get('estimated_cost_usd', 0) for p in phases.values() for t in p.get('tasks', []) if 'estimated_cost_usd' in t)}</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p>🔐 Relatório confidencial | Criado pela Cutover</p>
            <p style="margin-top: 10px; font-size: 0.8em;">© 2026 | Avanade Global AI Hub</p>
        </div>
    </div>
</body>
</html>
"""
    
    return html


def main():
    """Gera e salva relatório HTML."""
    output_dir = Path("outputs/cloudera-fabric")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🎨 Gerando relatório HTML...\n")
    
    html = generate_html_report()
    
    output_file = output_dir / "migration_report.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✅ Relatório gerado com sucesso!")
    print(f"\n📄 Arquivo: {output_file}")
    print(f"📊 Abra em seu navegador para visualizar\n")


if __name__ == "__main__":
    main()
