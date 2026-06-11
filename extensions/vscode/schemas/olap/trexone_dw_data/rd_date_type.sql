-- ==========================================

  CREATE TABLE "TREXONE_DW_DATA"."RD_DATE_TYPE"
   (	"RD_DATE_TYPE_ID" NUMBER(18,0),
	"RD_DATE_TYPE_NAME" VARCHAR2(30),
	"RD_DATE_TYPE_DESC" VARCHAR2(100),
	 CONSTRAINT "PK_RD_DATE_TYPE" PRIMARY KEY ("RD_DATE_TYPE_ID")
  USING INDEX  ENABLE
   ) ;
-- ==========================================
