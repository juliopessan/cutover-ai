#!/usr/bin/env python3
"""
Convert SAP CSVs to Parquet, package them, and generate an HTML report using templates/dashboard.template.html
"""

import json
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd


TEMPLATE = Path("templates/dashboard.template.html")


def load_manifest(manifest_path: Path):
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def csvs_to_parquet(manifest: dict, out_dir: Path) -> dict:
    parquet_dir = out_dir / "parquet"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    parquet_files = {}
    for key, csv_path in manifest["files"].items():
        p = Path(csv_path)
        if not p.exists():
            # try relative to out_dir/csv
            p = out_dir / "csv" / p.name
        df = pd.read_csv(p)
        parquet_path = parquet_dir / (p.stem + ".parquet")
        df.to_parquet(parquet_path, index=False)
        counts[key] = len(df)
        parquet_files[key] = str(parquet_path)
    return {"counts": counts, "parquet_files": parquet_files, "parquet_dir": str(parquet_dir)}


def make_package(parquet_info: dict, out_dir: Path, manifest_path: Path):
    zip_path = out_dir / "sap_parquet_package.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # add parquet files
        for k, p in parquet_info["parquet_files"].items():
            z.write(p, arcname=Path(p).name)
        # include manifest
        z.write(manifest_path, arcname=manifest_path.name)
    return str(zip_path)


def render_report(manifest: dict, parquet_info: dict, out_dir: Path):
    tpl = TEMPLATE.read_text(encoding="utf-8")
    page_title = "SAP Synthetic Data — Package Report"
    page_desc = "Resumo dos arquivos sintéticos SAP e pacote Parquet gerado"

    # Build meter cells
    total_files = len(manifest["files"])
    total_rows = sum(manifest["counts"].values())
    total_parquet = len(parquet_info["parquet_files"])

    meter_cells = []
    def cell(val, lbl, ember=False):
        cls = "val ember" if ember else "val"
        return f'<div class="meter-cell"><div class="{cls}">{val}</div><div class="lbl">{lbl}</div></div>'

    meter_cells.append(cell(total_files, "CSV Files"))
    meter_cells.append(cell(f"{total_rows:,}", "Total Rows", ember=True))
    meter_cells.append(cell(total_parquet, "Parquet Files"))
    meter_cells.append(cell(datetime.now().date().isoformat(), "Generated"))

    # Build main sections: simple table of files
    rows_html = []
    for k, csv_path in manifest["files"].items():
        rows_html.append("<tr>")
        rows_html.append(f"<td class=\"mono\">{k}</td>")
        rows_html.append(f"<td>{Path(csv_path).name}</td>")
        rows_html.append(f"<td class=\"mono\">{manifest['counts'].get(k, '?')}</td>")
        parquet_path = parquet_info["parquet_files"].get(k)
        if parquet_path:
            rows_html.append(f"<td><a href=\"{Path(parquet_path).name}\">{Path(parquet_path).name}</a></td>")
        else:
            rows_html.append("<td>-</td>")
        rows_html.append("</tr>")

    main_sections = """
<section>
  <div class="sec-label">Dataset</div>
  <h2>SAP Synthetic Dataset</h2>
  <p class="sec-intro">Arquivos gerados e empacotados para ingestão no Databricks.</p>

  <table class="data-table">
    <thead>
      <tr><th>Key</th><th>File</th><th>Rows</th><th>Parquet</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</section>
""".format(rows='\n'.join(rows_html))

    html = tpl.replace("{{PAGE_TITLE}}", page_title)
    html = html.replace("{{PAGE_DESCRIPTION}}", page_desc)
    html = html.replace("{{LOADING_TEXT}}", "Preparando relatório...")
    html = html.replace("{{LOGO_TEXT}}", "DataMig")
    html = html.replace("{{LOGO_SUFFIX}}", "SAP")
    html = html.replace("{{NAV_LINKS}}", "<a href='#top'>Top</a>")
    html = html.replace("{{EYEBROW}}", "Synthetic SAP")
    html = html.replace("{{HERO_TITLE}}", "SAP Synthetic Data Package")
    html = html.replace("{{HERO_SUBTITLE}}", "Parquet package pronto para upload no Databricks / DBFS")
    html = html.replace("{{HERO_BUTTONS}}", "<a class='btn btn-primary' href='#meter'>Resumo</a>")
    html = html.replace("{{METER_TITLE}}", "Package Summary")
    html = html.replace("{{METER_SUBTITLE}}", "SAP Synthetic")
    html = html.replace("{{METER_CELLS}}", '\n'.join(meter_cells))
    html = html.replace("{{MAIN_SECTIONS}}", main_sections)
    html = html.replace("{{CTA_TITLE}}", "Pronto para upload")
    html = html.replace("{{CTA_SUBTITLE}}", "Baixe o pacote e carregue no seu DBFS/Storage para ingestão no Databricks.")
    html = html.replace("{{CTA_LINK}}", "sap_parquet_package.zip")
    html = html.replace("{{CTA_BUTTON_TEXT}}", "Baixar pacote")
    html = html.replace("{{FOOTER_LEFT}}", "Generated by Data Migration Multi-Agent")
    html = html.replace("{{FOOTER_RIGHT}}", datetime.now().isoformat())

    report_dir = out_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_file = report_dir / "sap_report.html"
    out_file.write_text(html, encoding="utf-8")
    return str(out_file)


def main():
    artifacts_dir = Path("outputs/sap-cloudera-legacy/synthetic_data")
    manifest_path = artifacts_dir / "sap_manifest.json"
    manifest = load_manifest(manifest_path)

    # Create run-specific output structure
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = artifacts_dir / "runs" / run_id
    csv_dir = run_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    # Copy CSVs into run dir and build a local manifest pointing to them
    local_manifest = {"generated_at": manifest.get("generated_at", datetime.now().isoformat()), "files": {}, "counts": manifest.get("counts", {})}
    for k, p in manifest["files"].items():
        src = Path(p)
        if not src.exists():
            # try artifacts root
            src = artifacts_dir / Path(p).name
        dst = csv_dir / src.name
        shutil.copy2(src, dst)
        local_manifest["files"][k] = str(dst)

    # Save local manifest copy
    manifest_out_dir = run_dir / "manifest"
    manifest_out_dir.mkdir(parents=True, exist_ok=True)
    local_manifest_path = manifest_out_dir / "sap_manifest.json"
    local_manifest_path.write_text(json.dumps(local_manifest, indent=2), encoding="utf-8")

    print(f"Converting CSVs to Parquet into run folder {run_dir}...")
    parquet_info = csvs_to_parquet(local_manifest, run_dir)

    print("Packaging parquet files...")
    package_path = make_package(parquet_info, run_dir, local_manifest_path)

    print("Rendering HTML report...")
    report_path = render_report(local_manifest, parquet_info, run_dir)

    print("Done.")
    print(f"Run dir: {run_dir}")
    print(f"Parquet dir: {parquet_info['parquet_dir']}")
    print(f"Package: {package_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()


