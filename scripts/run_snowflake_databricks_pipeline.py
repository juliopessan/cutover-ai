#!/usr/bin/env python3
"""
Executor master: Gera dados sintéticos Snowflake, simula migração para Databricks e cria relatório.
"""

import subprocess
import sys
from pathlib import Path


def run_script(script_name: str, description: str) -> bool:
    """Executa um script Python e reporta resultado."""
    script_path = Path(__file__).parent / script_name

    print(f"\n{'='*70}")
    print(f"▶️  {description}")
    print(f"{'='*70}\n")

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=Path(__file__).parent.parent,
            capture_output=False,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print(f"✅ {description} — SUCESSO\n")
            return True
        else:
            print(f"❌ {description} — FALHA (código {result.returncode})\n")
            return False
    except Exception as e:
        print(f"❌ Erro ao executar {script_name}: {e}\n")
        return False


def main():
    """Executa pipeline completo."""

    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║        MIGRAÇÃO SNOWFLAKE → DATABRICKS - PIPELINE EXECUTIVO                ║
║                    Cutover                      ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

    scripts = [
        ("generate_snowflake_synthetic_data.py", "1️⃣  GERAR DADOS SINTÉTICOS SNOWFLAKE"),
        ("simulate_snowflake_databricks_migration.py", "2️⃣  SIMULAR PLANO DE MIGRAÇÃO"),
        ("generate_snowflake_migration_report.py", "3️⃣  GERAR RELATÓRIO HTML"),
    ]

    results = []
    for script, desc in scripts:
        success = run_script(script, desc)
        results.append((desc, success))

    print("\n" + "="*70)
    print("📋 RESUMO FINAL")
    print("="*70 + "\n")

    for desc, success in results:
        status = "✅ OK" if success else "❌ FALHA"
        print(f"  {status} — {desc}")

    all_success = all(success for _, success in results)

    print("\n" + "="*70)
    if all_success:
        print("🎉 PIPELINE COMPLETO COM SUCESSO!")
        print("\n📊 Artefatos gerados:")
        print("   • outputs/snowflake-databricks/synthetic_data/     — Dados sintéticos")
        print("   • outputs/snowflake-databricks/migration_plan/     — Plano de migração")
        print("   • outputs/snowflake-databricks/migration_report.html — Relatório executivo")
        print("\n🌐 Abra migration_report.html em seu navegador para visualizar!")
    else:
        print("⚠️  PIPELINE INCOMPLETO — Verifique os erros acima")
    print("="*70 + "\n")

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
