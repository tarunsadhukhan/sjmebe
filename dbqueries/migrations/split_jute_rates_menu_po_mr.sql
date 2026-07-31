-- Splits the single "Jute Rates" permission menu (add_jute_rates_permission_menu.sql,
-- already applied) into two independent permissions so PO and MR rate visibility can
-- be granted separately (frontend hook useJuteRatePermission("po" | "mr")):
--   'jutePurchase/poRates' -> Rate fields on Jute Purchase Order pages
--   'jutePurchase/mrRates' -> Rate / Claim Rate fields on Jute MR pages
-- The existing menu row is repurposed as the PO permission, KEEPING its role grants.
-- The new MR menu copies the same role grants so current access is unchanged;
-- adjust per role afterwards via Role Management.
-- Run all statements on the SAME connection so LAST_INSERT_ID() resolves correctly.

UPDATE menu_mst
SET menu_name = 'Jute PO Rates', menu_path = 'jutePurchase/poRates'
WHERE menu_path = 'jutePurchase/rates';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, module_mst_id, order_by)
VALUES ('Jute MR Rates', 'jutePurchase/mrRates', 1, 1, 2, 1, NULL);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT rmm.role_id, LAST_INSERT_ID(), rmm.access_type_id, 1, NOW()
FROM role_menu_map rmm
INNER JOIN menu_mst mm ON mm.menu_id = rmm.menu_id
WHERE mm.menu_path = 'jutePurchase/poRates';
