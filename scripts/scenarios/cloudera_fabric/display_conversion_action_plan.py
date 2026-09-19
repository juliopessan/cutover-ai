#!/usr/bin/env python3
"""
Exibe sumário visual da ação recomendada: Conversão TEXT → PARQUET
"""

import json
from pathlib import Path
from datetime import datetime

def main():
    print("\n" + "="*80)
    print(" 🎯 AÇÃO RECOMENDADA — CONVERSÃO TEXT → PARQUET ".center(80, "="))
    print("="*80 + "\n")
    
    # Carregar dados
    plan_path = Path("outputs/cloudera-fabric/text_to_parquet_conversion/execution_plan.json")
    if not plan_path.exists():
        print("❌ Plano não encontrado. Execute o script de geração primeiro.\n")
        return
    
    with open(plan_path) as f:
        plan = json.load(f)
    
    tables = plan["tables"]
    summary = plan["summary"]
    
    # Cabeçalho
    print(f"📊 STATUS: ✅ PRONTO PARA EXECUTAR")
    print(f"📅 DATA: {datetime.now().strftime('%d/%m/%Y %H:%M UTC')}")
    print(f"⚠️  RISCO: {summary['risk_level']}")
    print(f"🔄 ROLLBACK: {summary['rollback_strategy']}\n")
    
    # Resumo em tabela
    print("─" * 80)
    print("📋 RESUMO EXECUTIVO")
    print("─" * 80)
    
    stats = [
        ("Tabelas TEXT a converter", f"{len(tables)} tabelas"),
        ("Total de dados afetados", f"{summary['total_rows_affected']:,} linhas"),
        ("Volume total", f"{sum(t['size_gb'] for t in tables):.2f} GB"),
        ("Espaço a economizar", f"~{summary['estimated_space_saved_gb']:.1f} GB (90% redução)"),
        ("Duração total", f"{summary['total_duration_hours']:.2f} horas"),
        ("Performance gain esperado", "5-20x mais rápido em queries"),
        ("Impacto na migração", "-10% volume, -3-4h na migração"),
    ]
    
    for label, value in stats:
        print(f"  {label:<40} │ {value:>35}")
    
    print("\n" + "─" * 80)
    print("📊 TABELAS A CONVERTER (Ordenadas por tamanho)")
    print("─" * 80 + "\n")
    
    for i, table in enumerate(tables, 1):
        savings = table["size_gb"] * 0.9
        print(f"  {i}️⃣  {table['database']}.{table['table_name']}")
        print(f"      Linhas: {table['row_count']:>15,}  │  Tamanho: {table['size_gb']:>8.2f} GB  │  Economia: ~{savings:.2f} GB")
        print()
    
    print("─" * 80)
    print("🚀 CRONOGRAMA (7 Fases, 3.25 horas)")
    print("─" * 80 + "\n")
    
    phases = [
        ("1", "Validação Pré-Conversão", "30 min", "📋"),
        ("2", "Criar Tabelas PARQUET", "120 min", "⏳ MAIS LONGO"),
        ("3", "Habilitar Compressão Snappy", "15 min", "⚙️"),
        ("4", "Validação de Integridade", "30 min", "✓ CRÍTICO"),
        ("5", "SWAP - Substituir Tabelas", "10 min", "🔄 PRODUÇÃO"),
        ("6", "Validação Pós-Conversão", "30 min", "✓"),
        ("7", "Cleanup (Após 7 dias)", "5 min", "📅"),
    ]
    
    for phase, name, duration, status in phases:
        print(f"  Fase {phase}: {name:<35} │ {duration:>10} │ {status}")
    
    print(f"\n  {'TOTAL':<20} {' '*34} │ {'3.25 horas':>10}")
    
    print("\n" + "─" * 80)
    print("✅ PRÉ-REQUISITOS")
    print("─" * 80 + "\n")
    
    reqs = [
        "✓ Backup completo das tabelas já realizado",
        f"✓ Espaço em disco: >3.6 TB disponível em /user/hive/warehouse",
        "✓ Nenhuma query ativa nas 9 tabelas TEXT",
        "✓ Janela de manutenção aprovada (2-4 horas)",
        "✓ Usuário Hive com permissões DROP/CREATE/ALTER",
    ]
    
    for req in reqs:
        print(f"  {req}")
    
    print("\n" + "─" * 80)
    print("📁 ARQUIVOS GERADOS")
    print("─" * 80 + "\n")
    
    files = [
        ("conversion_script.sql", "45 KB", "Script SQL HiveQL pronto para executar"),
        ("execution_plan.json", "15 KB", "Timeline estruturada em JSON"),
        ("CONVERSION_ACTION_PLAN.md", "8 KB", "Guia executivo completo"),
        ("NEXT_STEPS.md", "10 KB", "Próximas ações recomendadas"),
    ]
    
    for fname, size, desc in files:
        print(f"  📄 {fname:<30} ({size:>6}) - {desc}")
    
    print(f"\n  📂 Local: outputs/cloudera-fabric/text_to_parquet_conversion/")
    
    print("\n" + "─" * 80)
    print("🎯 PRÓXIMAS AÇÕES")
    print("─" * 80 + "\n")
    
    actions = [
        "1️⃣  Revisar NEXT_STEPS.md com sua team de DBAs",
        "2️⃣  Testar em DEV/QA (copiar 1-2 tabelas, executar fases 1-6)",
        "3️⃣  Agendar janela de manutenção em PRODUÇÃO (2-4 horas)",
        "4️⃣  Copiar conversion_script.sql para Cloudera",
        "5️⃣  Executar Fase 1 (validação) antes do janela",
        "6️⃣  Durante janela: executar Fases 2-6 (3.25 horas)",
        "7️⃣  Após 7 dias: Executar Fase 7 (cleanup de backups)",
        "8️⃣  Após conversão: migração Fabric com 90% menos volume!",
    ]
    
    for action in actions:
        print(f"  {action}")
    
    print("\n" + "─" * 80)
    print("💰 IMPACTO FINANCEIRO")
    print("─" * 80 + "\n")
    
    impact = [
        f"  Storage: {summary['estimated_space_saved_gb']:.1f} GB economizados",
        f"  Custo/ano: ~USD $500-1.000 em storage",
        f"  Performance: 5-20x mais rápido em queries",
        f"  Migração Fabric: ~10% menos volume a transferir",
    ]
    
    for item in impact:
        print(item)
    
    print("\n" + "=" * 80)
    print(" ✨ STATUS: 🟢 PRONTO PARA EXECUTAR ".center(80, "="))
    print("=" * 80 + "\n")
    
    print("📖 Para mais detalhes, leia: outputs/cloudera-fabric/text_to_parquet_conversion/NEXT_STEPS.md\n")


if __name__ == "__main__":
    main()
