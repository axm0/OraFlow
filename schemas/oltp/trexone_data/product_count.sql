-- ==========================================

  CREATE TABLE "TREXONE_DATA"."PRODUCT_COUNT"
   (	"PRODUCT_KEY" NUMBER(18,0),
	"TOTAL_QTY" NUMBER(18,2),
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE
   ) ;
-- ==========================================
