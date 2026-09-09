-- Loads data/studio_dataset/*.json into ClickHouse as the tables the Budget
-- and Resource agents query over MCP when MCP_MODE=clickhouse. The rows are
-- the same synthetic dataset the JSON files carry.
--
-- Run once by hand against your cluster: paste into the ClickHouse Cloud SQL
-- console, or pipe it through clickhouse-client with --multiquery. BACKLOT
-- never executes this itself.
--
-- The database name is backlot_studio, matching CLICKHOUSE_DATABASE in
-- .env.example. Change both together if you use another name.
--
-- Safe to re-run: each table is truncated before it is loaded.

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

TRUNCATE TABLE IF EXISTS backlot_studio.historical_costs;

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

TRUNCATE TABLE IF EXISTS backlot_studio.vendor_rates;

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

TRUNCATE TABLE IF EXISTS backlot_studio.crew_library;

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

TRUNCATE TABLE IF EXISTS backlot_studio.location_library;

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

TRUNCATE TABLE IF EXISTS backlot_studio.past_schedules;

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
