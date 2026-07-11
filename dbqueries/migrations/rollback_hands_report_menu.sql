-- Rollback for add_hands_report_menu.sql
DELETE FROM role_menu_map WHERE menu_id IN (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/handsReport');
DELETE FROM menu_mst WHERE menu_path = 'hrms/handsReport';
