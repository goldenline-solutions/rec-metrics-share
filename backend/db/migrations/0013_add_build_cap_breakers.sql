-- Migration 13: Store selected cap breakers for planner-created builds (SQLite).
-- JSON object of { attributeKey: tierCount }, e.g. {"ShotThree": 3, "DrivingDunk": 5}

ALTER TABLE builds ADD COLUMN cap_breakers TEXT;
