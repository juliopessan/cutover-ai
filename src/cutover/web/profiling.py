"""Deterministic dataset profiling. Every figure is computed from the uploaded bytes."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation
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


DISTINCT_CAP = 100_000
PROFILE_VERSION = 2
# Column-name hints for personal data. A heuristic on names only: it says nothing about the values.
PRIVACY_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nome de pessoa", re.compile(r"(^|_|\b)(nome|name|sobrenome|surname)(_|\b|$)", re.I)),
    ("e-mail", re.compile(r"e-?mail", re.I)),
    ("documento (CPF, CNPJ, RG)", re.compile(r"(^|_|\b)(cpf|cnpj|rg|passaporte|passport)(_|\b|$)", re.I)),
    ("telefone", re.compile(r"telefone|phone|celular|fone|whatsapp", re.I)),
    ("endereço ou CEP", re.compile(r"endere[cç]o|address|(^|_|\b)(cep|zip|postal)(_|\b|$)", re.I)),
    ("data de nascimento", re.compile(r"nascimento|birth|(^|_|\b)dob(_|\b|$)", re.I)),
    ("credencial", re.compile(r"senha|password|token|secret", re.I)),
    ("remuneração", re.compile(r"sal[aá]rio|salary|remunera", re.I)),
)


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
    delimiter: str = ","
    rows_discarded: int = 0
    privacy_hints: list[dict[str, str]] = field(default_factory=list)
    profile_version: int = PROFILE_VERSION

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


class _Stats:
    """Per-column aggregates: distinct values (capped), numeric or date range, text length, decimal shape."""

    __slots__ = ("fingerprint", "distinct", "capped", "low", "high", "date_low", "date_high", "max_len", "max_scale", "max_int_digits")

    def __init__(self) -> None:
        self.fingerprint = hashlib.blake2b(digest_size=16)
        self.distinct: set[str] = set()
        self.capped = False
        self.low: Decimal | None = None
        self.high: Decimal | None = None
        self.date_low: str | None = None
        self.date_high: str | None = None
        self.max_len = 0
        self.max_scale = 0
        self.max_int_digits = 0

    def observe(self, value: str, kind: str) -> None:
        self.max_len = max(self.max_len, len(value))
        if not self.capped:
            self.distinct.add(value)
            if len(self.distinct) > DISTINCT_CAP:
                self.capped = True
                self.distinct = set()
        if kind in ("integer", "decimal"):
            try:
                number = Decimal(value)
            except InvalidOperation:
                return
            self.low = number if self.low is None else min(self.low, number)
            self.high = number if self.high is None else max(self.high, number)
            mantissa = value.lower().split("e")[0].lstrip("+-")
            integer, _, fraction = mantissa.partition(".")
            self.max_int_digits = max(self.max_int_digits, len(integer.lstrip("0")) or 1)
            self.max_scale = max(self.max_scale, len(fraction))
        elif kind == "date":
            head = value[:10]
            self.date_low = head if self.date_low is None else min(self.date_low, head)
            self.date_high = head if self.date_high is None else max(self.date_high, head)


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
    stats = [_Stats() for _ in headers]

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
            stats[index].fingerprint.update(value.encode() + b"\x1f")
            if value == "":
                nulls[index] += 1
            else:
                kind = _classify(value)
                types[index].add(kind)
                stats[index].observe(value, kind)

    columns = [
        {
            "name": name,
            "type": _merge(types[i]),
            "nulls": nulls[i],
            "null_ratio": (nulls[i] / rows) if rows else 0.0,
            **_column_summary(stats[i], _merge(types[i]), rows - nulls[i]),
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
    profile.delimiter = getattr(dialect, "delimiter", ",")
    profile.rows_discarded = len(malformed)
    profile.privacy_hints = privacy_hints([c["name"] for c in columns])
    return profile


def _column_summary(st: _Stats, kind: str, filled: int) -> dict[str, Any]:
    numeric = kind in ("integer", "decimal") and st.low is not None
    dated = kind == "date" and st.date_low is not None
    return {
        "fingerprint": st.fingerprint.hexdigest(),
        "distinct": None if st.capped else len(st.distinct),
        "distinct_capped": st.capped,
        "is_key_candidate": (not st.capped) and filled > 0 and len(st.distinct) == filled,
        "min": str(st.low) if numeric else (st.date_low if dated else None),
        "max": str(st.high) if numeric else (st.date_high if dated else None),
        "max_len": st.max_len,
        "max_scale": st.max_scale if numeric else None,
        "max_int_digits": st.max_int_digits if numeric else None,
    }


def privacy_hints(column_names: list[str]) -> list[dict[str, str]]:
    """Columns whose NAMES suggest personal data. A heuristic, not a scan of the values."""
    hints = []
    for name in column_names:
        for reason, pattern in PRIVACY_HINTS:
            if pattern.search(name):
                hints.append({"column": name, "reason": reason})
                break
    return hints


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
    by_content: dict[str, list[str]] = {}
    for column in profile.columns:
        if column["nulls"] < profile.rows:  # an all-empty column is "identical" to every other all-empty one
            by_content.setdefault(column.get("fingerprint", column["name"]), []).append(column["name"])
    identical = [" = ".join(group) for group in by_content.values() if len(group) > 1]
    if identical:
        flags.append(Flag(
            "identical_columns", "Colunas com conteúdo idêntico", _listed(identical),
            "Confirme se uma delas é redundante antes de migrar; manter as duas duplica armazenamento e pode divergir.",
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
