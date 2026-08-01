-- Migration: Add unique index on frame_details_mst.mc_id
-- One frame_details row per machine (app already enforces this in frame_create /
-- frame_edit duplicate checks); also serves the mc_id joins in the list query and
-- spinning efficiency reports. NULL mc_id rows are still allowed (MySQL unique
-- indexes permit multiple NULLs).
-- NOTE: fails if duplicate mc_id rows already exist -- find them with:
--   SELECT mc_id, COUNT(*) FROM frame_details_mst WHERE mc_id IS NOT NULL GROUP BY mc_id HAVING COUNT(*) > 1;
-- Rollback: ALTER TABLE frame_details_mst DROP INDEX uq_fdm_mc_id;

ALTER TABLE frame_details_mst ADD UNIQUE INDEX uq_fdm_mc_id (mc_id);
