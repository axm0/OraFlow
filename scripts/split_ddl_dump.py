"""Split a DBMS_METADATA spool dump into one .sql file per table.

Reads a monolithic DDL file produced by ``scripts/extract_trexone_*_ddl.sql``
and writes one ``<table_name>.sql`` per ``CREATE TABLE`` block into the chosen
output folder.

Usage:
    python scripts/split_ddl_dump.py <input_dump.sql> <output_dir> [--schema TREXONE_DATA]

If ``--schema`` is omitted, it is inferred from the first ``CREATE TABLE``
statement encountered.

The dumps emitted by ``extract_trexone_*_ddl.sql`` look like::

    -- ==========================================
    -- TABLE: TREXONE_DATA.PATIENT
    -- ==========================================
      CREATE TABLE "TREXONE_DATA"."PATIENT"
       (    "PD_PATIENT_KEY" NUMBER(18,0) ...
       ) ;

This script uses the ``-- TABLE: schema.table`` banner as the split boundary,
which is robust against mid-DDL line wrapping and multi-line constraint blocks.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BANNER_RE = re.compile(r"^--\s*TABLE:\s*([A-Z0-9_]+)\.([A-Z0-9_$#]+)\s*$", re.IGNORECASE)


def split_dump(input_path: Path, output_dir: Path, schema_filter: str | None) -> int:
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    current_table: str | None = None
    current_schema: str | None = None
    current_buf: list[str] = []

    def flush() -> None:
        nonlocal written, skipped, current_table, current_schema, current_buf
        if current_table is None or not current_buf:
            return
        if schema_filter and current_schema and current_schema.upper() != schema_filter.upper():
            skipped += 1
        else:
            target = output_dir / f"{current_table.lower()}.sql"
            target.write_text("".join(current_buf), encoding="utf-8")
            written += 1
        current_table = None
        current_schema = None
        current_buf = []

    with input_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            match = BANNER_RE.match(raw_line.strip())
            if match:
                # Flush the previous table before starting a new one.
                flush()
                current_schema = match.group(1)
                current_table = match.group(2)
                # Skip writing the banner itself; the DDL on the next lines is what matters.
                continue
            if current_table is not None:
                current_buf.append(raw_line)

    flush()  # last table

    print(f"wrote   {written} table file(s) to {output_dir}")
    if skipped:
        print(f"skipped {skipped} table(s) not matching --schema {schema_filter}")
    return 0 if written else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Path to the monolithic *_tables.sql dump.")
    parser.add_argument("output_dir", type=Path, help="Folder to write per-table .sql files into.")
    parser.add_argument(
        "--schema",
        default=None,
        help="Optional schema name filter (e.g. TREXONE_DATA). If omitted, accept all schemas.",
    )
    args = parser.parse_args()
    return split_dump(args.input, args.output_dir, args.schema)


if __name__ == "__main__":
    sys.exit(main())

