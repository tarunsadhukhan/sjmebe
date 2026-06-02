-- Add broker_id column to jute_po.
-- broker_id references party_mst.party_id and stores the broker (a party) selected
-- on the Jute PO header, shown as the "Broker Name" dropdown after "Party Name".
ALTER TABLE jute_po ADD COLUMN broker_id INT NULL AFTER party_id;

-- Rollback: ALTER TABLE jute_po DROP COLUMN broker_id;
