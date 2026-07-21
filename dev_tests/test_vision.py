"""
dev_tests/test_vision.py

Tests for Vision & Screen Understanding: parser intents, planner builders,
registry registration, and vision module functions.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from brain.parser import Parser
from brain.planner import Planner
from brain.parsed_command import ParsedCommand


# =========================================================================
# Parser tests
# =========================================================================

class TestParserVision(unittest.TestCase):
    """Tests for vision/screen command parsing."""

    def setUp(self) -> None:
        self.parser = Parser()

    # --- read_screen ---
    def test_whats_on_my_screen(self) -> None:
        parsed = self.parser.parse("what's on my screen")
        self.assertEqual(parsed.intent, "read_screen")

    def test_what_is_on_my_screen(self) -> None:
        parsed = self.parser.parse("what is on my screen")
        self.assertEqual(parsed.intent, "read_screen")

    def test_read_screen(self) -> None:
        parsed = self.parser.parse("read screen")
        self.assertEqual(parsed.intent, "read_screen")

    def test_whats_on_screen_no_apostrophe(self) -> None:
        parsed = self.parser.parse("whats on my screen")
        self.assertEqual(parsed.intent, "read_screen")

    def test_read_the_screen(self) -> None:
        parsed = self.parser.parse("read the screen")
        self.assertEqual(parsed.intent, "read_screen")

    # --- describe_screen ---
    def test_describe_screen(self) -> None:
        parsed = self.parser.parse("describe screen")
        self.assertEqual(parsed.intent, "describe_screen")

    def test_describe_what_you_see(self) -> None:
        parsed = self.parser.parse("describe what you see")
        self.assertEqual(parsed.intent, "describe_screen")

    # --- click_element ---
    def test_click_element(self) -> None:
        parsed = self.parser.parse("click Login")
        self.assertEqual(parsed.intent, "click_element")
        self.assertEqual(parsed.entities.get("target"), "Login")

    def test_click_on_element(self) -> None:
        parsed = self.parser.parse("click on Save")
        self.assertEqual(parsed.intent, "click_element")
        self.assertEqual(parsed.entities.get("target"), "Save")

    def test_tap_element(self) -> None:
        parsed = self.parser.parse("tap Continue")
        self.assertEqual(parsed.intent, "click_element")

    def test_press_button(self) -> None:
        parsed = self.parser.parse("press OK")
        self.assertEqual(parsed.intent, "click_element")

    def test_click_multi_word(self) -> None:
        parsed = self.parser.parse("click Submit Form")
        self.assertEqual(parsed.intent, "click_element")
        self.assertEqual(parsed.entities.get("target"), "Submit Form")

    # --- find_element ---
    def test_find_the_save_button(self) -> None:
        parsed = self.parser.parse("find the Save button")
        self.assertEqual(parsed.intent, "find_element")
        self.assertIn("Save", parsed.entities.get("target", ""))

    def test_find_save_button_no_the(self) -> None:
        parsed = self.parser.parse("find Save button")
        self.assertEqual(parsed.intent, "find_element")

    def test_find_login_field(self) -> None:
        parsed = self.parser.parse("find login field")
        self.assertEqual(parsed.intent, "find_element")

    def test_find_submit_icon(self) -> None:
        parsed = self.parser.parse("find submit icon")
        self.assertEqual(parsed.intent, "find_element")

    def test_find_short_label(self) -> None:
        """Single short word — likely a button label."""
        parsed = self.parser.parse("find Login")
        self.assertEqual(parsed.intent, "find_element")

    def test_find_two_word_label(self) -> None:
        """Two short words — likely a button label."""
        parsed = self.parser.parse("find Save As")
        self.assertEqual(parsed.intent, "find_element")

    def test_find_save_button(self) -> None:
        parsed = self.parser.parse("find Save button")
        self.assertEqual(parsed.intent, "find_element")

    def test_locate_element(self) -> None:
        parsed = self.parser.parse("locate search bar")
        self.assertEqual(parsed.intent, "find_element")

    def test_where_is_login(self) -> None:
        parsed = self.parser.parse("where is the login button")
        self.assertEqual(parsed.intent, "find_element")

    # --- read_pdf ---
    def test_read_pdf(self) -> None:
        parsed = self.parser.parse("read pdf")
        self.assertEqual(parsed.intent, "read_pdf")

    def test_read_pdf_with_path(self) -> None:
        parsed = self.parser.parse("read pdf report.pdf")
        self.assertEqual(parsed.intent, "read_pdf")
        self.assertEqual(parsed.entities.get("file_path"), "report.pdf")

    def test_ocr_pdf(self) -> None:
        parsed = self.parser.parse("ocr pdf document.pdf")
        self.assertEqual(parsed.intent, "read_pdf")

    def test_read_this_pdf(self) -> None:
        parsed = self.parser.parse("read this pdf")
        self.assertEqual(parsed.intent, "read_pdf")

    # --- ocr_image ---
    def test_ocr_image(self) -> None:
        parsed = self.parser.parse("ocr image screenshot.png")
        self.assertEqual(parsed.intent, "ocr_image")
        self.assertEqual(parsed.entities.get("file_path"), "screenshot.png")

    def test_read_text_from_image(self) -> None:
        parsed = self.parser.parse("read text from image photo.jpg")
        self.assertEqual(parsed.intent, "ocr_image")

    def test_extract_text_from_image(self) -> None:
        parsed = self.parser.parse("extract text from image img.png")
        self.assertEqual(parsed.intent, "ocr_image")

    # --- read_error ---
    def test_read_error(self) -> None:
        parsed = self.parser.parse("read error")
        self.assertEqual(parsed.intent, "read_error")

    def test_read_error_message(self) -> None:
        parsed = self.parser.parse("read error message")
        self.assertEqual(parsed.intent, "read_error")

    def test_what_does_the_error_say(self) -> None:
        parsed = self.parser.parse("what does the error say")
        self.assertEqual(parsed.intent, "read_error")

    # --- fill_form ---
    def test_fill_form(self) -> None:
        parsed = self.parser.parse("fill form name with John")
        self.assertEqual(parsed.intent, "fill_form")
        self.assertEqual(parsed.entities.get("field"), "name")
        self.assertEqual(parsed.entities.get("value"), "John")

    def test_type_into_field(self) -> None:
        parsed = self.parser.parse("type into search hello")
        self.assertEqual(parsed.intent, "fill_form")

    def test_fill_field(self) -> None:
        parsed = self.parser.parse("fill field email")
        self.assertEqual(parsed.intent, "fill_form")
        self.assertEqual(parsed.entities.get("field"), "email")


# =========================================================================
# Planner tests
# =========================================================================

class TestPlannerVision(unittest.TestCase):
    """Tests for vision intent builders."""

    def setUp(self) -> None:
        self.planner = Planner()

    def _plan(self, intent: str, entities: dict = None) -> ParsedCommand:
        return ParsedCommand(raw_text="test", intent=intent, entities=entities or {})

    def test_read_screen_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("read_screen"))
        self.assertEqual(plan.steps[0].action, "read_screen")

    def test_describe_screen_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("describe_screen"))
        self.assertEqual(plan.steps[0].action, "describe_screen")

    def test_click_element_plan(self) -> None:
        plan = self.planner.create_plan(
            self._plan("click_element", {"target": "Login"})
        )
        self.assertEqual(plan.steps[0].action, "click_element")
        self.assertEqual(plan.steps[0].parameters["target"], "Login")

    def test_find_element_plan(self) -> None:
        plan = self.planner.create_plan(
            self._plan("find_element", {"target": "Save"})
        )
        self.assertEqual(plan.steps[0].action, "find_element")

    def test_read_pdf_plan(self) -> None:
        plan = self.planner.create_plan(
            self._plan("read_pdf", {"file_path": "report.pdf"})
        )
        self.assertEqual(plan.steps[0].action, "read_pdf")

    def test_ocr_image_plan(self) -> None:
        plan = self.planner.create_plan(
            self._plan("ocr_image", {"file_path": "img.png"})
        )
        self.assertEqual(plan.steps[0].action, "ocr_image")

    def test_read_error_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("read_error"))
        self.assertEqual(plan.steps[0].action, "read_error")

    def test_fill_form_plan(self) -> None:
        plan = self.planner.create_plan(
            self._plan("fill_form", {"field": "name", "value": "John"})
        )
        self.assertEqual(plan.steps[0].action, "fill_form")


# =========================================================================
# Registry tests
# =========================================================================

class TestRegistryVision(unittest.TestCase):
    """Verify all vision actions are registered."""

    def test_registry_has_vision_actions(self) -> None:
        from automation.registry import Registry
        reg = Registry()
        for action in (
            "read_screen",
            "describe_screen",
            "click_element",
            "find_element",
            "read_pdf",
            "ocr_image",
            "read_error",
            "fill_form",
        ):
            self.assertTrue(reg.is_registered(action), f"{action} not registered")


# =========================================================================
# vision module unit tests (no screen required)
# =========================================================================

class TestVisionModule(unittest.TestCase):
    """Tests for automation.vision module functions."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_capture_screen_returns_screencapture(self) -> None:
        from automation.vision import capture_screen
        sc = capture_screen()
        self.assertIsNotNone(sc.image)
        self.assertGreater(sc.image.size[0], 0)
        self.assertGreater(sc.image.size[1], 0)

    def test_read_screen_text_returns_dict(self) -> None:
        from automation.vision import read_screen_text
        result = read_screen_text()
        self.assertIn("success", result)
        self.assertIn("text", result)

    def test_find_text_on_screen_non_existent(self) -> None:
        from automation.vision import find_text_on_screen
        result = find_text_on_screen("XYZZYX_NONEXISTENT_12345")
        self.assertFalse(result["success"])

    def test_ocr_image_file_not_found(self) -> None:
        from automation.vision import ocr_image
        result = ocr_image("/nonexistent/image.png")
        self.assertFalse(result["success"])

    def test_read_pdf_file_not_found(self) -> None:
        from automation.vision import read_pdf
        result = read_pdf("/nonexistent/doc.pdf")
        self.assertFalse(result["success"])

    def test_describe_screen_returns_dict(self) -> None:
        from automation.vision import describe_screen
        result = describe_screen()
        self.assertIn("success", result)
        if result["success"]:
            self.assertIn("description", result)

    def test_read_error_dialog_returns_dict(self) -> None:
        from automation.vision import read_error_dialog
        result = read_error_dialog()
        self.assertIn("success", result)
        self.assertIn("text", result)

    def test_click_coordinates(self) -> None:
        from automation.vision import click_coordinates
        result = click_coordinates(100, 100)
        self.assertIn("success", result)

    def test_detect_buttons(self) -> None:
        from automation.vision import detect_buttons
        result = detect_buttons()
        self.assertIn("success", result)

    def test_detect_text_fields(self) -> None:
        from automation.vision import detect_text_fields
        result = detect_text_fields()
        self.assertIn("success", result)

    def test_text_region_properties(self) -> None:
        from automation.vision import TextRegion
        r = TextRegion(text="hello", x=10, y=20, w=100, h=30)
        self.assertEqual(r.center, (60, 35))
        self.assertEqual(r.area, 3000)

    def test_fill_form_field_no_match(self) -> None:
        from automation.vision import fill_form_field
        result = fill_form_field("NONEXISTENT_LABEL_12345", "test")
        self.assertFalse(result["success"])

    # --- PDF with actual text ---
    def test_read_text_pdf(self) -> None:
        """Create a minimal text PDF and read it."""
        pdf_path = os.path.join(self.tmp_dir, "test.pdf")
        self._create_text_pdf(pdf_path, "Hello PDF World")
        from automation.vision import read_pdf
        result = read_pdf(pdf_path)
        self.assertTrue(result["success"], msg=result.get("error", ""))
        self.assertIn("Hello PDF World", result["text"])

    def test_read_pdf_page_count(self) -> None:
        pdf_path = os.path.join(self.tmp_dir, "multi.pdf")
        self._create_text_pdf(pdf_path, "Page 1\n---\nPage 2", pages=2)
        from automation.vision import read_pdf
        result = read_pdf(pdf_path)
        self.assertTrue(result["success"])
        self.assertEqual(result["page_count"], 2)
        self.assertIn("Page 1", result["text"])

    # --- Image OCR ---
    def test_ocr_image_white_text_black_bg(self) -> None:
        from PIL import Image, ImageDraw, ImageFont
        img_path = os.path.join(self.tmp_dir, "test.png")
        img = Image.new("RGB", (400, 80), "black")
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        d.text((20, 20), "TestOCR", fill="white", font=font)
        img.save(img_path)

        from automation.vision import ocr_image
        result = ocr_image(img_path)
        self.assertTrue(result["success"], msg=result.get("error", ""))
        # OCR may miss a character — check partial match
        self.assertIn("Test", result["text"])

    @staticmethod
    def _create_text_pdf(path: str, text: str, pages: int = 1) -> None:
        """Create a simple text-based PDF using reportlab or raw."""
        try:
            from reportlab.pdfgen import canvas
            c = canvas.Canvas(path)
            for i in range(pages):
                c.drawString(50, 750, text)
                c.showPage()
            c.save()
        except ImportError:
            from automation.vision import read_pdf, pytesseract
            from PIL import Image, ImageDraw
            images = []
            for i in range(pages):
                img = Image.new("RGB", (612, 792), "white")
                d = ImageDraw.Draw(img)
                d.text((50, 50), text, fill="black")
                images.append(img)
            if pages == 1:
                images[0].save(path, "PDF", resolution=100)
            else:
                images[0].save(path, "PDF", resolution=100,
                               save_all=True, append_images=images[1:])


# =========================================================================
# Vision memory tests
# =========================================================================

class TestVisionMemory(unittest.TestCase):
    """Tests for memory/vision_memory.py."""

    def setUp(self) -> None:
        self._orig_file = None
        import memory.vision_memory as vm
        if vm._MEMORY_FILE.exists():
            self._orig_content = vm._MEMORY_FILE.read_text()

    def tearDown(self) -> None:
        import memory.vision_memory as vm
        if vm._MEMORY_FILE.exists():
            vm._MEMORY_FILE.unlink()

    def test_save_and_get_screen_text(self) -> None:
        from memory.vision_memory import save_screen_text, get_last_screen_text
        save_screen_text("Hello World", "1920x1080")
        self.assertEqual(get_last_screen_text(), "Hello World")

    def test_save_and_get_element(self) -> None:
        from memory.vision_memory import save_found_element, get_found_element
        save_found_element("Login", {"x": 100, "y": 200})
        el = get_found_element("Login")
        self.assertIsNotNone(el)
        self.assertEqual(el["x"], 100)

    def test_clear_elements(self) -> None:
        from memory.vision_memory import save_found_element, get_found_element, clear_found_elements
        save_found_element("Test", {"x": 0, "y": 0})
        clear_found_elements()
        self.assertIsNone(get_found_element("Test"))

    def test_save_and_get_dialog(self) -> None:
        from memory.vision_memory import save_dialog, get_last_dialog, get_recent_dialogs
        save_dialog("Error: access denied", is_error=True)
        last = get_last_dialog()
        self.assertIsNotNone(last)
        self.assertTrue(last["is_error"])
        self.assertIn("access denied", last["text"])

    def test_recent_dialogs_count(self) -> None:
        from memory.vision_memory import save_dialog, get_recent_dialogs
        for i in range(5):
            save_dialog(f"Dialog {i}")
        recent = get_recent_dialogs(count=3)
        self.assertEqual(len(recent), 3)

    def test_get_last_screen_empty_initially(self) -> None:
        from memory.vision_memory import get_last_screen_text
        text = get_last_screen_text()
        self.assertIsInstance(text, str)

    def test_get_nonexistent_element(self) -> None:
        from memory.vision_memory import get_found_element
        self.assertIsNone(get_found_element("NONEXISTENT"))


if __name__ == "__main__":
    unittest.main()
