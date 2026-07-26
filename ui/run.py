"""
ui/run.py

Convenience entry point for the JARVIS desktop shell.

Usage:
    python -m ui.run
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from ui.app import JarvisApp

app = JarvisApp()
sys.exit(app.run())
