from __future__ import annotations

from typing import Any

from models.response import Response


class ResponseGenerator:
    def generate(
        self,
        executor_response: Response | None,
        intent: str,
        raw_text: str,
        verification_message: str = "",
        pipeline_reasoning: str = "",
    ) -> Response:
        if executor_response is None:
            return Response(
                success=False,
                message="No response from executor.",
                data={"raw_text": raw_text},
            )

        if executor_response.needs_clarification:
            return executor_response

        if not executor_response.success:
            return Response(
                success=False,
                message=executor_response.message or "Task failed.",
                data={"raw_text": raw_text, "intent": intent},
                error=executor_response.error,
            )

        message = executor_response.message
        if not message:
            message = self._generate_success_message(intent, executor_response.data)

        data = dict(executor_response.data)
        data["raw_text"] = raw_text
        data["intent"] = intent
        if pipeline_reasoning:
            data["reasoning"] = pipeline_reasoning

        return Response(
            success=True,
            message=message,
            data=data,
        )

    @staticmethod
    def _generate_success_message(intent: str, data: dict[str, Any]) -> str:
        if intent == "open_app":
            app = data.get("app_name") or data.get("display_name", "")
            return f"{app} is now open." if app else "Done."
        if intent == "open_website":
            site = data.get("website", "")
            return f"Opened {site}." if site else "Done."
        if intent == "search":
            query = data.get("query", "")
            return f"Searched for '{query}'." if query else "Done."
        if intent == "play_music":
            query = data.get("query", "")
            return f"Playing '{query}'." if query else "Done."
        return "Done."
