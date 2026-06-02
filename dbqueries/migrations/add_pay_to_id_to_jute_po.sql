-- Add pay_to_id column to jute_po.
-- pay_to_id references party_mst.party_id and stores the "Pay To" party selected
-- on the Jute PO header, shown as the "Pay To" dropdown after "Broker Name".
ALTER TABLE jute_po ADD COLUMN pay_to_id INT NULL AFTER broker_id;

-- Rollback: ALTER TABLE jute_po DROP COLUMN pay_to_id;
