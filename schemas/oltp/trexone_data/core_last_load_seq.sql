-- ==========================================

  CREATE TABLE "TREXONE_DATA"."CORE_LAST_LOAD_SEQ"
   (	"TABLE_NAME" VARCHAR2(30),
	"SEQ_NUM" NUMBER,
	"WF_STEP" NUMBER(18,0),
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID') NOT NULL ENABLE,
	 CONSTRAINT "PK_CORE_LAST_LOAD_SEQ" PRIMARY KEY ("TABLE_NAME", "ERX_CLIENT_ID")
  USING INDEX  ENABLE
   ) ;
-- ==========================================
