-- Rollback for add_jute_rates_permission_menu.sql: removes the "Jute Rates"
-- permission menu and every role assignment of it. Rates become visible to all
-- users again only after the frontend gating is also reverted.

DELETE rmm FROM role_menu_map rmm
INNER JOIN menu_mst mm ON mm.menu_id = rmm.menu_id
WHERE mm.menu_path = 'jutePurchase/rates';

DELETE FROM menu_mst WHERE menu_path = 'jutePurchase/rates';
