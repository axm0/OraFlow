-- ==========================================

  CREATE TABLE "TREXONE_ODS_DATA"."H_ETL_PROC"
   (	"ETL_PROC_NUM" NUMBER(18,0),
	"ETL_STEP_NUM" NUMBER(18,0),
	"PROC_NAME" VARCHAR2(100),
	"IS_ACTIVE" CHAR(1),
	"RUN_GROUP" NUMBER(20,2),
	"IS_NEXT_GROUP_DEPENDENT" CHAR(1),
	"RUN_PRIORITY" NUMBER(20,2),
	"LOOP_HOURS" NUMBER,
	"DATESTAMP" DATE,
	"H_TYPE" CHAR(1),
	"H_LEVEL" NUMBER,
	"ERX_CLIENT_ID" VARCHAR2(100)
   ) ;
-- ==========================================
