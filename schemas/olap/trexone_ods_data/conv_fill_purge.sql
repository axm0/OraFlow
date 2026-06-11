-- ==========================================

  CREATE TABLE "TREXONE_ODS_DATA"."CONV_FILL_PURGE"
   (	"FACILITY_NUM" NUMBER(18,0) NOT NULL ENABLE,
	"RX_RECORD_NUM" NUMBER(18,0) NOT NULL ENABLE,
	"RX_FILL_SEQ" NUMBER(18,0) NOT NULL ENABLE,
	"DATESTAMP" DATE,
	"H_LEVEL" NUMBER,
	"ERX_CLIENT_ID" VARCHAR2(100)
   ) ;
-- ==========================================
