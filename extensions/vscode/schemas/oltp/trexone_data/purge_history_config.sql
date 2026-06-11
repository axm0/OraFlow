-- ==========================================

  CREATE TABLE "TREXONE_DATA"."PURGE_HISTORY_CONFIG"
   (	"TABLE_NAME" VARCHAR2(30),
	"RETENTION_TIME" NUMBER,
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE
   ) ;
-- ==========================================
