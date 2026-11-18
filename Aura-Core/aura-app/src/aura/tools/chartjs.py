# aura/tools/chartjs.py
"""
Chart.js tools for Aura.
Generates chart configurations that render as interactive pop-up charts in the chat interface.

Each tool follows the pattern:
- TOOL_DEFINITION: JSON Schema
- run(arguments: Dict[str, Any]) -> str
"""

import json
import base64
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


TOOL_DEFINITION = {
    "name": "generate_chart",
    "description": (
        "Generate an interactive Chart.js chart that renders in the chat UI. "
        "Supports bar, line, pie, doughnut, radar, polarArea, bubble, and scatter charts. "
        "Use this whenever the user asks for a visualization, graph, chart, or data plot."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "description": "Type of chart: bar, line, pie, doughnut, radar, polarArea, bubble, scatter",
                "enum": ["bar", "line", "pie", "doughnut", "radar", "polarArea", "bubble", "scatter"]
            },
            "title": {
                "type": "string",
                "description": "Chart title displayed at the top"
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "X-axis labels (or segment labels for pie/doughnut)"
            },
            "datasets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Dataset legend label"
                        },
                        "data": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Numeric data points for this dataset"
                        },
                        "backgroundColor": {
                            "description": "Color(s) for the data. Can be a single string or array.",
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}}
                            ]
                        },
                        "borderColor": {
                            "description": "Border color(s). Can be a single string or array.",
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}}
                            ]
                        },
                        "borderWidth": {
                            "type": "number",
                            "description": "Border width in pixels",
                            "default": 1
                        },
                        "fill": {
                            "type": "boolean",
                            "description": "Fill area under line chart"
                        },
                        "tension": {
                            "type": "number",
                            "description": "Line tension (0 = straight, 0.4 = smooth curves)",
                            "minimum": 0,
                            "maximum": 1
                        }
                    },
                    "required": ["label", "data"]
                },
                "description": "One or more dataset objects"
            },
            "options": {
                "type": "object",
                "description": "Additional Chart.js options (scales, plugins, etc.). Applied on top of sensible defaults."
            }
        },
        "required": ["chart_type", "labels", "datasets"]
    }
}


async def run(arguments: Dict[str, Any]) -> str:
    """Generate a chart configuration for frontend rendering.

    Handles both canonical and LLM-friendly argument shapes:
    - chart_type  OR  type           ->  "bar", "line", "pie", etc.
    - datasets    OR  data (flat)    ->  [{label, data}, ...]
    - backgroundColor / borderColor at top level gets folded into datasets
    """
    # ---- 1. Resolve chart type -------------------------------------------
    chart_type = arguments.get("chart_type") or arguments.get("type")
    if not chart_type:
        return json.dumps({"error": "Missing 'chart_type' (or 'type') argument"})

    title = arguments.get("title", "Chart")
    labels = arguments.get("labels", [])
    # Handle nested data.labels (LLM sometimes wraps everything in a "data" key)
    if not labels and isinstance(arguments.get("data"), dict):
        labels = arguments["data"].get("labels", [])
    if not labels:
        return json.dumps({"error": "Missing 'labels' argument"})

    # ---- 2. Resolve datasets (canonical OR flat shorthand OR nested) ----
    datasets: list = arguments.get("datasets", [])
    # Handle nested data.datasets
    if not datasets and isinstance(arguments.get("data"), dict):
        datasets = arguments["data"].get("datasets", [])

    # LLM shorthand: top-level "data" flat array -> single anonymous dataset
    if not datasets and "data" in arguments:
        flat_data = arguments["data"]
        if isinstance(flat_data, list) and flat_data and isinstance(flat_data[0], (int, float)):
            ds: Dict[str, Any] = {"label": title, "data": flat_data}
            # Carry over top-level color/style props into the dataset
            for key in ("backgroundColor", "borderColor", "borderWidth", "fill", "tension"):
                if key in arguments:
                    ds[key] = arguments[key]
            datasets = [ds]

    if not datasets:
        return json.dumps({"error": "Missing 'datasets' (or 'data') argument"})

    # ---- 3. Auto-generate sensible default colors when none are provided --
    default_colors = [
        "rgba(59, 130, 246, 0.7)",   # blue
        "rgba(239, 68, 68, 0.7)",    # red
        "rgba(34, 197, 94, 0.7)",    # green
        "rgba(245, 158, 11, 0.7)",   # amber
        "rgba(168, 85, 247, 0.7)",   # purple
        "rgba(236, 72, 153, 0.7)",   # pink
        "rgba(20, 184, 166, 0.7)",   # teal
        "rgba(251, 146, 60, 0.7)",   # orange
    ]
    border_colors = [c.replace("0.7", "1") for c in default_colors]

    for i, ds in enumerate(datasets):
        if "backgroundColor" not in ds:
            if chart_type in ("pie", "doughnut", "polarArea"):
                ds["backgroundColor"] = default_colors[:len(labels)]
            else:
                ds["backgroundColor"] = default_colors[i % len(default_colors)]
        if "borderColor" not in ds:
            if chart_type in ("pie", "doughnut", "polarArea"):
                ds["borderColor"] = border_colors[:len(labels)]
            else:
                ds["borderColor"] = border_colors[i % len(border_colors)]
        if "borderWidth" not in ds:
            ds["borderWidth"] = 1

    # ---- 4. Merge user options with responsive defaults ------------------
    merged_options = {
        "responsive": True,
        "maintainAspectRatio": True,
        "plugins": {
            "title": {
                "display": bool(title),
                "text": title,
                "color": "rgba(255, 255, 255, 0.85)",
                "font": {"size": 18, "weight": "bold"}
            },
            "legend": {
                "position": "top",
                "labels": {"color": "rgba(255, 255, 255, 0.7)"}
            }
        },
        "scales": _default_scales(chart_type)
    }

    options = arguments.get("options", {})
    if options:
        if "plugins" in options:
            user_plugins = options.pop("plugins", {})
            merged_options["plugins"].update(user_plugins)
        merged_options.update(options)

    # ---- 5. Build final chart config and encode --------------------------
    chart_config = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": datasets
        },
        "options": merged_options
    }

    # Base64-encode to avoid markdown-parsing edge cases
    config_json = json.dumps(chart_config, ensure_ascii=False)
    encoded = base64.b64encode(config_json.encode("utf-8")).decode("utf-8")

    logger.info(f"Chart generated: {chart_type} '{title}' ({len(labels)} labels, {len(datasets)} datasets)")

    return f"[CHARTJS:{encoded}]"


def _default_scales(chart_type: str) -> dict:
    """Return sensible scale defaults for the given chart type."""
    if chart_type in ("pie", "doughnut", "polarArea", "radar"):
        return {}  # No cartesian scales for radial charts

    return {
        "x": {
            "ticks": {"color": "rgba(255, 255, 255, 0.6)"},
            "grid": {"color": "rgba(255, 255, 255, 0.06)"}
        },
        "y": {
            "ticks": {"color": "rgba(255, 255, 255, 0.6)"},
            "grid": {"color": "rgba(255, 255, 255, 0.06)"},
            "beginAtZero": True
        }
    }
