-- ==========================================

  CREATE TABLE "TREXONE_ODS_DATA"."PURGE_ODS_CONFIG"
   (	"KEEP_HIST_DAYS" NUMBER,
	"PURGE_MODE" CHAR(1),
	"TABLE_NAME" VARCHAR2(30),
	"OVERRIDE_LLS_NAME" VARCHAR2(50),
	"OVERRIDE_AUDIT_NAME" VARCHAR2(30)
   ) ;
-- ==========================================
