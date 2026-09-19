#!/usr/bin/env python3
"""
Synthetic SAP-like data generator for Databricks testing.
Generates CSV files suitable for ingest into Databricks (VBAK, VBAP, MARA, BKPF, BSEG).
"""

import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def generate_mara(fake: Faker, n: int):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "MATNR": f"MAT{100000 + i}",
            "MAKTX": fake.company()[:60],
            "MTART": random.choice(["FERT", "HALB", "ROH"]),
            "MATKL": random.choice(["001", "002", "003", "010"]),
            "MEINS": random.choice(["PC", "KG", "M"]),
            "LABOR": round(random.uniform(0.5, 50.0), 2),
            "CREATED_AT": fake.date_between(start_date="-3y", end_date="today").isoformat(),
        })
    return rows


def generate_vbak_vbap(fake: Faker, orders: int, avg_items: int):
    vbak_rows = []
    vbap_rows = []
    for i in range(1, orders + 1):
        order_id = f"ORD{1000000 + i}"
        sold_to = fake.company()[:50]
        order_date = fake.date_between(start_date="-2y", end_date="today")
        total_amount = 0.0
        items = max(1, int(random.gauss(avg_items, avg_items * 0.3)))

        for it in range(1, items + 1):
            material = f"MAT{100000 + random.randint(1, max(1, orders//2))}"
            qty = max(1, int(random.expovariate(1/3)))
            price = round(random.uniform(5.0, 1000.0), 2)
            line_amount = round(qty * price, 2)
            total_amount += line_amount
            vbap_rows.append({
                "VBELN": order_id,
                "POSNR": f"{it:04d}",
                "MATNR": material,
                "ARKTX": fake.word()[:40],
                "KWMENG": qty,
                "NETPR": price,
                "WAERK": random.choice(["USD", "EUR", "BRL"]),
            })

        vbak_rows.append({
            "VBELN": order_id,
            "AUART": random.choice(["OR", "ZOR"]),
            "VKORG": random.choice(["1000", "2000"]),
            "VTWEG": random.choice(["10", "20"]),
            "SPART": random.choice(["00", "01"]),
            "KUNNR": f"CUST{1000 + (i%500)}",
            "NAME": sold_to,
            "AUDAT": order_date.isoformat(),
            "NETWR": round(total_amount, 2),
            "WAERK": random.choice(["USD", "EUR", "BRL"]),
        })

    return vbak_rows, vbap_rows


def generate_bkpf_bseg(fake: Faker, docs: int, avg_lines: int):
    bkpf = []
    bseg = []
    for i in range(1, docs + 1):
        docnum = f"DOC{500000 + i}"
        doc_date = fake.date_between(start_date="-2y", end_date="today")
        lines = max(1, int(random.gauss(avg_lines, avg_lines * 0.4)))
        total = 0.0
        for ln in range(1, lines + 1):
            amt = round(random.uniform(-1000, 5000), 2)
            total += amt
            bseg.append({
                "BELNR": docnum,
                "BUZEI": f"{ln:02d}",
                "HKONT": random.choice(["100000", "200000", "300000"]),
                "WRBTR": amt,
                "WRBTR_CUR": round(amt, 2),
                "BSCHL": random.choice(["40", "50"]),
            })

        bkpf.append({
            "BELNR": docnum,
            "BLART": random.choice(["SA", "KR", "DZ"]),
            "BUKRS": random.choice(["1000", "2000"]),
            "BLDAT": doc_date.isoformat(),
            "BUDAT": (doc_date + timedelta(days=random.randint(0,3))).isoformat(),
            "WAERS": random.choice(["USD", "EUR", "BRL"]),
            "WRBTR": round(total, 2),
        })

    return bkpf, bseg


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic SAP-like CSV datasets for Databricks testing")
    parser.add_argument("--out", default="outputs/sap-cloudera-legacy/synthetic_data", help="output directory")
    parser.add_argument("--orders", type=int, default=2000, help="number of sales orders to generate")
    parser.add_argument("--avg-items", type=int, default=3, help="average items per order")
    parser.add_argument("--materials", type=int, default=500, help="number of material master rows")
    parser.add_argument("--docs", type=int, default=500, help="number of financial documents to generate")
    args = parser.parse_args()

    fake = Faker()
    Faker.seed(12345)
    random.seed(42)

    out_dir = Path(args.out)

    # Generate MARA (material master)
    mara_rows = generate_mara(fake, args.materials)
    mara_fields = ["MATNR", "MAKTX", "MTART", "MATKL", "MEINS", "LABOR", "CREATED_AT"]
    mara_file = out_dir / "sap_mara.csv"
    write_csv(mara_file, mara_fields, mara_rows)

    # Generate sales orders (VBAK) and items (VBAP)
    vbak_rows, vbap_rows = generate_vbak_vbap(fake, args.orders, args.avg_items)
    vbak_fields = ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR", "NAME", "AUDAT", "NETWR", "WAERK"]
    vbap_fields = ["VBELN", "POSNR", "MATNR", "ARKTX", "KWMENG", "NETPR", "WAERK"]
    vbak_file = out_dir / "sap_vbak.csv"
    vbap_file = out_dir / "sap_vbap.csv"
    write_csv(vbak_file, vbak_fields, vbak_rows)
    write_csv(vbap_file, vbap_fields, vbap_rows)

    # Generate financial docs (BKPF/BSEG)
    bkpf_rows, bseg_rows = generate_bkpf_bseg(fake, args.docs, avg_lines=3)
    bkpf_fields = ["BELNR", "BLART", "BUKRS", "BLDAT", "BUDAT", "WAERS", "WRBTR"]
    bseg_fields = ["BELNR", "BUZEI", "HKONT", "WRBTR", "WRBTR_CUR", "BSCHL"]
    bkpf_file = out_dir / "sap_bkpf.csv"
    bseg_file = out_dir / "sap_bseg.csv"
    write_csv(bkpf_file, bkpf_fields, bkpf_rows)
    write_csv(bseg_file, bseg_fields, bseg_rows)

    # Create a simple manifest
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "files": {
            "mara": str(mara_file),
            "vbak": str(vbak_file),
            "vbap": str(vbap_file),
            "bkpf": str(bkpf_file),
            "bseg": str(bseg_file),
        },
        "counts": {
            "mara": len(mara_rows),
            "vbak": len(vbak_rows),
            "vbap": len(vbap_rows),
            "bkpf": len(bkpf_rows),
            "bseg": len(bseg_rows),
        }
    }

    manifest_file = out_dir / "sap_manifest.json"
    with manifest_file.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("✅ SAP synthetic data generated:")
    for k, v in manifest["files"].items():
        print(f" - {k}: {v} ({manifest['counts'][k]} rows)")
    print(f"Manifest: {manifest_file}")


if __name__ == "__main__":
    main()
