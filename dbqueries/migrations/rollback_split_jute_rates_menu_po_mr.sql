-- Rollback for split_jute_rates_menu_po_mr.sql: removes the MR rates menu (and its
-- role assignments) and renames the PO rates menu back to the single "Jute Rates".
-- Only meaningful together with reverting the frontend to the unscoped hook.

DELETE rmm FROM role_menu_map rmm
INNER JOIN menu_mst mm ON mm.menu_id = rmm.menu_id
WHERE mm.menu_path = 'jutePurchase/mrRates';

DELETE FROM menu_mst WHERE menu_path = 'jutePurchase/mrRates';

UPDATE menu_mst
SET menu_name = 'Jute Rates', menu_path = 'jutePurchase/rates'
WHERE menu_path = 'jutePurchase/poRates';
