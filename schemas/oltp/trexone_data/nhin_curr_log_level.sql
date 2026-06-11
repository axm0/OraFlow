-- ==========================================

  CREATE TABLE "TREXONE_DATA"."NHIN_CURR_LOG_LEVEL"
   (	"CURRLLEVEL" NUMBER(4,0),
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE
   ) ;
-- ==========================================
