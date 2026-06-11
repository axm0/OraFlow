-- ==========================================

  CREATE TABLE "TREXONE_DATA"."PURGE_HISTORY_TAB_PARTITIONS"
   (	"TABLE_NAME" VARCHAR2(30),
	"PARTITION_NAME" VARCHAR2(30),
	"DATE_LOADED" DATE,
	"DATE_PURGED" DATE,
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE
   ) ;
-- ==========================================
