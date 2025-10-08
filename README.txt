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

experiment                pioreactor_unit  timestamp                 led_reading         angle  channel  pd_channel
------------------------  ---------------  ------------------------  ------------------  -----  -------  ----------
LED890_reinstalledPlugin  leaderA1         2025-10-08T16:38:43.574Z  0.0665611645299146  -1     2        1
LED890_reinstalledPlugin  leaderA1         2025-10-08T16:38:43.574Z  1.17922619047619    135    2        2
LED890_reinstalledPlugin  leaderA1         2025-10-08T16:37:49.468Z  0.0666954746642247  -1     2        1
LED890_reinstalledPlugin  leaderA1         2025-10-08T16:37:49.468Z  0.856583867521367   135    2        2
LED890_reinstalledPlugin  leaderA1         2025-10-08T16:37:29.476Z  0.0666451083638584  -1     2        1

Both the values from the reference (REF) photodiode and the other photodiode are captured. REF PD is usually at position 1 (PD1), and the other PD is at position 2 (PD2). 
In the above sqlite3 query, angle = -1 is REF. "Channel = 2" referes to the LED at position "B" or "2". 

### Notes
- Table creation is done both by `additional_sql.sql` on plugin install and by the job at runtime via `_ensure_table()`—safe to run twice.
- The job writes directly to SQLite and also publishes a compact JSON payload to `pioreactor/<unit>/<experiment>/led_reading/<channel>`.


The job publishes JSON to:
pioreactor/<unit>/<experiment>/led_reading_plugin/led_reading
and the leader writes rows into the SQLite table `led_automation_readings`.

### Files
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

### Output
When `pio run led_reading` is entered, the output looks like below. PD readings from both PDs are outputted every 20s (0.05) or so. 
```pioreactor@leaderA1:~/.pioreactor $ pio run led_reading
[2025-10-08 16:38:40.214155Z] start_led_reading(): interval=20.0s, settle_ms=200, burst_seconds=3.0, target_samples=12, led_name=IR890, pd_channels=['1', '2']
2025-10-08T12:38:40-0400 DEBUG  [led_reading] Init.
[2025-10-08 16:38:40.250787Z] === LEDReader init ===
[2025-10-08 16:38:40.250940Z] Unit=leaderA1, Experiment=LED890_reinstalledPlugin
[2025-10-08 16:38:40.261573Z] Using PD1 as reference photodiode (angle sentinel -1).
[2025-10-08 16:38:40.264067Z] Config: interval=20.0s, settle=200 ms, burst=3.0s, target_samples=12
[2025-10-08 16:38:40.264268Z] LED: name='IR890', channel=B, intensity=100.0%
[2025-10-08 16:38:40.264355Z] PD channels -> PD1=angle:REF, PD2=angle:135
[2025-10-08 16:38:40.264417Z] SQLite DB: /home/pioreactor/.pioreactor/storage/pioreactor.sqlite
[2025-10-08 16:38:40.264476Z] Ensuring table/index exist in DB: /home/pioreactor/.pioreactor/storage/pioreactor.sqlite
[2025-10-08 16:38:40.289733Z] ADC_CHANNEL_FUNCS keys: ['1', '2', 'version', 'aux']
[2025-10-08 16:38:40.289902Z] Using selector for pd1: 2
[2025-10-08 16:38:40.289970Z] Selected ADC driver class: Pico_ADC
[2025-10-08 16:38:40.314638Z] Created ADC instance: <pioreactor.utils.adcs.Pico_ADC object at 0xf693d770>
[2025-10-08 16:38:40.314784Z] ADC instance has methods: ['check_on_gain', 'from_raw_to_voltage', 'from_voltage_to_raw', 'from_voltage_to_raw_precise', 'gain', 'get_firmware_version', 'i2c', 'read_from_channel', 'scale']
[2025-10-08 16:38:40.314990Z] ADC_CHANNEL_FUNCS keys: ['1', '2', 'version', 'aux']
[2025-10-08 16:38:40.315070Z] Using selector for pd2: 3
[2025-10-08 16:38:40.315163Z] Selected ADC driver class: Pico_ADC
[2025-10-08 16:38:40.316049Z] Created ADC instance: <pioreactor.utils.adcs.Pico_ADC object at 0xf57f18b0>
[2025-10-08 16:38:40.316142Z] ADC instance has methods: ['check_on_gain', 'from_raw_to_voltage', 'from_voltage_to_raw', 'from_voltage_to_raw_precise', 'gain', 'get_firmware_version', 'i2c', 'read_from_channel', 'scale']
[2025-10-08 16:38:40.319393Z] Starting periodic bursts (first run immediately)...
[2025-10-08 16:38:40.320101Z] --- Burst start ---
[2025-10-08 16:38:40.320223Z] led_reading is running.
2025-10-08T12:38:40-0400 INFO   [led_reading] Ready.
2025-10-08T12:38:40-0400 DEBUG  [led_reading] led_reading is blocking until disconnected.
... Settling for 0.200 s ...
[2025-10-08 16:38:40.540354Z] Sampling up to 3.00s (aim 12 samples, ~0.250s cadence)
[2025-10-08 16:38:43.574476Z] Samples collected -> PD1: samples=12 min=0.0661V max=0.0669V avg=0.0666V; PD2: samples=12 min=1.1654V max=1.1972V avg=1.1792V
[2025-10-08 16:38:43.586599Z] DB insert OK -> led_automation_readings (ts=2025-10-08 16:38:43.574000+00:00, PD1:avg=0.066561 angle=REF, PD2:avg=1.179226 angle=135)
[2025-10-08 16:38:44.590679Z] MQTT published on led_reading/B
```

