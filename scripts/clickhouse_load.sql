-- BACKLOT: loads data/studio_dataset/*.json into a real ClickHouse cluster,
-- as tables the Budget/Resource agents query directly with SQL when
-- MCP_MODE=clickhouse (see backlot/agents/_state_instructions.py's
-- clickhouse_sql_rule and backlot/agents/budget.py / resource.py). Queried
-- at runtime via the real, official ClickHouse MCP server
-- (github.com/ClickHouse/mcp-clickhouse)'s run_query/list_tables tools.
--
-- Run this ONCE, by hand, against your ClickHouse Cloud (or self-hosted)
-- cluster -- e.g. paste it into the ClickHouse Cloud SQL console, or pipe
-- it through `clickhouse-client --host ... --secure --password ... --multiquery
-- < scripts/clickhouse_load.sql`. This script is NOT executed by BACKLOT
-- itself and needs no Python/MCP dependency to run.
--
-- Before running:
--   1. The database name below is "backlot_studio", matching
--      CLICKHOUSE_DATABASE's default in .env.example/backlot/config.py. If
--      you want a different name, change every reference below AND set
--      CLICKHOUSE_DATABASE to match in .env.
--   2. After loading, set in .env (see .env.example):
--        MCP_MODE=clickhouse
--        CLICKHOUSE_DATABASE=backlot_studio   (or whatever you chose)
--        CLICKHOUSE_MCP_URL=<your mcp-clickhouse server's streamable-http URL>
--        CLICKHOUSE_MCP_AUTH_TOKEN=<if the server has auth enabled>
--     so the agents' SQL targets the same database this script loaded data
--     into. The cluster connection itself (CLICKHOUSE_HOST/PORT/USER/
--     PASSWORD) is configured on whoever runs the mcp-clickhouse server,
--     not read by backlot directly -- see .env.example's comments.
--
-- The rows below are the exact same synthetic data as
-- data/studio_dataset/*.json (see each file's own "_disclaimer" field) --
-- this script just gets them into real tables so the Budget/Resource
-- agents can run real SELECTs (via the MCP server's run_query tool)
-- instead of mcp_shim's in-process fuzzy matcher. Re-running this script
-- is safe for the CREATE statements (IF NOT EXISTS) but will duplicate
-- rows if the INSERTs are re-run against tables that already have data --
-- TRUNCATE first (or DROP DATABASE + re-run this whole file) if you need
-- to reload.

CREATE DATABASE IF NOT EXISTS backlot_studio;

-- ---------------------------------------------------------------------
-- historical_costs  (source: data/studio_dataset/historical_costs.json)
-- Queried by the Budget Agent to ground per-shoot-day cost line items.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backlot_studio.historical_costs
(
    scene_profile     String,
    description       String,
    avg_cost_per_day  Float64,
    sample_size       UInt32,
    comparable_titles Array(String)
)
ENGINE = MergeTree
ORDER BY (scene_profile);

INSERT INTO backlot_studio.historical_costs
    (scene_profile, description, avg_cost_per_day, sample_size, comparable_titles)
VALUES
    ('EXT_NIGHT_INDUSTRIAL', 'Night exterior, industrial/lot setting, minimal cast, practical lighting rig', 38500, 6, ['Low Tide (2023)', 'Backlot Nine (2024)', 'Quiet Freight (2024)']),
    ('INT_CONTINUOUS_VEHICLE', 'Interior vehicle (process trailer or insert car), 2-3 cast, night continuity', 27200, 9, ['Backlot Nine (2024)', 'Redline (2022)', 'Two Lane (2025)']),
    ('EXT_NIGHT_LOADING_DOCK', 'Night exterior, single-location dock/warehouse exterior, small cast, minor stunts', 41800, 5, ['Quiet Freight (2024)', 'Night Shift (2023)']),
    ('EXT_NIGHT_HIGHWAY_VEHICLE', 'Night exterior highway/road work, moving vehicle unit, weather element (rain)', 61200, 4, ['Two Lane (2025)', 'Redline (2022)']),
    ('INT_DAY_GARAGE_WORKSHOP', 'Day interior, practical location (garage/workshop), 3 cast, standard lighting', 22400, 7, ['Backlot Nine (2024)', 'Cash Value (2023)']),
    ('INT_DAY_STANDARD', 'Day interior, standard dressed set, dialogue-driven scene', 18900, 12, ['Cash Value (2023)', 'Low Tide (2023)', 'Night Shift (2023)']);

-- ---------------------------------------------------------------------
-- vendor_rates  (source: data/studio_dataset/vendor_rates.json)
-- Queried by the Budget Agent to ground per-vendor rate line items.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backlot_studio.vendor_rates
(
    category String,
    region   String,
    rate     Float64,
    vendor   String
)
ENGINE = MergeTree
ORDER BY (category, region);

INSERT INTO backlot_studio.vendor_rates
    (category, region, rate, vendor)
VALUES
    ('grip_and_electric_package', 'US-West', 4200, 'Lot 12 Grip & Electric'),
    ('grip_and_electric_package', 'US-East', 3900, 'Harborline Lighting Co.'),
    ('camera_package_pro', 'US-West', 5800, 'Backlot Camera Rentals'),
    ('camera_package_pro', 'US-East', 5400, 'Eastline Cine Rentals'),
    ('picture_vehicle_cargo_van', 'US-West', 650, 'Studio Fleet Services'),
    ('picture_vehicle_cargo_van', 'US-East', 600, 'Coastal Picture Cars'),
    ('security_night_shoot', 'US-West', 1200, 'Perimeter Watch Security'),
    ('security_night_shoot', 'US-East', 1100, 'Harborline Security'),
    ('catering_full_crew', 'US-West', 3100, 'Craft & Call Catering'),
    ('catering_full_crew', 'US-East', 2900, 'Eastline Craft Services'),
    ('rain_effects_unit', 'US-West', 4800, 'Weathermaker FX'),
    ('rain_effects_unit', 'US-East', 4500, 'Coastal Weather FX');

-- ---------------------------------------------------------------------
-- crew_library  (source: data/studio_dataset/crew_library.json)
-- Queried by the Resource Agent to ground crew picks.
-- `union` is back-quoted throughout -- it's a ClickHouse keyword.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backlot_studio.crew_library
(
    crew_id        String,
    name           String,
    role           String,
    region         String,
    day_rate       Float64,
    `union`        String,
    available_from Date,
    available_to   Date
)
ENGINE = MergeTree
ORDER BY (crew_id);

INSERT INTO backlot_studio.crew_library
    (crew_id, name, role, region, day_rate, `union`, available_from, available_to)
VALUES
    ('CR-101', 'J. Alvarez', 'Gaffer', 'US-West', 950, 'IATSE Local 728', '2026-08-01', '2026-10-31'),
    ('CR-102', 'K. Okafor', 'Key Grip', 'US-West', 900, 'IATSE Local 80', '2026-08-01', '2026-09-30'),
    ('CR-103', 'R. Chen', '1st AC', 'US-West', 750, 'IATSE Local 600', '2026-07-15', '2026-11-30'),
    ('CR-104', 'T. Boone', 'Sound Mixer', 'US-West', 800, 'IATSE Local 695', '2026-08-10', '2026-10-15'),
    ('CR-105', 'M. Farrow', 'Location Manager', 'US-West', 700, 'non-union', '2026-07-28', '2026-12-31'),
    ('CR-106', 'D. Whitlock', 'Stunt Coordinator', 'US-West', 1400, 'SAG-AFTRA', '2026-08-15', '2026-09-15'),
    ('CR-107', 'P. Nakashima', '1st AD', 'US-West', 1100, 'DGA', '2026-08-01', '2026-10-31'),
    ('CR-108', 'S. Delacroix', 'Gaffer', 'US-East', 880, 'IATSE Local 52', '2026-08-01', '2026-11-15'),
    ('CR-109', 'A. Novak', 'Key Grip', 'US-East', 850, 'IATSE Local 52', '2026-08-01', '2026-10-01'),
    ('CR-110', 'L. Ibarra', 'Location Manager', 'US-East', 680, 'non-union', '2026-07-28', '2026-12-31');

-- ---------------------------------------------------------------------
-- location_library  (source: data/studio_dataset/location_library.json)
-- Queried by the Resource Agent to ground location picks.
-- `type` is back-quoted throughout -- treat it as a keyword defensively.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backlot_studio.location_library
(
    location_id           String,
    name                  String,
    `type`                String,
    region                String,
    permit_cost_per_day   Float64,
    supports_night_shoot  Bool,
    power_access          Bool,
    available_from        Date,
    available_to          Date,
    notes                 Nullable(String)
)
ENGINE = MergeTree
ORDER BY (location_id);

INSERT INTO backlot_studio.location_library
    (location_id, name, `type`, region, permit_cost_per_day, supports_night_shoot, power_access, available_from, available_to, notes)
VALUES
    ('LOC-01', 'Fernwood Industrial Lot', 'industrial_lot', 'US-West', 2200, true, true, '2026-08-01', '2026-11-30', NULL),
    ('LOC-02', 'Pier 9 Loading Dock', 'warehouse_dock', 'US-West', 2600, true, true, '2026-08-01', '2026-10-15', NULL),
    ('LOC-03', 'Route 14 Overpass Stretch', 'highway_stretch', 'US-West', 5200, true, false, '2026-08-15', '2026-09-30', 'Requires county traffic control permit, 14-day lead time.'),
    ('LOC-04', 'Delgado''s Auto Garage', 'auto_garage', 'US-West', 1400, false, true, '2026-07-28', '2026-12-31', NULL),
    ('LOC-05', 'Harborline Freight Yard', 'industrial_lot', 'US-East', 1900, true, true, '2026-08-01', '2026-11-01', NULL),
    ('LOC-06', 'Cutter Street Dock 4', 'warehouse_dock', 'US-East', 2300, true, true, '2026-08-01', '2026-10-31', NULL);

-- ---------------------------------------------------------------------
-- past_schedules  (source: data/studio_dataset/past_schedules.json)
-- Not queried by any agent yet today (mcp_shim's get_past_schedule_patterns
-- tool isn't wired to a client either -- see mcp_shim/server.py) -- loaded
-- here for parity so ClickHouse mirrors the full studio_dataset and is
-- ready if/when the Scheduler's fixed pages-per-day default is grounded in
-- past-schedule priors.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backlot_studio.past_schedules
(
    genre             String,
    scale             String,
    avg_pages_per_day Float64,
    avg_shoot_days    UInt32,
    sample_size       UInt32,
    notes             Nullable(String)
)
ENGINE = MergeTree
ORDER BY (genre, scale);

INSERT INTO backlot_studio.past_schedules
    (genre, scale, avg_pages_per_day, avg_shoot_days, sample_size, notes)
VALUES
    ('heist_thriller', 'short_film', 4.5, 4, 5, 'Night-heavy schedules reduce pages/day vs. day interiors.'),
    ('heist_thriller', 'feature', 3.2, 28, 8, NULL),
    ('drama', 'short_film', 6.0, 3, 9, NULL),
    ('drama', 'feature', 4.1, 24, 11, NULL),
    ('action', 'feature', 2.4, 42, 6, 'Vehicle and stunt units lower average pages/day.');

-- Sanity check after loading -- expect 6, 12, 10, 6, 5 rows respectively:
SELECT 'historical_costs' AS table, count() AS rows FROM backlot_studio.historical_costs
UNION ALL SELECT 'vendor_rates', count() FROM backlot_studio.vendor_rates
UNION ALL SELECT 'crew_library', count() FROM backlot_studio.crew_library
UNION ALL SELECT 'location_library', count() FROM backlot_studio.location_library
UNION ALL SELECT 'past_schedules', count() FROM backlot_studio.past_schedules;
