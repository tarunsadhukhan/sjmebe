-- Adds the "Jute Rates" permission menu that controls per-user visibility/editability
-- of Rate fields on Jute PO and Jute MR pages (frontend hook useJuteRatePermission).
-- Path jutePurchase/rates, under the Jute Procurement group (menu_parent_id 1).
-- access_type_id >= 1 (view) = rates visible; = 4 (edit) = rates editable.
-- Users whose roles do NOT have this menu see no rate fields at all.
-- Grants edit access to role 15 (superadmin) only; assign to other roles via Role Management.
-- Run both statements on the SAME connection so LAST_INSERT_ID() resolves to the new menu.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, module_mst_id, order_by)
VALUES ('Jute Rates', 'jutePurchase/rates', 1, 1, 2, 1, NULL);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (15, LAST_INSERT_ID(), 4, 1, NOW());
