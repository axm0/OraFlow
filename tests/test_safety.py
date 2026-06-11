import pytest

from oraflow.safety import SqlSafetyError, validate_select_only


@pytest.mark.parametrize(
    "sql",
    [
        # Basic SELECT against tables.
        "select * from dual",
        "select * from TREXONE_DATA.PATIENT fetch first 5 rows only",
        # SELECT against views and materialized views.
        "select * from TREXONE_DATA.V_ORDER_PROFILE fetch first 5 rows only",
        "select * from TREXONE_DATA.MV_PATIENT_SUMMARY",
        # CTE / WITH.
        "with x as (select 1 as n from dual) select * from x",
        "with q as (select patient_num from trexone_data.patient) "
        "select count(*) from q",
        # JOIN of view + table.
        "select p.patient_num, v.order_num "
        "from   trexone_data.patient p "
        "join   trexone_data.v_order_profile v on v.patient_num = p.patient_num "
        "fetch first 50 rows only",
        # Aggregation, GROUP BY, HAVING.
        "select status, count(*) c from trexone_data.fill group by status having count(*) > 10",
        # Window functions.
        "select patient_num, "
        "row_number() over (partition by status order by created_date) rn "
        "from trexone_data.fill",
        # EXISTS / IN subqueries.
        "select * from trexone_data.patient p "
        "where exists (select 1 from trexone_data.fill f where f.patient_num = p.patient_num)",
        "select * from trexone_data.patient where patient_num in "
        "(select patient_num from trexone_data.fill)",
        # UNION ALL.
        "select 1 from dual union all select 2 from dual",
        # Comments and string literals containing semicolons must not break the validator.
        "/* comment */ select user from dual -- trailing comment",
        "select 'a;b;c' as s from dual",
    ],
)
def test_validate_select_only_allows_reads(sql):
    assert validate_select_only(sql).lower().lstrip().startswith(("select", "with"))


@pytest.mark.parametrize(
    "sql",
    [
        # DML / DDL / PL-SQL / admin.
        "update some_table set x = 1",
        "delete from some_table",
        "insert into some_table(x) values (1)",
        "merge into some_table t using other o on (t.id=o.id) when matched then update set t.x=o.x",
        "drop table some_table",
        "alter session set current_schema = TREXONE_DATA",
        "begin null; end;",
        "declare x number; begin x := 1; end;",
        "grant select on x to y",
        "revoke select on x from y",
        "truncate table x",
        "lock table x in exclusive mode",
        "set role all",
        "commit",
        "rollback",
        "savepoint sp1",
        # Multi-statement input.
        "select * from dual; delete from some_table",
        # Locking variants.
        "select * from some_table for update",
        "select * from some_table for update nowait",
        "select * from some_table for update of x",
        "select * from some_table for update skip locked",
        "select * from some_table for share",
        # PL/SQL-only SELECT INTO.
        "select x into v from dual",
        # Dangerous packages and schemas (including quoted forms).
        "select dbms_random.value from dual",
        'select "DBMS_OUTPUT".put_line(\'x\') from dual',
        "select * from sys.dual",
        'select * from "SYS"."DUAL"',
        "select * from system.objects",
        "select utl_http.request('http://x') from dual",
        "select dbms_sql.parse(1, 'select 1 from dual', 1) from dual",
        # Dynamic SQL.
        "select 1 from dual where 1 = (execute immediate 'select 1 from dual')",
    ],
)
def test_validate_select_only_rejects_writes_admin_and_unsafe(sql):
    with pytest.raises(SqlSafetyError):
        validate_select_only(sql)
