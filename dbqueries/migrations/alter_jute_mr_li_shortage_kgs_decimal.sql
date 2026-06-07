-- Migration: Change jute_mr_li.shortage_kgs from INT to a decimal type
-- Reason: shortage_kgs is now carried to 2 decimal places (consistent with
--         actual_weight / accepted_weight) instead of being rounded to whole kg.
-- Target DB: tenant DB(s) (e.g. dev3)

ALTER TABLE jute_mr_li MODIFY COLUMN shortage_kgs DECIMAL(12, 2) NULL DEFAULT 0;

-- Rollback: ALTER TABLE jute_mr_li MODIFY COLUMN shortage_kgs INT NULL DEFAULT 0;
