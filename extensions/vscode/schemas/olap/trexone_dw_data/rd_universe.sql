-- ==========================================

  CREATE TABLE "TREXONE_DW_DATA"."RD_UNIVERSE"
   (	"RD_UNIVERSE_ID" NUMBER(18,0),
	"RD_UNIVERSE_NAME" VARCHAR2(30),
	"RD_UNIVERSE_DESC" VARCHAR2(1000),
	 CONSTRAINT "PK_RD_UNIVERSE" PRIMARY KEY ("RD_UNIVERSE_ID")
  USING INDEX  ENABLE
   ) ;
-- ==========================================
