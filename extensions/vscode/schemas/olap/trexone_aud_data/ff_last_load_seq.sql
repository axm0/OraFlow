-- ==========================================

  CREATE TABLE "TREXONE_AUD_DATA"."FF_LAST_LOAD_SEQ"
   (	"LAST_FS_H_LEVEL" NUMBER,
	"TABLE_NAME" VARCHAR2(100),
	"FEED_FORMAT" VARCHAR2(40),
	"RECORD_FORMAT" VARCHAR2(40),
	"DATESTAMP" DATE,
	"LAST_TX_DATE" DATE,
	"FACILITY_NUM" NUMBER(18,0),
	"ERX_CLIENT_ID" VARCHAR2(100)
   ) ;
-- ==========================================
