-- ============================================================================
-- extract_trexone_aud_data_ddl.sql
-- Extract every CREATE TABLE DDL for the TREXONE_AUD_DATA (OLAP / Audit) schema.
-- AUD = Audit, the second ETL stage in the warehouse pipeline
-- (TREXONE_DATA -> TREXONE_ODS_DATA -> TREXONE_AUD_DATA -> TREXONE_DW_DATA).
-- Run via SQL*Plus or Toad (script mode, F5).
-- Output: C:\Developer\Workspace\EnterpriseRx\OraFlow\trexone_data_dumps\TREXONE_AUD_DATA_tables.sql
-- ============================================================================
SET PAGESIZE 0
SET HEADING OFF
SET FEEDBACK OFF
SET TERMOUT OFF
SET LINESIZE 32767
SET LONG 100000000
SET LONGCHUNKSIZE 1000000
SET TRIMSPOOL ON
SET VERIFY OFF
SET SERVEROUTPUT OFF
BEGIN
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'CONSTRAINTS',        TRUE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'REF_CONSTRAINTS',    TRUE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'STORAGE',            FALSE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES', FALSE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'TABLESPACE',         FALSE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'EMIT_SCHEMA',        TRUE);
  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SQLTERMINATOR',      TRUE);
END;
/
SPOOL "C:/Developer/Workspace/EnterpriseRx/OraFlow/trexone_data_dumps/TREXONE_AUD_DATA_tables.sql"
SELECT '-- =========================================='   || CHR(10) ||
       '-- TABLE: ' || owner || '.' || table_name        || CHR(10) ||
       '-- =========================================='   || CHR(10) ||
       DBMS_METADATA.GET_DDL('TABLE', table_name, owner) || CHR(10)
FROM   ALL_TABLES
WHERE  owner = 'TREXONE_AUD_DATA'
ORDER  BY table_name;
SPOOL OFF
SET TERMOUT ON
SET HEADING ON
SET FEEDBACK ON
PROMPT Done. See C:\Developer\Workspace\EnterpriseRx\OraFlow\trexone_data_dumps\TREXONE_AUD_DATA_tables.sql
