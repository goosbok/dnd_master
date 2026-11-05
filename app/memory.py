import uuid

from app.models import Fact


class Memory:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._facts: list[Fact] = []
        self._scene_summaries: dict[str, str] = {}

    def record(self, fact: Fact) -> None:
        if any(existing.text == fact.text for existing in self._facts):
            return
        self._facts.append(fact)

    def add(self, text: str, source: str = "engine", scene_id: str | None = None) -> Fact:
        fact = Fact(id=str(uuid.uuid4()), text=text, source=source, scene_id=scene_id)
        self.record(fact)
        return fact

    def remove(self, text: str) -> bool:
        before = len(self._facts)
        self._facts = [f for f in self._facts if f.text != text]
        return len(self._facts) < before

    def has(self, text: str) -> bool:
        return any(f.text == text for f in self._facts)

    def recall(self) -> list[Fact]:
        return list(self._facts)

    def summarize_scene(self, scene_id: str, summary: str) -> None:
        self._scene_summaries[scene_id] = summary

    def scene_summaries(self) -> dict[str, str]:
        return dict(self._scene_summaries)
