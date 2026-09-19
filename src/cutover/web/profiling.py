"""Deterministic dataset profiling. Every figure is computed from the uploaded bytes."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Characters that Delta Lake (Databricks and Fabric Lakehouse) rejects in column names.
INVALID_NAME_CHARS = re.compile(r"[ ,;{}()\n\t=]")
MOSTLY_EMPTY_RATIO = 0.5
MAX_LISTED = 8

_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?")
_BOOL = {"true", "false"}


class ProfileError(ValueError):
    """The file cannot be profiled (not CSV, wrong encoding, empty)."""


@dataclass
class Flag:
    kind: str
    title: str
    items: list[str]
    action: str


@dataclass
class DatasetProfile:
    sha256: str
    rows: int
    columns: list[dict[str, Any]]
    duplicate_rows: int
    empty_cells: int
    total_cells: int
    flags: list[Flag] = field(default_factory=list)

    @property
    def filled_cells(self) -> int:
        return self.total_cells - self.empty_cells

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify(value: str) -> str:
    if _INT.match(value):
        return "integer"
    if _FLOAT.match(value):
        return "decimal"
    if value.lower() in _BOOL:
        return "boolean"
    if _DATE.match(value):
        return "date"
    return "text"


def _merge(types: set[str]) -> str:
    if not types:
        return "empty"
    if len(types) == 1:
        return next(iter(types))
    if types == {"integer", "decimal"}:
        return "decimal"
    return "mixed"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_csv(path: Path) -> DatasetProfile:
    raw = path.read_bytes()
    if not raw.strip():
        raise ProfileError("O arquivo está vazio.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProfileError("O arquivo não está em UTF-8. Exporte novamente em UTF-8.") from exc
    try:
        dialect: Any = csv.Sniffer().sniff(text[:16384], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    headers = next(reader, [])
    if not headers or not any(h.strip() for h in headers):
        raise ProfileError("Não foi possível ler o cabeçalho do CSV.")

    width = len(headers)
    types: list[set[str]] = [set() for _ in headers]
    nulls = [0] * width
    seen: set[bytes] = set()
    duplicates = rows = 0
    malformed: list[str] = []

    for line_number, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != width:
            malformed.append(str(line_number))
            continue
        rows += 1
        key = hashlib.blake2b("\x1f".join(row).encode(), digest_size=16).digest()
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
        for index, value in enumerate(row):
            value = value.strip()
            if value == "":
                nulls[index] += 1
            else:
                types[index].add(_classify(value))

    columns = [
        {
            "name": name,
            "type": _merge(types[i]),
            "nulls": nulls[i],
            "null_ratio": (nulls[i] / rows) if rows else 0.0,
        }
        for i, name in enumerate(headers)
    ]
    profile = DatasetProfile(
        sha256=sha256_file(path),
        rows=rows,
        columns=columns,
        duplicate_rows=duplicates,
        empty_cells=sum(nulls),
        total_cells=rows * width,
    )
    profile.flags = _flags(profile, malformed)
    return profile


def _listed(items: list[str]) -> list[str]:
    if len(items) <= MAX_LISTED:
        return items
    return [*items[:MAX_LISTED], f"… e mais {len(items) - MAX_LISTED}"]


def _flags(profile: DatasetProfile, malformed: list[str]) -> list[Flag]:
    """Flags render only when something is wrong; a clean dataset shows none."""
    flags: list[Flag] = []
    names = [c["name"] for c in profile.columns]

    bad = [n for n in names if INVALID_NAME_CHARS.search(n) or not n.strip()]
    if bad:
        flags.append(Flag(
            "column_names", "Nomes de coluna incompatíveis com Delta",
            _listed([repr(n) for n in bad]),
            "Renomeie antes de migrar para Fabric ou Databricks; o plano de migração depende destes nomes.",
        ))
    lowered: dict[str, list[str]] = {}
    for name in names:
        lowered.setdefault(name.strip().lower(), []).append(name)
    clashes = [", ".join(group) for group in lowered.values() if len(group) > 1]
    if clashes:
        flags.append(Flag(
            "duplicate_columns", "Colunas duplicadas (sem diferenciar maiúsculas)",
            _listed(clashes), "Delta não diferencia maiúsculas: unifique ou renomeie.",
        ))
    if malformed:
        flags.append(Flag(
            "malformed_rows", "Linhas com número de campos diferente do cabeçalho",
            [f"linha {n}" for n in _listed(malformed)],
            "Estas linhas foram excluídas dos números acima; trate as métricas como incompletas.",
        ))
    mixed = [c["name"] for c in profile.columns if c["type"] == "mixed"]
    if mixed:
        flags.append(Flag(
            "mixed_types", "Colunas com tipos misturados", _listed(mixed),
            "Defina o tipo de destino manualmente; o tipo inferido é ambíguo.",
        ))
    sparse = [
        f"{c['name']} ({c['null_ratio']:.0%} vazia)"
        for c in profile.columns
        if profile.rows and c["null_ratio"] > MOSTLY_EMPTY_RATIO
    ]
    if sparse:
        flags.append(Flag(
            "mostly_empty", "Colunas majoritariamente vazias", _listed(sparse),
            "Confirme se devem migrar; valide a regra de negócio com o dono do dado.",
        ))
    if profile.duplicate_rows:
        flags.append(Flag(
            "duplicate_rows", "Linhas duplicadas",
            [f"{profile.duplicate_rows} linhas idênticas a uma anterior"],
            "A reconciliação de contagem falhará se a origem e o destino tratarem duplicatas de forma diferente.",
        ))
    return flags
