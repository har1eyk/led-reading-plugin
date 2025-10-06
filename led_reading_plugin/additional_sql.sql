-- 1) Main table
CREATE TABLE IF NOT EXISTS led_automation_readings (
experiment TEXT NOT NULL,
pioreactor_unit TEXT NOT NULL,
timestamp TEXT NOT NULL,
led_reading REAL NOT NULL,
angle INTEGER NOT NULL,
channel INTEGER NOT NULL CHECK (channel IN (1, 2)),
FOREIGN KEY (experiment) REFERENCES experiments(experiment) ON DELETE CASCADE
);


-- 2) Index tuned for export/overview scans
CREATE INDEX IF NOT EXISTS led_automation_readings_ix
ON led_automation_readings (experiment, pioreactor_unit, timestamp);