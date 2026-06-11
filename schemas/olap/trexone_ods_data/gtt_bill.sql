-- ==========================================

  CREATE GLOBAL TEMPORARY TABLE "TREXONE_ODS_DATA"."GTT_BILL"
   (	"ORDER_NUM" NUMBER(18,0),
	"ITEM_SEQ" NUMBER(18,0),
	"STATUS" CHAR(1),
	"BILL_DATE" DATE,
	"DAYS_SUPPLY" NUMBER(9,3),
	"BILLING_QTY" NUMBER(13,3),
	"BILLING_DAYS" NUMBER(5,0),
	"CARRY_OVER_QTY" NUMBER(13,3),
	"EFF_START_DATE" DATE,
	"EFF_END_DATE" DATE
   ) ON COMMIT DELETE ROWS ;
-- ==========================================
