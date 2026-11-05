"""Read-only access to source files.

Pattern 1: start read-only. The connector can list and read CSV files inside
one folder. It has no method that writes, every file is opened in read mode,
and the rows it returns cannot be changed.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class Source:
    """Where a value came from: file, data row (header excluded) and column."""

    file: str
    row: int
    column: str

    def __str__(self) -> str:
        return f"{self.file} row {self.row} column {self.column}"


@dataclass(frozen=True)
class Cell:
    value: str
    source: Source


Row = Mapping[str, Cell]


class ReadOnlyCSVConnector:
    """Reads CSV files from a single folder. Nothing in this class writes."""

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "_root", Path(root).resolve())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ReadOnlyCSVConnector cannot be modified")

    @property
    def root(self) -> Path:
        return self._root

    def files(self) -> tuple[str, ...]:
        return tuple(sorted(p.name for p in self._root.glob("*.csv")))

    def _path(self, name: str) -> Path:
        path = (self._root / name).resolve()
        if path.parent != self._root:
            raise PermissionError(f"{name} is outside the connector folder")
        return path

    def rows(self, name: str) -> tuple[Row, ...]:
        """Return every data row of a CSV file, each cell tagged with its source."""
        with self._path(name).open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return tuple(
                MappingProxyType(
                    {col: Cell(val, Source(name, i, col)) for col, val in record.items()}
                )
                for i, record in enumerate(reader, start=1)
            )

    def fingerprint(self, *names: str) -> str:
        """SHA-256 over the named files, so a result can be tied to exact inputs."""
        digest = hashlib.sha256()
        for name in sorted(names):
            digest.update(name.encode())
            digest.update(self._path(name).read_bytes())
        return digest.hexdigest()[:16]
