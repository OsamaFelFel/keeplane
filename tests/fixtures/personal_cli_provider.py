"""Tool replies run only after the shared fixture verifies real provider auth."""

from typing import ClassVar

from tests.fixtures.personal_cli_tools import prepare
from tests.fixtures.personal_provider import PersonalProvider as Provider
from tests.fixtures.personal_provider import serve

__all__ = ["PersonalProvider", "serve"]


class PersonalProvider(Provider):
    state: ClassVar[dict] = {"contacts": [], "failures": 0, "probes": 0, "tools": []}

    def respond(self, body, protocol, owner_label):
        if not body.get("tools"):
            return False
        raw, observation = prepare(body, protocol, owner_label)
        with self.lock:
            self.state["tools"].append(observation)
        self.answer(
            200, raw, "text/event-stream" if body.get("stream") else "application/json"
        )
        return True
