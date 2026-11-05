from typing import Protocol

from app.models import DmContext, DmResponse, Intent
from app.scenario import Scene


class DungeonMaster(Protocol):
    def narrate(self, ctx: DmContext) -> DmResponse: ...
    def classify_intent(self, text: str, scene: Scene) -> Intent: ...
    def answer_question(self, ctx: DmContext) -> str: ...
