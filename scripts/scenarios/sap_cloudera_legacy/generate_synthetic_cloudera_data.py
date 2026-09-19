#!/usr/bin/env python3
"""
Synthetic Cloudera data generator for Fabric migration testing.
Generates realistic Hive/Cloudera metadata and sample datasets.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from dataclasses import dataclass, asdict
import random

# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ColumnDefinition:
    """Hive column metadata"""
    name: str
    type: str
    comment: str = ""
    nullable: bool = True

@dataclass
class TableMetadata:
    """Hive table metadata (Cloudera source)"""
    database: str
    table_name: str
    location: str
    input_format: str
    output_format: str
    serde: str
    columns: list[ColumnDefinition]
    partitions: list[str] = None
    table_type: str = "MANAGED_TABLE"
    created_at: str = None
    owner: str = "cloudera"
    storage_size_gb: float = 0.0
    row_count: int = 0
    
    def __post_init__(self):
        if self.partitions is None:
            self.partitions = []
        if self.created_at is None:
            self.created_at = (datetime.now() - timedelta(days=random.randint(30, 365))).isoformat()

@dataclass
class HiveDatabase:
    """Hive database container"""
    name: str
    location: str
    description: str = ""
    tables: list[TableMetadata] = None
    created_at: str = None
    
    def __post_init__(self):
        if self.tables is None:
            self.tables = []
        if self.created_at is None:
            self.created_at = (datetime.now() - timedelta(days=random.randint(365, 1095))).isoformat()

@dataclass
class ClouderaCatalog:
    """Cloudera metastore snapshot"""
    cluster_name: str
    hive_version: str
    databases: list[HiveDatabase]
    extraction_timestamp: str = None
    
    def __post_init__(self):
        if self.extraction_timestamp is None:
            self.extraction_timestamp = datetime.now().isoformat()


# ============================================================================
# Synthetic Data Generators
# ============================================================================

def generate_column(name: str, col_type: str = None) -> ColumnDefinition:
    """Generate a column definition"""
    types = ["bigint", "string", "double", "int", "timestamp", "boolean", "decimal(18,2)"]
    return ColumnDefinition(
        name=name,
        type=col_type or random.choice(types),
        comment=f"Column: {name}",
        nullable=random.choice([True, False])
    )

def generate_customers_table() -> TableMetadata:
    """Generate synthetic customers table"""
    return TableMetadata(
        database="sales",
        table_name="customers",
        location="/data/hive/warehouse/sales.db/customers",
        input_format="org.apache.hadoop.mapred.TextInputFormat",
        output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        serde="org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
        columns=[
            generate_column("customer_id", "bigint"),
            generate_column("first_name", "string"),
            generate_column("last_name", "string"),
            generate_column("email", "string"),
            generate_column("country", "string"),
            generate_column("created_date", "date"),
            generate_column("is_active", "boolean"),
        ],
        partitions=["year", "month"],
        row_count=2_500_000,
        storage_size_gb=15.3,
        owner="sales_team"
    )

def generate_orders_table() -> TableMetadata:
    """Generate synthetic orders table"""
    return TableMetadata(
        database="sales",
        table_name="orders",
        location="/data/hive/warehouse/sales.db/orders",
        input_format="org.apache.hadoop.mapred.TextInputFormat",
        output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        serde="org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
        columns=[
            generate_column("order_id", "bigint"),
            generate_column("customer_id", "bigint"),
            generate_column("order_date", "timestamp"),
            generate_column("total_amount", "decimal(18,2)"),
            generate_column("currency", "string"),
            generate_column("status", "string"),
            generate_column("shipping_address", "string"),
            generate_column("payment_method", "string"),
        ],
        partitions=["year", "quarter"],
        row_count=15_000_000,
        storage_size_gb=85.7,
        owner="sales_team"
    )

def generate_products_table() -> TableMetadata:
    """Generate synthetic products table"""
    return TableMetadata(
        database="catalog",
        table_name="products",
        location="/data/hive/warehouse/catalog.db/products",
        input_format="org.apache.hadoop.mapred.TextInputFormat",
        output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        serde="org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
        columns=[
            generate_column("product_id", "bigint"),
            generate_column("product_name", "string"),
            generate_column("category", "string"),
            generate_column("subcategory", "string"),
            generate_column("unit_price", "decimal(18,2)"),
            generate_column("currency", "string"),
            generate_column("in_stock", "int"),
            generate_column("supplier_id", "bigint"),
            generate_column("last_updated", "timestamp"),
        ],
        row_count=500_000,
        storage_size_gb=3.2,
        owner="product_team"
    )

def generate_analytics_table() -> TableMetadata:
    """Generate synthetic analytics events table"""
    return TableMetadata(
        database="analytics",
        table_name="events",
        location="/data/hive/warehouse/analytics.db/events",
        input_format="org.apache.hadoop.mapred.TextInputFormat",
        output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        serde="org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
        columns=[
            generate_column("event_id", "string"),
            generate_column("user_id", "bigint"),
            generate_column("event_type", "string"),
            generate_column("event_timestamp", "timestamp"),
            generate_column("session_id", "string"),
            generate_column("page_url", "string"),
            generate_column("device_type", "string"),
            generate_column("event_properties", "string"),  # JSON as string
        ],
        partitions=["date", "hour"],
        row_count=500_000_000,
        storage_size_gb=250.5,
        owner="analytics_team"
    )

def generate_cloudera_catalog() -> ClouderaCatalog:
    """Generate complete Cloudera metastore snapshot"""
    sales_db = HiveDatabase(
        name="sales",
        location="/data/hive/warehouse/sales.db",
        description="Sales transactions and customer data",
        tables=[
            generate_customers_table(),
            generate_orders_table(),
        ]
    )
    
    catalog_db = HiveDatabase(
        name="catalog",
        location="/data/hive/warehouse/catalog.db",
        description="Product catalog and inventory",
        tables=[
            generate_products_table(),
        ]
    )
    
    analytics_db = HiveDatabase(
        name="analytics",
        location="/data/hive/warehouse/analytics.db",
        description="Analytics events and user telemetry",
        tables=[
            generate_analytics_table(),
        ]
    )
    
    return ClouderaCatalog(
        cluster_name="prod-cloudera-cluster",
        hive_version="3.1.3",
        databases=[sales_db, catalog_db, analytics_db]
    )


# ============================================================================
# Output Helpers
# ============================================================================

def catalog_to_dict(catalog: ClouderaCatalog) -> dict[str, Any]:
    """Convert catalog to dict for JSON serialization"""
    result = {
        "cluster_name": catalog.cluster_name,
        "hive_version": catalog.hive_version,
        "extraction_timestamp": catalog.extraction_timestamp,
        "databases": []
    }
    
    for db in catalog.databases:
        db_dict = {
            "name": db.name,
            "location": db.location,
            "description": db.description,
            "created_at": db.created_at,
            "tables": []
        }
        
        for table in db.tables:
            table_dict = {
                "database": table.database,
                "table_name": table.table_name,
                "table_type": table.table_type,
                "location": table.location,
                "input_format": table.input_format,
                "output_format": table.output_format,
                "serde": table.serde,
                "owner": table.owner,
                "created_at": table.created_at,
                "row_count": table.row_count,
                "storage_size_gb": table.storage_size_gb,
                "partitions": table.partitions,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.type,
                        "comment": col.comment,
                        "nullable": col.nullable
                    }
                    for col in table.columns
                ]
            }
            db_dict["tables"].append(table_dict)
        
        result["databases"].append(db_dict)
    
    return result


# ============================================================================
# Main
# ============================================================================

def main():
    print("🚀 Generating synthetic Cloudera metastore...")
    
    # Generate catalog
    catalog = generate_cloudera_catalog()
    
    # Convert to dict
    catalog_dict = catalog_to_dict(catalog)
    
    # Create output directory
    output_dir = Path("outputs/sap-cloudera-legacy/synthetic_data")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    output_file = output_dir / "cloudera_metastore.json"
    with open(output_file, "w") as f:
        json.dump(catalog_dict, f, indent=2)
    
    print(f"✅ Metastore snapshot saved: {output_file}")
    
    # Print summary
    total_tables = sum(len(db.tables) for db in catalog.databases)
    total_rows = sum(sum(t.row_count for t in db.tables) for db in catalog.databases)
    total_size_gb = sum(sum(t.storage_size_gb for t in db.tables) for db in catalog.databases)
    
    print(f"\n📊 Cloudera Catalog Summary:")
    print(f"   Cluster: {catalog.cluster_name}")
    print(f"   Databases: {len(catalog.databases)}")
    print(f"   Tables: {total_tables}")
    print(f"   Total Rows: {total_rows:,}")
    print(f"   Total Size: {total_size_gb:.1f} GB")
    print(f"\n📋 Database Details:")
    
    for db in catalog.databases:
        db_rows = sum(t.row_count for t in db.tables)
        db_size = sum(t.storage_size_gb for t in db.tables)
        print(f"   • {db.name}")
        print(f"     - Tables: {len(db.tables)}")
        print(f"     - Rows: {db_rows:,}")
        print(f"     - Size: {db_size:.1f} GB")
        for table in db.tables:
            print(f"       → {table.table_name}: {table.row_count:,} rows ({table.storage_size_gb:.1f} GB)")


if __name__ == "__main__":
    main()
