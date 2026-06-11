-- ==========================================

  CREATE TABLE "TREXONE_DW_DATA"."RD_USER_LOGIN_FACILITY"
   (	"SYS_USER_KEY" NUMBER(18,0),
	"FD_FACILITY_KEY" NUMBER(18,0),
	"FACILITY_VALUE" VARCHAR2(20) DEFAULT 'Login Facility' NOT NULL ENABLE,
	 CONSTRAINT "PK_RD_USER_LOGIN_FACILITY" PRIMARY KEY ("SYS_USER_KEY")
  USING INDEX  ENABLE
   ) ;
-- ==========================================
