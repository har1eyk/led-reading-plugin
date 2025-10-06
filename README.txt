### Overview
This plugin turns on a user‑selected LED (e.g., orange1 on channel B) at fixed intervals, waits ~200 ms to settle, 
rapidly samples a chosen photodiode channel for up to 3 s (targeting up to 12 samples), averages the samples, and 
logs the result to MQTT and a new SQLite table led_automation_readings. It dodges OD readings so it normally fires 
between IR OD bursts.
### 1) Install
pio plugins install led-reading-plugin --source /path/to/led-reading-plugin


### 2) Configure
Edit your config to include:

    [leds]
    A=IR
    B=orange1


    [od_config.photodiode_channel]
    1=180
    2=90


    [led_reading_plugin.config]
    frequency_hz=0.05
    settling_delay_ms=200
    sampling_window_s=3.0
    max_samples=12
    led_label=orange1
    led_channel=B
    led_intensity_percent=70
    pd_channel=1
    enable_dodging_od=1


    (Optional) add chart to Overview:
    [ui.overview.charts]
    led_reading=1

### 3) Run
pio run led_reading_plugin

### 4) Verify
pio db
SELECT COUNT(*) FROM led_automation_readings;

### Notes
- Table creation is done both by `additional_sql.sql` on plugin install and by the job at runtime via `_ensure_table()`—safe to run twice.
- The job writes directly to SQLite and also publishes a compact JSON payload to `pioreactor/<unit>/<experiment>/led_reading/<channel>`.


The job publishes JSON to:
pioreactor/<unit>/<experiment>/led_reading_plugin/led_reading
and the leader writes rows into the SQLite table `led_automation_readings`.


led-reading-plugin/
├─ led_reading_plugin/
│ ├─ __init__.py # plugin metadata + exports click entrypoint
│ ├─ led_reading.py # **your working job**, unmodified logic
│ ├─ additional_config.ini # defaults; merged into config on install
│ ├─ additional_sql.sql # creates led_automation_readings table + index
│ ├─ ui/
│ │ └─ contrib/
│ │ ├─ jobs/
│ │ │ └─ led_reading.yaml # shows job in Activities list
│ │ └─ charts/
│ │ └─ led_reading.yaml # optional chart for avg voltage
├─ LICENSE.txt
├─ MANIFEST.in
├─ README.md
└─ setup.py

pioreactor@leaderA1:~ $ pio plugins install led-reading-plugin --source /home/pioreactor/.pioreactor/plugins/led-reading-plugin/
2025-10-01T12:21:35-0400 DEBUG  [install_plugin] Installing plugin led-reading-plugin.
2025-10-01T12:21:35-0400 DEBUG  [install_plugin] bash /usr/local/bin/install_pioreactor_plugin.sh led-reading-plugin /home/pioreactor/.pioreactor/plugins/led-reading-plugin/
2025-10-01T12:21:43-0400 NOTICE [install_plugin] Successfully installed plugin led-reading-plugin.