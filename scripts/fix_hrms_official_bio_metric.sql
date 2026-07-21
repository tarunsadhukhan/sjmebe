-- Fix 500 on /hrms/employee_section_save (section=official):
-- model HrmsEdOfficialDetails maps bio_metric_id (added in commit a90c545) but the
-- sjm DB table never got the column, so every ORM INSERT/UPDATE fails with 1054.
-- Also relax minimum_working_commitment: optional in the UI, so NULL must be allowed.
ALTER TABLE hrms_ed_official_details ADD COLUMN bio_metric_id INT NULL AFTER office_email_id;
ALTER TABLE hrms_ed_official_details MODIFY minimum_working_commitment INT NULL;
