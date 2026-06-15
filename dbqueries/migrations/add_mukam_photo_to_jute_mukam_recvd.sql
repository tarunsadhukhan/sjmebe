-- Add a column to store the captured photo as an HTML <img> snippet
-- (base64 data URI). LONGTEXT because base64-encoded images are large.
-- Photo is capture-once: written on insert, never updated.
ALTER TABLE jute_mukam_recvd ADD COLUMN mukam_photo LONGTEXT NULL;
