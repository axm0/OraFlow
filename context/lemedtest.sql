--------------------------------------------------------------------------------
-- ERXD-69638 verification queries for Mary
-- Read-only. Run against LeMed production (trexone_data schema).
-- Three queries:
--   Q1: Single-order proof   - full workflow history for order 10006319400
--   Q2: De-duplicated count  - 13 unique suspicious PV1 records over last 8 months
--   Q3: Victim/trigger pairs - matches each victim to the sibling PV1 that
--                              completed at the moment the victim was swept to PV2
--
-- Block numbers:
--   108100 = Pre-Verification 1 (PV1)
--   108300 = Pre-Verification 2 (PV2)
--
-- The signature we are looking for on a victim PV1 row:
--   wf_block_definition_num = 108100
--   node_state              = 'ACTIVATED'
--   completion_date         IS NULL
--   AND a later PV2 row exists for the same proc_inst_seq with node_seq > victim.node_seq
--------------------------------------------------------------------------------

SET LINESIZE 250
SET PAGESIZE 200
SET TRIMSPOOL ON
SET NUMWIDTH 15
COLUMN rx_number FORMAT A12
COLUMN victim_rx FORMAT A12
COLUMN trigger_rx FORMAT A12
COLUMN block_name FORMAT A30
COLUMN node_state FORMAT A15
COLUMN duplicate_reason FORMAT A80


-- ===========================================================================
-- Q1: Full workflow history for the cleanest single-order example.
-- Order 10006319400 has 2 Rxs: 6987406 (trigger, PV1 COMPLETED) and
-- 6987403 (victim, PV1 ACTIVATED with NULL completion, then PV2 row appears).
-- Expected: ~16 rows. Look at the two PV1 rows (block 108100) side by side.
-- ===========================================================================
SELECT rb.rx_number, wpi.proc_inst_seq, wui.node_seq, wui.node_instance_seq,
       wbd.description AS block_name, wbd.wf_block_definition_num AS block_num,
       wui.node_state, wui.state_date, wui.activated_date, wui.completion_date,
       wui.complete_user, wui.lock_user, wui.lock_date, wui.decline_reason
FROM trexone_data.wf_process_instance wpi
         JOIN trexone_data.item i
              ON i.order_num = wpi.order_num
                  AND i.item_seq = wpi.item_seq
         JOIN trexone_data.rx_base rb
              ON rb.rx_record_num = i.rx_record_num
         JOIN trexone_data.wf_user_item wui
              ON wui.wf_process_definition_num = wpi.wf_process_definition_num
                  AND wui.proc_inst_seq = wpi.proc_inst_seq
         JOIN trexone_data.wf_block_definition wbd
              ON wbd.wf_block_definition_num = wui.wf_block_definition_num
WHERE wpi.order_num = 10006319400
ORDER BY rb.rx_number, wui.node_seq, wui.node_instance_seq;


-- ===========================================================================
-- Q2: De-duplicated list of suspicious PV1 records over the last 8 months.
-- Expected: 13 rows.
-- The original B1 query returned 23/21 rows because some victims had multiple
-- later PV2 rows. The GROUP BY here collapses those duplicates to one row per
-- unique suspicious PV1 record (proc_inst_seq + node_seq + node_instance_seq).
-- ===========================================================================
WITH suspicious AS (
    SELECT victim.wf_process_definition_num,
           victim.proc_inst_seq,
           victim.node_seq,
           victim.node_instance_seq,
           rb.rx_number,
           wpi.order_num,
           wpi.item_seq,
           victim.state_date,
           victim.activated_date,
           victim.lock_user,
           victim.lock_date,
           MIN(pv2.state_date) AS first_pv2_arrival,
           COUNT(*)            AS later_pv2_rows
    FROM trexone_data.wf_user_item victim
             JOIN trexone_data.wf_user_item pv2
                  ON pv2.wf_process_definition_num = victim.wf_process_definition_num
                      AND pv2.proc_inst_seq = victim.proc_inst_seq
                      AND pv2.wf_block_definition_num = 108300
                      AND pv2.node_seq > victim.node_seq
             JOIN trexone_data.wf_process_instance wpi
                  ON wpi.wf_process_definition_num = victim.wf_process_definition_num
                      AND wpi.proc_inst_seq = victim.proc_inst_seq
             JOIN trexone_data.item i
                  ON i.order_num = wpi.order_num
                      AND i.item_seq = wpi.item_seq
             JOIN trexone_data.rx_base rb
                  ON rb.rx_record_num = i.rx_record_num
    WHERE victim.wf_block_definition_num = 108100
      AND   victim.completion_date IS NULL
      AND   victim.node_state = 'ACTIVATED'
      AND   victim.state_date > ADD_MONTHS(SYSDATE, -8)
    GROUP BY victim.wf_process_definition_num,
             victim.proc_inst_seq,
             victim.node_seq,
             victim.node_instance_seq,
             rb.rx_number,
             wpi.order_num,
             wpi.item_seq,
             victim.state_date,
             victim.activated_date,
             victim.lock_user,
             victim.lock_date
)
SELECT rx_number AS victim_rx,
       order_num,
       item_seq,
       proc_inst_seq,
       node_seq,
       node_instance_seq,
       state_date,
       activated_date,
       lock_user,
       lock_date,
       first_pv2_arrival,
       later_pv2_rows
FROM suspicious
ORDER BY state_date DESC, rx_number;


-- ===========================================================================
-- Q3: Victim -> trigger pairs.
-- For each de-duplicated victim from Q2, find a sibling Rx on the same order
-- whose PV1 row completed within +/- 2 seconds of the victim arriving in PV2.
-- That sibling is the "trigger" item the user actually completed in PV1, and
-- whose Next Work Step click swept the victim along.
-- Expected: ~12 of the 13 victims will match (one is missed by the timing
-- window because of an earlier PV2 row from a prior pass).
-- lock_to_sweep_sec shows the time between the victim being locked and the
-- trigger being completed - typically 4 to 60 seconds.
-- ===========================================================================
WITH suspicious AS (
    SELECT victim.wf_process_definition_num,
           victim.proc_inst_seq,
           victim.node_seq,
           victim.node_instance_seq,
           rb.rx_number,
           wpi.order_num,
           wpi.item_seq,
           victim.state_date,
           victim.lock_date,
           victim.lock_user,
           MIN(pv2.state_date) AS first_pv2_arrival
    FROM trexone_data.wf_user_item victim
             JOIN trexone_data.wf_user_item pv2
                  ON pv2.wf_process_definition_num = victim.wf_process_definition_num
                      AND pv2.proc_inst_seq = victim.proc_inst_seq
                      AND pv2.wf_block_definition_num = 108300
                      AND pv2.node_seq > victim.node_seq
             JOIN trexone_data.wf_process_instance wpi
                  ON wpi.wf_process_definition_num = victim.wf_process_definition_num
                      AND wpi.proc_inst_seq = victim.proc_inst_seq
             JOIN trexone_data.item i
                  ON i.order_num = wpi.order_num
                      AND i.item_seq = wpi.item_seq
             JOIN trexone_data.rx_base rb
                  ON rb.rx_record_num = i.rx_record_num
    WHERE victim.wf_block_definition_num = 108100
      AND   victim.completion_date IS NULL
      AND   victim.node_state = 'ACTIVATED'
      AND   victim.state_date > ADD_MONTHS(SYSDATE, -8)
    GROUP BY victim.wf_process_definition_num,
             victim.proc_inst_seq,
             victim.node_seq,
             victim.node_instance_seq,
             rb.rx_number,
             wpi.order_num,
             wpi.item_seq,
             victim.state_date,
             victim.lock_date,
             victim.lock_user
)
SELECT s.rx_number AS victim_rx,
       rb_t.rx_number AS trigger_rx,
       s.order_num,
       s.state_date AS victim_pv1_state_date,
       s.lock_user  AS victim_lock_user,
       s.lock_date  AS victim_lock_date,
       s.first_pv2_arrival,
       trig.completion_date AS trigger_completed,
       trig.complete_user   AS trigger_user,
       ROUND((trig.completion_date - s.lock_date) * 24 * 3600, 1) AS lock_to_sweep_sec
FROM suspicious s
         JOIN trexone_data.item i_t
              ON i_t.order_num = s.order_num
                  AND i_t.item_seq <> s.item_seq
         JOIN trexone_data.rx_base rb_t
              ON rb_t.rx_record_num = i_t.rx_record_num
         JOIN trexone_data.wf_process_instance wpi_t
              ON wpi_t.order_num = i_t.order_num
                  AND wpi_t.item_seq = i_t.item_seq
         JOIN trexone_data.wf_user_item trig
              ON trig.wf_process_definition_num = wpi_t.wf_process_definition_num
                  AND trig.proc_inst_seq = wpi_t.proc_inst_seq
                  AND trig.wf_block_definition_num = 108100
                  AND trig.node_state = 'COMPLETED'
                  AND trig.completion_date IS NOT NULL
                  AND ABS(trig.completion_date - s.first_pv2_arrival) < 2/86400
ORDER BY s.state_date DESC, s.rx_number, trig.completion_date;

