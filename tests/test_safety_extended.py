"""Extended safety tests — every realistic Oracle 19c SELECT shape we expect
to investigate, and every realistic write/admin shape we must reject. These
build on `test_safety.py` to give wider coverage of the validator that gates
both `run_sql_script` and `run_query_once`.
"""

from __future__ import annotations

import pytest

from oraflow.safety import SqlSafetyError, validate_select_only

# ---------------------------------------------------------------------------
# Allowed: complex but read-only SELECT shapes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # LEFT / RIGHT / FULL OUTER joins.
        "select p.patient_num, f.fill_num "
        "from trexone_data.patient p "
        "left outer join trexone_data.fill f on f.patient_num = p.patient_num",
        "select p.patient_num, f.fill_num "
        "from trexone_data.patient p "
        "full outer join trexone_data.fill f on f.patient_num = p.patient_num",
        # Self-join.
        "select a.rx_record_num, b.rx_record_num as reassigned_to "
        "from trexone_data.rx_base a "
        "join trexone_data.rx_base b on b.reassigned_rx_num = a.rx_record_num",
        # Anti-join via NOT EXISTS.
        "select * from trexone_data.patient p "
        "where not exists (select 1 from trexone_data.fill f "
        "where f.patient_num = p.patient_num)",
        # Multiple chained CTEs.
        "with chain as (select 1 n from dual), "
        "extras as (select 2 n from dual) "
        "select * from chain union all select * from extras",
        # Recursive CTE.
        "with cte (n) as (select 1 from dual union all select n+1 from cte where n < 5) "
        "select * from cte",
        # CONNECT BY hierarchical query.
        "select level, e.name from trexone_data.employee e "
        "start with e.manager_num is null connect by prior e.employee_num = e.manager_num",
        # PIVOT / UNPIVOT.
        "select * from (select status, patient_num from trexone_data.fill) "
        "pivot (count(*) for status in ('A' as active, 'I' as inactive))",
        # LISTAGG aggregate.
        "select patient_num, listagg(rx_number, ',') within group (order by rx_number) rxs "
        "from trexone_data.rx_base group by patient_num",
        # Analytic functions: LAG / LEAD / NTILE / RANK.
        "select patient_num, lag(datestamp) over (partition by patient_num order by datestamp) "
        "from trexone_data.fill",
        "select patient_num, ntile(4) over (order by datestamp) "
        "from trexone_data.fill",
        # JSON_VALUE / JSON_TABLE (Oracle 12c+).
        "select json_value(payload, '$.id') as id from trexone_data.event_payload",
        # Date/timestamp predicates with intervals and ADD_MONTHS.
        "select * from trexone_data.system_audit "
        "where partition_date > add_months(sysdate, -24) "
        "and start_time > sysdate - interval '7' day",
        # Subquery in SELECT clause.
        "select p.patient_num, "
        "(select count(*) from trexone_data.fill f where f.patient_num = p.patient_num) cnt "
        "from trexone_data.patient p",
        # Set operators beyond UNION ALL.
        "select 1 from dual union select 2 from dual",
        "select 1 from dual intersect select 1 from dual",
        "select 1 from dual minus select 2 from dual",
        # Cross-schema joins.
        "select d.patient_num, dw.refill_count "
        "from trexone_data.patient d "
        "join trexone_dw_data.patient_summary dw on dw.patient_num = d.patient_num",
        # FETCH FIRST / OFFSET.
        "select * from trexone_data.fill order by datestamp desc offset 100 rows fetch next 50 rows only",
        # CASE in SELECT, WHERE, ORDER BY.
        "select case when status = 1 then 'A' else 'X' end status_label "
        "from trexone_data.rx_base "
        "where case when refills_authorized > 0 then 'Y' else 'N' end = 'Y' "
        "order by case when datestamp is null then 1 else 0 end",
        # COALESCE / NVL / NULLIF.
        "select coalesce(rx_number, 'NONE'), nvl(refills_authorized, 0), "
        "nullif(rx_number, 'EMPTY') from trexone_data.rx_base",
        # Subquery factoring with materialize hint (still SELECT-only).
        "with /*+ materialize */ chain as (select 1 n from dual) select * from chain",
        # Schema-qualified view of an audit/history table.
        "select * from trexone_data.h_rx where partition_date > add_months(sysdate, -24)",
    ],
)
def test_complex_selects_are_allowed(sql):
    cleaned = validate_select_only(sql)
    assert cleaned.lower().lstrip("( ").startswith(("select", "with"))


# ---------------------------------------------------------------------------
# Rejected: write / admin / dangerous patterns the validator must block.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # CREATE variants (table, view, index, mview, sequence, synonym).
        "create table t (n number)",
        "create or replace view v as select * from dual",
        "create index i on t(c)",
        "create materialized view mv as select * from dual",
        "create sequence s start with 1",
        "create or replace synonym my_dual for dual",
        # ALTER TABLE / SESSION / SYSTEM.
        "alter table t add (n number)",
        "alter session set current_schema = SOMETHING",
        "alter system flush shared_pool",
        # DROP variants.
        "drop view v",
        "drop index i",
        "drop sequence s",
        "drop user u cascade",
        # DML.
        "update trexone_data.rx_base set rx_status_num = 9",
        "delete from trexone_data.rx_base where rx_status_num = 9",
        "insert into trexone_data.rx_base (rx_record_num) values (1)",
        "insert into trexone_data.rx_base select * from trexone_data.rx_base where 1=0",
        "merge into t using s on (t.id=s.id) when matched then update set t.x=s.x",
        # PL/SQL anonymous blocks.
        "begin update trexone_data.rx_base set rx_status_num = 9; end;",
        "declare v number; begin select 1 into v from dual; end;",
        # PL/SQL stored procedure / function call.
        "call my_proc(1)",
        "exec my_proc(1)",
        "execute my_proc(1)",
        # Locking and transaction control.
        "lock table trexone_data.rx_base in exclusive mode",
        "select * from trexone_data.rx_base for update",
        "select * from trexone_data.rx_base for share",
        "commit",
        "rollback to savepoint sp1",
        "savepoint sp1",
        "set transaction read write",
        "set role none",
        # GRANT / REVOKE.
        "grant select on trexone_data.rx_base to public",
        "revoke select on trexone_data.rx_base from public",
        # Multi-statement input is rejected even if both are reads.
        "select 1 from dual; select 2 from dual",
        # SELECT ... INTO is PL/SQL form, not allowed in the data tool surface.
        "select rx_record_num into v from trexone_data.rx_base where rownum = 1",
        # Dangerous packages / dynamic SQL.
        "select dbms_random.value(0,1) from dual",
        'select "DBMS_LOB".getlength(c) from t',
        "select utl_file.fopen('x','y','r') from dual",
        "select dbms_sql.open_cursor from dual",
        "select 1 from dual where (execute immediate 'select 1 from dual') = 1",
        # SYS./SYSTEM. references.
        "select * from sys.user_tables",
        'select * from "SYSTEM"."DBA_TABLES"',
        # FLASHBACK / PURGE.
        "flashback table t to timestamp sysdate - 1",
        "purge recyclebin",
        # TRUNCATE.
        "truncate table trexone_data.rx_base",
    ],
)
def test_writes_admin_and_unsafe_are_rejected(sql):
    with pytest.raises(SqlSafetyError):
        validate_select_only(sql)


# ---------------------------------------------------------------------------
# Edge cases that must NOT be confused for multi-statement input.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # Trailing semicolon is fine.
        "select 1 from dual;",
        # Multiple trailing semicolons (unusual but harmless).
        "select 1 from dual;;;",
        # Block comment containing a semicolon.
        "/* note: a;b */ select 1 from dual",
        # String literal containing a semicolon.
        "select 'a;b' from dual",
        # Inline -- comment after terminator.
        "select 1 from dual; -- end",
    ],
)
def test_single_statement_with_inert_semicolons_passes(sql):
    cleaned = validate_select_only(sql)
    assert cleaned.lower().lstrip("( ").startswith(("select", "with"))

