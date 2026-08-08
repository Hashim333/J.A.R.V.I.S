"""
intelligence/ — the world-state-aware layer of JARVIS.

- ``world_state``  : continuously-updated view of the computer (apps,
  browser windows/tabs/URL, clipboard, mouse, dialogs, confirmations).
- ``intelligent_planner`` : plans that consult the world state, bake in
  verification, and never claim success without evidence.
"""
