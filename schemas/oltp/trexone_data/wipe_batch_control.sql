-- ==========================================

  CREATE TABLE "TREXONE_DATA"."WIPE_BATCH_CONTROL"
   (	"WIPE_CLIENT_ID" VARCHAR2(100) NOT NULL ENABLE,
	"CREATED" DATE DEFAULT sysdate,
	"STARTED" DATE,
	"COMPLETED" DATE,
	"STATUS" CHAR(1),
	"TABLE_COUNT" NUMBER(5,0),
	 CONSTRAINT "PK_WIPE_BATCH_CONTROL" PRIMARY KEY ("WIPE_CLIENT_ID")
  USING INDEX  ENABLE
   ) ;
-- ==========================================
