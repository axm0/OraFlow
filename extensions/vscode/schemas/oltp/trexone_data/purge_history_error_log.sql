-- ==========================================

  CREATE TABLE "TREXONE_DATA"."PURGE_HISTORY_ERROR_LOG"
   (	"TABLE_NAME" VARCHAR2(30),
	"PARTITION_NAME" VARCHAR2(30),
	"DATESTAMP" DATE,
	"STATEMENT" VARCHAR2(4000),
	"MESSAGE" VARCHAR2(500),
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE
   ) ;
-- ==========================================
