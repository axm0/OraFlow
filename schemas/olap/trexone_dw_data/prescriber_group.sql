-- ==========================================

  CREATE TABLE "TREXONE_DW_DATA"."PRESCRIBER_GROUP"
   (	"PRESCRIBER_NUM" NUMBER(18,0),
	"GROUP_NUM" NUMBER(18,0),
	"GROUP_NAME" VARCHAR2(30),
	"MEMBER_STATUS" VARCHAR2(10),
	"ERX_CLIENT_ID" VARCHAR2(100) DEFAULT sys_context('ERX_CONTEXT', 'ERX_CLIENT_ID')
   ) ;
-- ==========================================
