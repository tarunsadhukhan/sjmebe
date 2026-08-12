-- Migration: R-08-23 Bag Weight — record the full paper sheet
-- Module: juteSQC (bag_weight)
-- Date: 2026-08-08
--
-- The paper sheet header carries the nominal bag size (94 cm x 57 cm) and the customer
-- "Above N gm = X%" line; the per-bag rows carry length/width/ends/picks/stitch/remarks
-- alongside MR% + observed weight. Row-level fields ride inside the existing `readings`
-- JSON (widened to TEXT — 24 rows x 8 fields overflows VARCHAR(2000)).

ALTER TABLE jute_sqc_bag_weight
    MODIFY COLUMN readings TEXT NOT NULL,
    ADD COLUMN std_length_cm  DECIMAL(6,2) NULL AFTER bag_type_label,
    ADD COLUMN std_width_cm   DECIMAL(6,2) NULL AFTER std_length_cm,
    ADD COLUMN above_wt_gm    DECIMAL(8,2) NULL AFTER std_mr_pct,
    ADD COLUMN calc_above_pct DECIMAL(6,2) NULL AFTER calc_corr_hy_lt_pct;

-- Rollback:
-- ALTER TABLE jute_sqc_bag_weight
--     DROP COLUMN calc_above_pct,
--     DROP COLUMN above_wt_gm,
--     DROP COLUMN std_width_cm,
--     DROP COLUMN std_length_cm,
--     MODIFY COLUMN readings VARCHAR(2000) NOT NULL;
