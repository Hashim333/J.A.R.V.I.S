import os
import re
import unittest

BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
RIGHT_PANEL_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "RightPanel.qml")
BOTTOM_CARDS_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "BottomCards.qml")
AI_CORE_STATES_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "AiCoreStates.qml")
SYSTEM_CARDS_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "SystemCards.qml")
DASHBOARD_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "Dashboard.qml")
PARTICLE_BG_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "ParticleBackground.qml")
CONVERSATION_QML = os.path.join(BASE, "ui", "qml", "v4_deprecated", "Conversation.qml")
BRIDGE_PY = os.path.join(BASE, "ui", "bridge.py")


class TestUiGaps(unittest.TestCase):
    """Verify the UI gap fixes: 4-mode cards, system overview, particles."""

    def test_ai_core_states_component_exists(self):
        self.assertTrue(
            os.path.isfile(AI_CORE_STATES_QML),
            f"AiCoreStates.qml not found at {AI_CORE_STATES_QML}",
        )

    def test_ai_core_states_has_four_modes(self):
        with open(AI_CORE_STATES_QML) as f:
            content = f.read()
        mode_ids = re.findall(r'id:\s*"(\w+)"', content)
        self.assertEqual(
            mode_ids,
            ["idle", "listening", "thinking", "speaking"],
            f"AiCoreStates.qml should define exactly 4 modes, got {mode_ids}",
        )

    def test_ai_core_states_has_exact_descriptions(self):
        with open(AI_CORE_STATES_QML) as f:
            content = f.read()
        descs = re.findall(r'desc:\s*"([^"]+)"', content)
        self.assertEqual(descs, [
            "Calm, breathing glow",
            "Expands, blue particles",
            "Faster rotation, data pulses",
            "Waveform & energy ripple",
        ], f"AiCoreStates.qml descriptions mismatch, got {descs}")

    def test_right_panel_uses_ai_core_states(self):
        with open(RIGHT_PANEL_QML) as f:
            content = f.read()
        self.assertIn("AiCoreStates", content)
        self.assertIn("AI CORE STATES", content)
        self.assertNotIn("CORE STATE", content.replace("AI CORE STATES", ""))

    def test_bottom_cards_has_reference_feature_chips(self):
        with open(BOTTOM_CARDS_QML) as f:
            content = f.read()
        expected = [
            "ADAPTIVE UI",
            "REAL-TIME VOICE MATCH",
            "SMOOTH 60 FPS",
            "NO CLUTTER",
            "PREMIUM & FUTURISTIC",
        ]
        for label in expected:
            self.assertIn(label, content, f"Feature chip {label!r} not found in BottomCards.qml")

    def test_bottom_cards_no_old_chips(self):
        with open(BOTTOM_CARDS_QML) as f:
            content = f.read()
        old = ["ALWAYS ACCESSIBLE", "CHROME", "VS CODE", "FLOATING ORB", "TASKBAR"]
        for label in old:
            self.assertNotIn(label, content, f"Old chip {label!r} should have been replaced")

    def test_bottom_cards_has_subtexts(self):
        with open(BOTTOM_CARDS_QML) as f:
            content = f.read()
        self.assertIn("Orange (AI)", content, "Card subtext missing 'Orange (AI)' in BottomCards.qml")
        self.assertIn("Blue (You)", content, "Card subtext missing 'Blue (You)' in BottomCards.qml")
        self.assertIn("Particles react to your voice", content)
        self.assertIn("GPU Accelerated", content)
        self.assertIn("Focus on what matters", content)
        self.assertIn("Next-Gen AI Experience", content)

    def test_quick_status_adjusted_for_ai_core_states(self):
        with open(RIGHT_PANEL_QML) as f:
            content = f.read()
        self.assertIn("aiCoreStates.bottom", content, "QUICK STATUS should anchor to aiCoreStates.bottom")
        m = re.search(r"topMargin:\s*(\d+)", content.split("QUICK STATUS")[1].split("StatusCard")[0])
        self.assertIsNotNone(m, "Could not find topMargin below QUICK STATUS label")
        self.assertLessEqual(int(m.group(1)), 30, "Relative topMargin should be small (dynamically positioned)")

    def test_card_width_larger(self):
        with open(BOTTOM_CARDS_QML) as f:
            content = f.read()
        m = re.search(r"width:\s*(\d+)", content)
        self.assertIsNotNone(m, "Could not find card width")
        self.assertGreaterEqual(int(m.group(1)), 120, "Card width should be >= 120 for longer labels")

    # ── SystemCards ──

    def test_system_cards_exists(self):
        self.assertTrue(
            os.path.isfile(SYSTEM_CARDS_QML),
            f"SystemCards.qml not found at {SYSTEM_CARDS_QML}",
        )

    def test_system_cards_has_cpu_mem_gpu_bars(self):
        with open(SYSTEM_CARDS_QML) as f:
            content = f.read()
        for label in ("CPU", "MEM", "GPU"):
            self.assertIn(label, content, f"SystemCards should contain {label} bar")

    def test_system_cards_has_perf_graph(self):
        with open(SYSTEM_CARDS_QML) as f:
            content = f.read()
        self.assertIn("graphCanvas", content, "SystemCards should have a performance graph canvas")
        self.assertIn("cpuUsage", content, "SystemCards should reference cpuUsage")
        self.assertIn("ramUsage", content, "SystemCards should reference ramUsage")

    def test_dashboard_wires_system_cards(self):
        with open(DASHBOARD_QML) as f:
            content = f.read()
        self.assertIn("SystemCards", content, "Dashboard.qml should import SystemCards")
        self.assertIn("systemCards", content, "Dashboard.qml should instantiate SystemCards")
        self.assertIn("cpuUsage: root.cpuUsage", content, "SystemCards cpuUsage should be wired")
        self.assertIn("ramUsage: root.ramUsage", content, "SystemCards ramUsage should be wired")
        self.assertIn("gpuUsage: root.gpuUsage", content, "SystemCards gpuUsage should be wired")

    def test_dashboard_wires_quassistant_status_bars(self):
        with open(DASHBOARD_QML) as f:
            content = f.read()
        self.assertIn("onCpuUsageChanged", content, "Dashboard needs onCpuUsageChanged bridge handler")
        self.assertIn("onRamUsageChanged", content, "Dashboard needs onRamUsageChanged bridge handler")
        self.assertIn("onGpuUsageChanged", content, "Dashboard needs onGpuUsageChanged bridge handler")

    def test_conversation_qml_uses_list_view(self):
        with open(CONVERSATION_QML) as f:
            content = f.read()
        self.assertIn("ListView", content, "Conversation.qml should use ListView")
        self.assertIn("conversationHistory", content, "Conversation.qml should reference conversationHistory")
        self.assertIn("modelData", content, "Conversation.qml should use modelData in delegates")

    def test_dashboard_conversation_fills_vertical(self):
        with open(DASHBOARD_QML) as f:
            content = f.read()
        self.assertIn("anchors.bottom: parent.bottom", content,
                      "Dashboard Conversation should anchor to bottom")
        self.assertNotIn("subtitleText: root.subtitleText", content,
                         "Dashboard Conversation should NOT bind subtitleText (reads bridge directly)")

    # ── ParticleBackground ──

    def test_particle_idle_alpha_boosted(self):
        with open(PARTICLE_BG_QML) as f:
            content = f.read()
        self.assertIn("0.15 + 0.25", content, "Idle alpha should be 0.15 + 0.25 * (...)")
        self.assertIn("p.layer === 0) alpha *= 0.6", content, "Layer 0 multiplier should be 0.6 (was 0.3)")
        self.assertIn("p.layer === 1) alpha *= 0.75", content, "Layer 1 multiplier should be 0.75 (was 0.65)")


    # ── Bridge Stats Timer ──

    def test_bridge_has_stats_timer(self):
        with open(BRIDGE_PY) as f:
            content = f.read()
        self.assertIn("_stats_timer", content, "Bridge must have _stats_timer QTimer")
        self.assertIn("_sample_stats", content, "Bridge must have _sample_stats method")
        self.assertIn("psutil.cpu_percent", content, "_sample_stats must call psutil.cpu_percent")
        self.assertIn("psutil.virtual_memory", content, "_sample_stats must call psutil.virtual_memory")
        self.assertIn("_read_gpu_percent", content, "Bridge must have _read_gpu_percent helper")
        self.assertIn("engtype_3D", content, "Bridge must have WMI GPU fallback via engtype_3D")
        self.assertIn("import wmi", content, "Bridge must import wmi for GPU fallback")
        self.assertIn("conversationHistoryChanged", content, "Bridge must emit conversationHistoryChanged")
        self.assertIn("add_conversation_entry", content, "Bridge must have add_conversation_entry Slot")
        self.assertIn("_conversation_history", content, "Bridge must track _conversation_history list")

    def test_bridge_stats_timer_interval(self):
        with open(BRIDGE_PY) as f:
            content = f.read()
        m = re.search(r"_stats_timer\.start\((\d+)\)", content)
        self.assertIsNotNone(m, "Could not find _stats_timer.start(...)")
        interval = int(m.group(1))
        self.assertGreaterEqual(interval, 1000, "Stats timer should fire at least every 1s")
        self.assertLessEqual(interval, 3000, "Stats timer should fire at most every 3s")

    def test_bridge_emits_initial_stats(self):
        with open(BRIDGE_PY) as f:
            content = f.read()
        self.assertIn("_sample_stats(skip_gpu=True)", content, "Bridge __init__ should call _sample_stats immediately")


if __name__ == "__main__":
    unittest.main()
