"""
brain/brain.py

Brain is the single entry point and coordinator of the full pipeline:

    Brain.process(text)
        -> Parser.parse(text)            -> ParsedCommand
        -> Planner.create_plan(parsed)   -> ExecutionPlan
        -> Executor.execute(plan)        -> Response

Brain() takes no constructor arguments. It builds Parser, Planner,
LLM, Registry, and Executor internally, and registers AppsHandler,
MouseHandler, and KeyboardHandler against the Registry using plain
string action names -- no StepKind, no automation.step, no enum of
any kind. No dependency injection: callers never construct or pass in
any of Brain's internals.

Brain never touches automation directly and never bypasses Executor.
Once an ExecutionPlan exists, the only thing Brain does with it is
hand it to Executor.execute(plan) and return whatever Response comes
back.
"""

from __future__ import annotations

from brain.parser import Parser
from brain.llm import LLM
from planner.planner import Planner
from automation.registry import Registry
from automation.handlers import AppsHandler, MouseHandler, KeyboardHandler
from executor.executor import Executor
from models.response import Response


class Brain:
    """
    Coordinates Parser -> Planner -> Executor -> Response.

    Constructor takes no arguments. Parser, Planner, LLM, Registry,
    and Executor are all created internally here, and the built-in
    handlers are registered against the Registry by string action
    name before any request is processed.
    """

    def __init__(self) -> None:
        self._parser = Parser()
        self._planner = Planner()
        self._llm = LLM()
        self._registry = Registry()
        self._register_handlers()
        self._executor = Executor(self._registry)

    def _register_handlers(self) -> None:
        """
        Register the built-in handlers against the Registry using
        string action names only -- never StepKind, never
        automation.step.

        Adding a new handler later only requires one more
        registry.register(...) line here -- no other part of Brain,
        Executor, or Registry needs to change.
        """
        apps_handler = AppsHandler()
        mouse_handler = MouseHandler()
        keyboard_handler = KeyboardHandler()

        self._registry.register("open_app", apps_handler)
        self._registry.register("close_app", apps_handler)

        self._registry.register("move_mouse", mouse_handler)
        self._registry.register("left_click", mouse_handler)
        self._registry.register("right_click", mouse_handler)
        self._registry.register("double_click", mouse_handler)
        self._registry.register("scroll", mouse_handler)

        self._registry.register("type_text", keyboard_handler)
        self._registry.register("hotkey", keyboard_handler)

    def process(self, text: str) -> Response:
        """
        Run the full pipeline for a single piece of user input.

        Steps:
            1. Parser.parse(text) -> ParsedCommand
            2. Planner.create_plan(parsed) -> ExecutionPlan
            3. Executor.execute(plan) -> Response

        Args:
            text: raw user input.

        Returns:
            A Response. This method never raises -- any exception from
            Parser, Planner, or Executor is caught here and converted
            into a Response with success=False so callers (like
            dev_tests/test_pipeline.py) can print it without crashing.
        """
        try:
            parsed = self._parser.parse(text)
        except Exception as exc:  # noqa: BLE001 - intentional, broad by design
            return Response(
                success=False,
                message="Parser failed while processing input.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            plan = self._planner.create_plan(parsed)
        except Exception as exc:  # noqa: BLE001
            return Response(
                success=False,
                message="Planner failed while creating an execution plan.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            response = self._executor.execute(plan)
        except Exception as exc:  # noqa: BLE001
            return Response(
                success=False,
                message="Executor failed while running the execution plan.",
                data={"raw_text": text, "intent": plan.intent},
                error=f"{type(exc).__name__}: {exc}",
            )

        return response