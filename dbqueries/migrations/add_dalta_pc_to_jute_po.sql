-- Add dalta_pc column to jute_po.
-- dalta_pc stores the "Less (%)" deduction percentage entered on the Jute PO header.
ALTER TABLE jute_po ADD COLUMN dalta_pc DOUBLE NULL AFTER brokrage_percentage;

-- Rollback: ALTER TABLE jute_po DROP COLUMN dalta_pc;
