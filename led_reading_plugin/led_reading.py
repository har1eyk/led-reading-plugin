#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Periodic LED-driven reading for a visible/fluorescent channel with verbose prints.

- Uses a user-named LED (e.g., 'orange1' mapped to channel B)
- Reads PD channel 1 (PD585) at a configured cadence
- Turns LED on -> settles -> rapid samples -> averages -> turns LED off
- Inserts average into SQLite table `led_automation_readings`
- Publishes a compact MQTT message
- Prints helpful progress messages to stdout for debugging/observability

Pioreactor version noted by user: 25.8.14
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from time import sleep, time
from typing import Optional, cast
from datetime import datetime

import click
from pioreactor.background_jobs.base import BackgroundJob
from pioreactor import types as pt
from pioreactor import exc, hardware, whoami
from pioreactor.config import config
from pioreactor.pubsub import publish
from pioreactor.utils.timing import RepeatedTimer, current_utc_datetime
import pioreactor.actions.led_intensity as led_utils
import json

# === Hard-wired DB path (matches core location) ===
DB_PATH = "/home/pioreactor/.pioreactor/storage/pioreactor.sqlite"


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%fZ")


def _ensure_table() -> None:
    print(f"[{_now()}] Ensuring table/index exist in DB: {DB_PATH}", flush=True)
    ddl_1 = """
    CREATE TABLE IF NOT EXISTS led_automation_readings (
        experiment TEXT NOT NULL,
        pioreactor_unit TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        led_reading REAL NOT NULL,
        angle INTEGER NOT NULL,
        channel INTEGER NOT NULL CHECK (channel IN (1, 2)),
        FOREIGN KEY (experiment) REFERENCES experiments(experiment) ON DELETE CASCADE
    );
    """
    ddl_2 = """
    CREATE INDEX IF NOT EXISTS led_automation_readings_ix
    ON led_automation_readings (experiment, pioreactor_unit, timestamp);
    """
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(ddl_1)
        conn.execute(ddl_2)


class SimpleADC:
    """Minimal wrapper around the Pioreactor ADC for one PD channel."""

    def __init__(self, channel: str, dynamic_gain: bool = True) -> None:
        from pioreactor import hardware
        from pioreactor import exc
        # IMPORTANT: use the installed ADC driver (ADS1115 / Pico / ADS1114) via a unified class
        from pioreactor.utils.adcs import ADC as ADCDriver

        self.channel = channel
        self.dynamic_gain = dynamic_gain

        # Debug: show what's available on pioreactor.hardware
        print(f"[{_now()}] ADC_CHANNEL_FUNCS keys: {list(getattr(hardware, 'ADC_CHANNEL_FUNCS', {}).keys())}")

        try:
            # Use the selector integer (0..3) for this PD channel
            self.selector = hardware.ADC_CHANNEL_FUNCS[str(self.channel)]
            print(f"[{_now()}] Using selector for pd{self.channel}: {self.selector!r}")

            # Instantiate the driver with NO arguments (per 25.8.14)
            print(f"[{_now()}] Selected ADC driver class: {ADCDriver.__name__}")
            self.adc = ADCDriver()
            print(f"[{_now()}] Created ADC instance: {self.adc!r}")
            print(f"[{_now()}] ADC instance has methods: "
                  f"{[m for m in dir(self.adc) if not m.startswith('_')][:40]}")

        except KeyError as e:
            print(f"[{_now()}] ERROR: No selector for pd{self.channel} in ADC_CHANNEL_FUNCS")
            raise exc.HardwareNotFoundError(f"ADC selector for pd{self.channel} not found.") from e
        except Exception as e:
            # Last-chance log with available attributes to aid debugging
            attrs = [a for a in dir(hardware) if a.isupper() or a.startswith("Adc")]
            print(f"[{_now()}] ERROR: ADC init failed. hardware ADC-like attrs: {attrs}")
            raise exc.HardwareNotFoundError(
                f"Failed to initialize ADC for pd{self.channel}. Is the HAT attached and powered?"
            ) from e

        # Optional: set initial gain if supported (ADS1115), Pico_ADC ignores this (no attr)
        if hasattr(self.adc, "set_ads_gain"):
            try:
                self.adc.set_ads_gain(1.0)
                print(f"[{_now()}] ADC gain set to 1.0")
            except Exception as e:
                print(f"[{_now()}] WARNING: set_ads_gain failed: {e}")

    def read_voltage(self) -> float:
        # Always pass the selector (channel index) to the driver
        raw = self.adc.read_from_channel(self.selector)
        if hasattr(self.adc, "from_raw_to_voltage"):
            v = self.adc.from_raw_to_voltage(raw)
        else:
            v = raw
        return float(v)

    # Provide these shims because LEDReader calls them.
    def check_on_gain(self, value_v: float) -> None:
        if self.dynamic_gain and hasattr(self.adc, "check_on_gain"):
            try:
                self.adc.check_on_gain(value_v)
            except Exception as e:
                print(f"[{_now()}] WARNING: check_on_gain failed: {e}")

    def from_voltage_to_raw_precise(self, v: float) -> float:
        if hasattr(self.adc, "from_voltage_to_raw_precise"):
            return float(self.adc.from_voltage_to_raw_precise(v))
        return v

    def from_raw_to_voltage(self, r: float) -> float:
        if hasattr(self.adc, "from_raw_to_voltage"):
            return float(self.adc.from_raw_to_voltage(r))
        return r


class LEDReader(BackgroundJob):
    """LED-driven periodic reading (visible / fluorescence-like)."""

    job_name = "led_reading"

    published_settings = {
        "interval": {"datatype": "float", "settable": True, "unit": "s"},
        "led_intensity": {"datatype": "float", "settable": False, "unit": "%"},
        "led_channel": {"datatype": "string", "settable": False},
        "last_burst_avg": {"datatype": "float", "settable": False, "unit": "V"},
        "angle": {"datatype": "integer", "settable": False},
    }

    def __init__(
        self,
        unit: pt.Unit,
        experiment: pt.Experiment,
        interval: float,
        pd_channel: pt.PdChannel = "1",
        led_name: str = "orange1",
        led_channel: Optional[pt.LedChannel] = None,
        led_intensity_percent: Optional[float] = None,
        settle_ms: int = 200,
        burst_seconds: float = 3.0,
        target_samples: int = 12,
        fake_data: bool = False,
    ) -> None:
        super().__init__(unit=unit, experiment=experiment)

        print(f"[{_now()}] === LEDReader init ===", flush=True)
        print(f"[{_now()}] Unit={unit}, Experiment={experiment}", flush=True)

        if not hardware.is_HAT_present():
            print(f"[{_now()}] ERROR: Pioreactor HAT not present.", flush=True)
            self.clean_up()
            raise exc.HardwareNotFoundError("Pioreactor HAT must be present.")

        # Resolve LED channel from name via [leds_reverse]
        if led_channel is None:
            try:
                resolved = cast(pt.LedChannel, config.get("leds_reverse", led_name))
            except Exception as e:
                print(
                    f"[{_now()}] ERROR: Could not resolve LED channel for '{led_name}'. "
                    f"Ensure [leds] contains a mapping like B={led_name}. ({e})",
                    flush=True,
                )
                self.clean_up()
                raise
            led_channel = resolved

        # Intensity %
        if led_intensity_percent is None:
            led_intensity_percent = config.getfloat(
                "led_reading.config", f"led_{led_channel}_intensity", fallback=70.0
            )

        self.interval = float(interval)
        self.led_channel = led_channel
        self.led_intensity = float(led_intensity_percent)
        self.settle_ms = int(settle_ms)
        self.burst_seconds = float(burst_seconds)
        self.target_samples = int(target_samples)
        self.fake_data = fake_data

        # Angle from od_config.photodiode_channel.1 (e.g., "180")
        angle_str = config.get("od_config.photodiode_channel", "1", fallback=None)
        if angle_str is None:
            print(
                f"[{_now()}] ERROR: Missing [od_config.photodiode_channel] 1=ANGLE (e.g., 180).",
                flush=True,
            )
            self.clean_up()
            raise ValueError("Angle for PD channel 1 is required in config.")
        try:
            self.angle = int(angle_str)
        except Exception:
            print(f"[{_now()}] ERROR: Angle for PD1 must be integer. Got: {angle_str}", flush=True)
            self.clean_up()
            raise

        # Summarize configuration
        print(
            f"[{_now()}] Config: interval={self.interval}s, settle={self.settle_ms} ms, "
            f"burst={self.burst_seconds}s, target_samples={self.target_samples}",
            flush=True,
        )
        print(
            f"[{_now()}] LED: name='{led_name}', channel={self.led_channel}, intensity={self.led_intensity}%",
            flush=True,
        )
        print(f"[{_now()}] PD channel=1 (PD585), angle={self.angle}", flush=True)
        print(f"[{_now()}] SQLite DB: {DB_PATH}", flush=True)

        # Ensure table exists up-front
        _ensure_table()

        # ADC for PD1
        self.adc = SimpleADC(pd_channel, dynamic_gain=not fake_data)

        # Start periodic runner (immediate first run)
        print(f"[{_now()}] Starting periodic bursts (first run immediately)...", flush=True)
        self.record_timer = RepeatedTimer(
            self.interval, self._burst_cycle, job_name=self.job_name, run_immediately=True, logger=self.logger
        ).start()

        print(f"[{_now()}] led_reading is running.", flush=True)

    # --- lifecycle hooks ---

    def on_sleeping(self) -> None:
        print(f"[{_now()}] Job sleeping: pausing bursts.", flush=True)
        self.record_timer.pause()

    def on_sleeping_to_ready(self) -> None:
        print(f"[{_now()}] Job ready: resuming bursts.", flush=True)
        self.record_timer.unpause()

    def on_disconnected(self) -> None:
        print(f"[{_now()}] Job disconnecting: stopping timer and LED.", flush=True)
        try:
            self.record_timer.cancel()
        except Exception:
            pass
        try:
            self._stop_led()
        except Exception:
            pass

    # --- helpers for LED context mgmt ---
    def _stop_led(self) -> None:
        try:
            led_utils.led_intensity({self.led_channel: 0.0}, unit=self.unit, experiment=self.experiment,
                                    pubsub_client=self.pub_client, source_of_event=self.job_name)
        except Exception:
            pass

    # --- main cycle ---
    def _burst_cycle(self) -> None:
        """
        One full cycle:
        - lock LED channel
        - LED on → settle → rapid ADC samples → average → LED off
        - write to DB + publish MQTT
        """
        print(f"[{_now()}] --- Burst start ---", flush=True)
        samples: list[float] = []
        try:
            with led_utils.change_leds_intensities_temporarily(
                {self.led_channel: self.led_intensity},
                unit=self.unit,
                experiment=self.experiment,
                source_of_event=self.job_name,
                pubsub_client=self.pub_client,
                verbose=False,
            ):
                settle_s = max(0.0, self.settle_ms / 1000.0)
                print(f"... Settling for {settle_s:.3f} s ...", flush=True)
                sleep(settle_s)

                t0 = time()
                target_dt = max(0.02, self.burst_seconds / self.target_samples) if self.target_samples > 1 else 0.05
                print(
                    f"[{_now()}] Sampling up to {self.burst_seconds:.2f}s "
                    f"(aim {self.target_samples} samples, ~{target_dt:.3f}s cadence)",
                    flush=True,
                )

                while (time() - t0) < self.burst_seconds and len(samples) < self.target_samples:
                    v = self.adc.read_voltage()
                    samples.append(v)
                    sleep(target_dt)
        except Exception as e:
            print(f"[{_now()}] ERROR during sampling: {e}", flush=True)

        # compute average
        if samples:
            avg_v = sum(samples) / len(samples)
            mn = min(samples)
            mx = max(samples)
        else:
            avg_v = 0.0
            mn = mx = 0.0

        self.last_burst_avg = float(avg_v)
        print(
            f"[{_now()}] Samples collected: {len(samples)}  "
            f"min={mn:.4f}V  max={mx:.4f}V  avg={avg_v:.4f}V",
            flush=True,
        )

        # persist → SQLite
        ts = current_utc_datetime()
        try:
            with closing(sqlite3.connect(DB_PATH)) as conn, conn:
                conn.execute(
                    "INSERT INTO led_automation_readings "
                    "(experiment, pioreactor_unit, timestamp, led_reading, angle, channel) "
                    "VALUES (?, ?, ?, ?, ?, ?);",
                    (
                        self.experiment,
                        self.unit,
                        ts,
                        float(avg_v),
                        int(self.angle),
                        2 if self.led_channel == "B" else (1 if self.led_channel == "A" else 2),
                    ),
                )
            print(
                f"[{_now()}] DB insert OK → led_automation_readings "
                f"(ts={ts}, avg={avg_v:.6f}, angle={self.angle}, chan={'2' if self.led_channel=='B' else '1'})",
                flush=True,
            )
        except Exception as e:
            print(f"[{_now()}] ERROR: Failed to write to DB: {e}", flush=True)

        # publish compact MQTT payload (optional)
        try:
            payload = json.dumps(
                {
                    "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "avg_voltage": float(avg_v),
                    "angle": int(self.angle),
                    "channel": self.led_channel,
                    "intensity_percent": self.led_intensity,
                    "n_samples": len(samples),
                }
            )
            publish(
                f"pioreactor/{self.unit}/{self.experiment}/led_reading/{self.led_channel}",
                payload,
            )
            print(f"[{_now()}] MQTT published on led_reading/{self.led_channel}", flush=True)
        except Exception as e:
            print(f"[{_now()}] MQTT publish failed (non-fatal): {e}", flush=True)
            print(f"[{_now()}] --- Burst end ---", flush=True)

    # allow changing interval at runtime if desired
    def set_interval(self, interval: float) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive.")
        print(f"[{_now()}] Changing interval to {interval}s", flush=True)
        self.interval = interval
        self.record_timer.interval = interval


def start_led_reading(
    interval: Optional[float] = None,
    fake_data: bool = False,
    unit: Optional[pt.Unit] = None,
    experiment: Optional[pt.Experiment] = None,
    led_name: Optional[str] = None,
    led_channel: Optional[pt.LedChannel] = None,
    led_intensity_percent: Optional[float] = None,
) -> LEDReader:
    """Convenience bootstrapper."""
    unit = unit or whoami.get_unit_name()
    experiment = experiment or whoami.get_assigned_experiment_name(unit)

    # interval default from config
    if interval is None:
        sps = config.getfloat("led_reading.config", "samples_per_second", fallback=0.05)  # 1/20s
        interval = 1.0 / sps if sps > 0 else 20.0

    settle_ms = config.getint("led_reading.config", "settle_ms", fallback=200)
    burst_seconds = config.getfloat("led_reading.config", "burst_seconds", fallback=3.0)
    target_samples = config.getint("led_reading.config", "target_samples", fallback=12)
    led_name = led_name or config.get("led_reading.config", "led_name", fallback="orange1")

    print(
        f"[{_now()}] start_led_reading(): interval={interval}s, settle_ms={settle_ms}, "
        f"burst_seconds={burst_seconds}, target_samples={target_samples}, led_name={led_name}",
        flush=True,
    )

    return LEDReader(
        unit=unit,
        experiment=experiment,
        interval=float(interval),
        pd_channel="1",
        led_name=led_name,
        led_channel=led_channel,
        led_intensity_percent=led_intensity_percent,
        settle_ms=settle_ms,
        burst_seconds=burst_seconds,
        target_samples=target_samples,
        fake_data=fake_data or whoami.is_testing_env(),
    )

# led_reading_plugin/led_reading.py
# import click
from pioreactor.cli.run import run   

@run.command("led_reading")          # <-- not @click.command
@click.option("--interval", type=click.FLOAT, default=None, show_default=True,
              help="seconds between bursts (default from [led_reading.config].samples_per_second)")
@click.option("--fake-data", is_flag=True, help="produce fake data (for testing)")
@click.option("--led-name", type=click.STRING, default=None, show_default=True,
              help="name as defined in [leds]/[leds_reverse] (e.g., orange1)")
@click.option("--led-intensity", type=click.FLOAT, default=None, show_default=True,
              help="override LED intensity percent for this run (otherwise from config)")
def led_reading(interval, fake_data, led_name, led_intensity):
    # Call your existing start function
    from .led_reading import start_led_reading  # if start_led_reading is in this same file, this import is optional
    with start_led_reading(
        interval=interval,
        fake_data=fake_data,
        led_name=led_name,
        led_intensity_percent=led_intensity,
    ) as job:
        job.block_until_disconnected()
# --- compatibility for loaders expecting a `click_...` symbol ---
# This simply points the old expected name to the actual @run.command function.
click_led_reading_plugin = led_reading

if __name__ == "__main__":
    print(f"[{_now()}] Starting led_reading CLI...", flush=True)
    try:
        led_reading()
    except Exception as e:
        print(f"[{_now()}] FATAL: {e}", flush=True)
        raise
