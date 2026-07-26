"""
ui/themes/amber.py

Default amber/orange theme — JARVIS signature look.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeColors:
    name: str = "Amber"
    background: str = "#0a0a0a"
    surface: str = "#14100a"
    surface_light: str = "#1e1810"

    primary: str = "#ff7b00"
    primary_light: str = "#ff9500"
    primary_dark: str = "#cc5500"

    accent: str = "#ffd700"
    accent_alt: str = "#ffaa00"

    text_primary: str = "#ffffff"
    text_secondary: str = "#aaaaaa"
    text_muted: str = "#666666"

    success: str = "#00ff88"
    warning: str = "#ffaa00"
    error: str = "#ff3355"
    info: str = "#33aaff"

    particle_idle: str = "#ff7b00"
    particle_listening: str = "#33aaff"
    particle_thinking: str = "#ffd700"
    particle_speaking: str = "#ff7b00"
    particle_error: str = "#ff3355"
    particle_offline: str = "#666666"

    core_idle: str = "#ff7b00"
    core_listening: str = "#33aaff"
    core_thinking: str = "#ffd700"
    core_speaking: str = "#ff7b00"
    core_error: str = "#ff3355"
    core_offline: str = "#444444"

    glow_idle: str = "1, 0.48, 0"
    glow_listening: str = "0.2, 0.67, 1"
    glow_thinking: str = "1, 0.84, 0"
    glow_speaking: str = "1, 0.48, 0"
    glow_error: str = "1, 0.2, 0.33"
    glow_offline: str = "0.4, 0.4, 0.4"


AMBER_THEME = ThemeColors()


def get_theme(name: str = "amber") -> ThemeColors:
    themes = {"amber": AMBER_THEME}
    return themes.get(name, AMBER_THEME)
