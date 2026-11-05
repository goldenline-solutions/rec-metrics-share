-- Migration 13 (PostgreSQL): Store selected cap breakers for planner-created builds.
-- JSON object of { attributeKey: tierCount }, e.g. {"ShotThree": 3, "DrivingDunk": 5}

ALTER TABLE builds ADD COLUMN IF NOT EXISTS cap_breakers TEXT;
