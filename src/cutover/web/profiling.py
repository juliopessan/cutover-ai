"""Deterministic dataset profiling. Every figure is computed from the uploaded bytes."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Characters that Delta Lake (Databricks and Fabric Lakehouse) rejects in column names.
INVALID_NAME_CHARS = re.compile(r"[ ,;{}()\n\t=]")
MOSTLY_EMPTY_RATIO = 0.5
MAX_LISTED = 8

_INT = re.compile(r"^[+-]?\d+$")
# "1.234" is ambiguous: 1.234 in US notation, one thousand two hundred thirty-four in Brazilian notation.
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+$")
_DECIMAL_BR = re.compile(r"^[+-]?(\d{1,3}(\.\d{3})+|\d+),\d+$")
_DECIMAL_US = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:([T ])(\d{2}):(\d{2})(?::(\d{2}))?)?$")
_DMY = re.compile(r"^(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_BOOL = {"true", "false"}
NUMERIC_KINDS = {"integer", "decimal", "decimal_br", "int_thousands"}


DISTINCT_CAP = 100_000
PROFILE_VERSION = 3
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
    encoding: str = "utf-8"
    profile_version: int = PROFILE_VERSION

    @property
    def filled_cells(self) -> int:
        return self.total_cells - self.empty_cells

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _DateParts:
    """One parsed date value. ``dmy`` and ``mdy`` are the dates it would be in each reading (None if invalid)."""

    __slots__ = ("family", "sep", "tsep", "dmy", "mdy", "padded", "time", "seconds", "hour_padded")

    def __init__(self, family, sep, tsep, dmy, mdy, padded, time, seconds, hour_padded):
        self.family, self.sep, self.tsep, self.dmy, self.mdy = family, sep, tsep, dmy, mdy
        self.padded, self.time, self.seconds, self.hour_padded = padded, time, seconds, hour_padded


def _parse_date(value: str) -> _DateParts | None:
    iso = _ISO.match(value)
    if iso:
        try:
            parsed = date(int(iso[1]), int(iso[2]), int(iso[3]))
        except ValueError:
            return None
        return _DateParts("iso", "-", iso[4] or "", parsed, parsed, True, iso[5] is not None, iso[7] is not None, True)
    m = _DMY.match(value)
    if not m:
        return None
    a, b, year = int(m[1]), int(m[3]), int(m[4])
    dmy = mdy = None
    try:
        dmy = date(year, b, a)
    except ValueError:
        pass
    try:
        mdy = date(year, a, b)
    except ValueError:
        pass
    if dmy is None and mdy is None:
        return None
    padded = len(m[1]) == 2 and len(m[3]) == 2
    return _DateParts("dmy", m[2], "", dmy, mdy, padded, m[5] is not None, m[7] is not None, m[5] is None or len(m[5]) == 2)


def _classify(value: str) -> str:
    if _INT.match(value):
        return "integer"
    if _THOUSANDS.match(value):
        return "int_thousands"
    if _DECIMAL_BR.match(value):
        return "decimal_br"
    if _DECIMAL_US.match(value):
        return "decimal"
    if value.lower() in _BOOL:
        return "boolean"
    if _parse_date(value):
        return "date"
    return "text"


class _Num:
    """Range and decimal shape of one reading of the numbers in a column."""

    __slots__ = ("low", "high", "scale", "digits")

    def __init__(self) -> None:
        self.low: Decimal | None = None
        self.high: Decimal | None = None
        self.scale = 0
        self.digits = 0

    def add(self, number: Decimal, scale: int, digits: int) -> None:
        self.low = number if self.low is None else min(self.low, number)
        self.high = number if self.high is None else max(self.high, number)
        self.scale, self.digits = max(self.scale, scale), max(self.digits, digits)


def _canon(number: Decimal) -> str:
    return format(number.normalize(), "f")


def _shape(text: str) -> tuple[int, int]:
    """(digits before the point, digits after it) of a plain ``123.45`` string."""
    mantissa = text.lower().split("e")[0].lstrip("+-")
    integer, _, fraction = mantissa.partition(".")
    return len(integer.lstrip("0")) or 1, len(fraction)


class _Stats:
    """Per-column aggregates. Ambiguous values are tracked under every reading; the column decides at the end."""

    __slots__ = ("fingerprint", "distinct", "capped", "max_len", "us", "br", "shared", "us_only", "br_only",
                 "patterns", "dmy_ok", "mdy_ok", "dmy_low", "dmy_high", "mdy_low", "mdy_high", "padded", "unpadded", "hour_padded", "hour_unpadded")

    def __init__(self) -> None:
        self.fingerprint = hashlib.blake2b(digest_size=16)
        self.distinct: set[str] = set()
        self.capped = False
        self.max_len = 0
        self.us, self.br = _Num(), _Num()
        self.shared: set[str] = set()
        self.us_only: set[str] = set()
        self.br_only: set[str] = set()
        self.patterns: set[tuple[Any, ...]] = set()
        self.dmy_ok = self.mdy_ok = True
        self.dmy_low = self.dmy_high = self.mdy_low = self.mdy_high = None
        self.padded = self.unpadded = self.hour_padded = self.hour_unpadded = False

    def _count(self) -> int:
        return len(self.distinct) + len(self.shared) + len(self.us_only) + len(self.br_only)

    def observe(self, value: str, kind: str) -> None:
        self.max_len = max(self.max_len, len(value))
        if not self.capped:
            self.distinct.add(value.lower() if kind == "boolean" else value)
            if self._count() > DISTINCT_CAP:
                self.capped = True
                self.distinct, self.shared, self.us_only, self.br_only = set(), set(), set(), set()
        if kind in NUMERIC_KINDS:
            self._observe_number(value, kind)
        elif kind == "date":
            self._observe_date(value)

    def _observe_number(self, value: str, kind: str) -> None:
        try:
            if kind == "integer":
                number = Decimal(value)
                digits, scale = _shape(value)
                self.us.add(number, 0, digits)
                self.br.add(number, 0, digits)
                key, bucket = _canon(number), self.shared
            elif kind == "decimal":
                number = Decimal(value)
                digits, scale = _shape(value)
                self.us.add(number, scale, digits)
                key, bucket = _canon(number), self.us_only
            elif kind == "decimal_br":
                number = Decimal(value.replace(".", "").replace(",", "."))
                digits, scale = _shape(value.replace(".", "").replace(",", "."))
                self.br.add(number, scale, digits)
                key, bucket = _canon(number), self.br_only
            else:  # int_thousands
                us_number, br_number = Decimal(value), Decimal(value.replace(".", ""))
                self.us.add(us_number, *reversed(_shape(value)))
                self.br.add(br_number, 0, _shape(value.replace(".", ""))[0])
                if not self.capped:
                    self.us_only.add(_canon(us_number))
                    self.br_only.add(_canon(br_number))
                return
        except InvalidOperation:
            return
        if not self.capped:
            bucket.add(key)

    def _observe_date(self, value: str) -> None:
        parts = _parse_date(value)
        if parts is None:
            return
        self.patterns.add((parts.family, parts.sep, parts.tsep, parts.time, parts.seconds))
        if parts.family == "dmy":
            self.dmy_ok &= parts.dmy is not None
            self.mdy_ok &= parts.mdy is not None
        for reading, low, high in (("dmy", "dmy_low", "dmy_high"), ("mdy", "mdy_low", "mdy_high")):
            when = getattr(parts, reading)
            if when is not None:
                current_low, current_high = getattr(self, low), getattr(self, high)
                setattr(self, low, when if current_low is None else min(current_low, when))
                setattr(self, high, when if current_high is None else max(current_high, when))
        if parts.padded:
            self.padded = True
        else:
            self.unpadded = True
        if parts.time:
            if parts.hour_padded:
                self.hour_padded = True
            else:
                self.hour_unpadded = True


def _date_format(st: _Stats, order: str) -> str:
    (family, sep, tsep, has_time, has_seconds), = st.patterns
    if family == "iso":
        pattern = "yyyy-MM-dd" + (("'T'" if tsep == "T" else " ") + "HH:mm" + (":ss" if has_seconds else "") if has_time else "")
        return pattern
    day, month = ("d", "M") if st.unpadded else ("dd", "MM")
    first, second = (day, month) if order == "dmy" else (month, day)
    pattern = f"{first}{sep}{second}{sep}yyyy"
    if has_time:
        pattern += " " + ("H" if st.hour_unpadded else "HH") + ":mm" + (":ss" if has_seconds else "")
    return pattern


def _resolve(kinds: set[str], st: _Stats, filled: int) -> dict[str, Any]:
    """Decide the column's type and formats from everything seen. Returns the column's measured description."""
    out: dict[str, Any] = {"date_format": None, "date_ambiguous": False, "has_time": False, "number_style": None}
    if not kinds:
        return {"type": "empty", **out}
    if kinds <= NUMERIC_KINDS:
        has_br, has_us_decimal = "decimal_br" in kinds, "decimal" in kinds
        if has_br and has_us_decimal:
            return {"type": "mixed", **out}
        style = "br" if has_br else "us"
        tracker = st.br if style == "br" else st.us
        kind = "integer" if kinds == {"integer"} else "decimal"
        only = st.br_only if style == "br" else st.us_only
        out["number_style"] = style if kind == "decimal" else None
        out["_numbers"] = (tracker, st.shared | only)
        return {"type": kind, **out}
    if kinds == {"date"}:
        if len(st.patterns) != 1:
            return {"type": "mixed", **out}
        (family, _sep, _tsep, has_time, _seconds), = st.patterns
        order, ambiguous = "dmy", False
        if family == "dmy":
            if st.dmy_ok and not st.mdy_ok:
                order = "dmy"
            elif st.mdy_ok and not st.dmy_ok:
                order = "mdy"
            elif st.dmy_ok and st.mdy_ok:
                order, ambiguous = "dmy", True
            else:
                return {"type": "mixed", **out}
        low, high = (st.mdy_low, st.mdy_high) if order == "mdy" else (st.dmy_low, st.dmy_high)
        out.update(date_format=_date_format(st, order), date_ambiguous=ambiguous, has_time=has_time,
                   _dates=(low, high, (st.padded and st.unpadded) or (st.hour_padded and st.hour_unpadded)))
        return {"type": "date", **out}
    if len(kinds) == 1:
        return {"type": next(iter(kinds)), **out}
    return {"type": "mixed", **out}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode(raw: bytes) -> tuple[str, str]:
    """Decode the file and say which encoding worked. UTF-8 first, then the Windows and Latin encodings common in Brazil."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:8192]:
        raise ProfileError("O arquivo parece ser UTF-16 ou binário. Exporte como CSV em UTF-8.")
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252"), "windows-1252"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def profile_csv(path: Path) -> DatasetProfile:
    raw = path.read_bytes()
    if not raw.strip():
        raise ProfileError("O arquivo está vazio.")
    text, encoding = _decode(raw)
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

    columns = []
    for i, name in enumerate(headers):
        resolved = _resolve(types[i], stats[i], rows - nulls[i])
        columns.append({
            "name": name, "type": resolved["type"], "nulls": nulls[i], "null_ratio": (nulls[i] / rows) if rows else 0.0,
            **_column_summary(stats[i], resolved, rows - nulls[i]),
        })
    profile = DatasetProfile(
        sha256=sha256_file(path),
        rows=rows,
        columns=columns,
        duplicate_rows=duplicates,
        empty_cells=sum(nulls),
        total_cells=rows * width,
    )
    profile.encoding = encoding
    profile.flags = _flags(profile, malformed)
    profile.delimiter = getattr(dialect, "delimiter", ",")
    profile.rows_discarded = len(malformed)
    profile.privacy_hints = privacy_hints([c["name"] for c in columns])
    return profile


def _column_summary(st: _Stats, resolved: dict[str, Any], filled: int) -> dict[str, Any]:
    kind = resolved["type"]
    numbers, dates = resolved.get("_numbers"), resolved.get("_dates")
    distinct: int | None = None if st.capped else len(st.distinct)
    low = high = scale = digits = None
    if numbers and numbers[0].low is not None:
        tracker, values = numbers
        low, high, scale, digits = str(tracker.low), str(tracker.high), tracker.scale, tracker.digits
        distinct = None if st.capped else len(values)
    elif dates and dates[0] is not None:
        low, high = dates[0].isoformat(), dates[1].isoformat()
        if dates[2]:
            distinct = None  # "1/2/2026" and "01/02/2026" are one date typed but two strings raw
    return {
        "fingerprint": st.fingerprint.hexdigest(),
        "distinct": distinct,
        "distinct_capped": st.capped,
        "is_key_candidate": distinct is not None and filled > 0 and distinct == filled,
        "min": low, "max": high, "max_len": st.max_len,
        "max_scale": scale if kind in ("integer", "decimal") else None,
        "max_int_digits": digits if kind in ("integer", "decimal") else None,
        "date_format": resolved["date_format"], "date_ambiguous": resolved["date_ambiguous"],
        "has_time": resolved["has_time"], "number_style": resolved["number_style"],
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
    ambiguous = [f"{c['name']} (assumido {c['date_format']})" for c in profile.columns if c.get("date_ambiguous")]
    if ambiguous:
        flags.append(Flag(
            "ambiguous_dates", "Datas ambíguas (dia/mês ou mês/dia)", _listed(ambiguous),
            "Todos os valores são válidos nas duas ordens; o perfil assumiu dia/mês (padrão brasileiro). "
            "Confirme com o dono do dado: um erro aqui troca dia e mês sem gerar nenhuma falha.",
        ))
    if profile.encoding != "utf-8":
        flags.append(Flag(
            "encoding", "Arquivo fora de UTF-8", [profile.encoding],
            "O código de carga gerado já informa essa codificação. Se puder, exporte em UTF-8 para evitar surpresas.",
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
