-- Adds the "Hands Report" portal menu (sidebar) mirroring "Daily Man Machine" (menu_id 769),
-- under the HRMS group (menu_parent_id 741), and grants it to the same role (role_id 15)
-- that has Daily Man Machine. Route: /dashboardportal/hrms/handsReport.
-- Run both statements on the SAME connection so LAST_INSERT_ID() resolves to the new menu.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, module_mst_id, order_by)
VALUES ('Hands Report', 'hrms/handsReport', 1, 741, 2, 1, 2);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (15, LAST_INSERT_ID(), 4, 21, NOW());
