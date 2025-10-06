# -*- coding: utf-8 -*-
"""Pioreactor plugin: led_reading_plugin
Publishes averaged LED/PD readings to MQTT and stores them in SQLite.
"""
from __future__ import annotations


import json
from typing import Any, Dict


# ---- Plugin metadata shown on the Plugins page (follow Pioreactor style)
__plugin_name__ = "led_reading_plugin"
__plugin_version__ = "0.1.4"
__plugin_summary__ = (
    "Uses a non-IR LED + a photodiode to take periodic measurements; averages N"
    " samples in a short burst and stores the result."
)
__plugin_author__ = "Harley King"
# __plugin_homepage__ = "https://github.com/yourname/led-reading-plugin"
__plugin_license__ = "MIT"

# Import the module that defines @run.command("led_reading")
from . import led_reading  # side-effect import to register `pio run led_reading`

# ---- Wire MQTT → SQLite so values land in led_automation_readings
try:
    from pioreactor.background_jobs.leader.mqtt_to_db_streaming import (
    register_source_to_sink,
    TopicToParserToTable,
    produce_metadata,
    )
    from pioreactor.utils import timing


    def _parser(topic: str, payload: str) -> Dict[str, Any]:
        """Parse JSON payload from this plugin into a DB row dict.
        Expected payload shape: {"led_reading": float, "angle": int, "channel": int}
        """
        meta = produce_metadata(topic)
        data = json.loads(payload)
        return {
            "experiment": meta.experiment,
            "pioreactor_unit": meta.pioreactor_unit,
            "timestamp": timing.current_utc_timestamp(),
            "led_reading": float(data["led_reading"]),
            "angle": int(data["angle"]),
            "channel": int(data["channel"]),
        }


        # Subscribe leader to ALL units/experiments that emit this plugin topic
    register_source_to_sink(
        TopicToParserToTable(
            ["pioreactor/+/+/led_reading_plugin/led_reading"],
            _parser,
            "led_automation_readings",
        )
    )
except Exception:
        # Safe to ignore on workers / during dev when leader-only module isn't present.
    pass


# Import click entrypoint so `pio plugins install` can locate it
from .led_reading import click_led_reading_plugin # noqa: E402,F401