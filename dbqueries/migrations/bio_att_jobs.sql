-- BioAtt background-job status table.
-- Apply per tenant DB (e.g. sjm). Idempotent.
--
-- Rollback: DROP TABLE IF EXISTS bio_att_jobs;

CREATE TABLE IF NOT EXISTS bio_att_jobs (
    job_id      VARCHAR(64) PRIMARY KEY,
    status      VARCHAR(20) NOT NULL,
    total       INT         NOT NULL DEFAULT 0,
    processed   INT         NOT NULL DEFAULT 0,
    inserted    INT         NOT NULL DEFAULT 0,
    duplicates  INT         NOT NULL DEFAULT 0,
    invalid     INT         NOT NULL DEFAULT 0,
    message     VARCHAR(255),
    error       TEXT,
    created_at  DATETIME    DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Recommended index for the bulk-dedup LEFT JOIN in the worker.
-- Speeds up `LEFT JOIN bio_attendance_table b ON b.emp_code = t.emp_code AND b.log_date = t.log_date ...`.
CREATE INDEX IF NOT EXISTS idx_bio_attendance_emp_logdate
    ON bio_attendance_table (emp_code, log_date);
