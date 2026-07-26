"""
ui/config.py

UI configuration — all visual parameters are tunable from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UIConfig:
    # ── Performance ───────────────────────────────────────────────────
    target_fps: int = 60
    particle_count: int = 800
    max_particle_count: int = 3000

    # ── Animation ─────────────────────────────────────────────────────
    animation_speed: float = 1.0
    spring_stiffness: float = 180.0
    spring_damping: float = 12.0

    # ── Transparency ──────────────────────────────────────────────────
    background_opacity: float = 0.92
    orb_opacity: float = 0.85
    blur_radius: int = 16

    # ── Window ────────────────────────────────────────────────────────
    orb_size: int = 90
    orb_expanded_size: int = 130
    dock_width: int = 48
    dock_expanded_width: int = 280
    sidebar_width: int = 320

    # ── Theme ─────────────────────────────────────────────────────────
    theme_name: str = "amber"
    glow_intensity: float = 1.0


# Singleton
ui_config: UIConfig = UIConfig()