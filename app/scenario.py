import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import Character


class Exit(BaseModel):
    to: str
    trigger: str


class SceneCheck(BaseModel):
    skill: str
    dc: int
    grants_fact: str | None = None


class Npc(BaseModel):
    id: str
    name: str
    label: str = "???"
    personality: str = ""
    secrets: list[str] = Field(default_factory=list)


class Scene(BaseModel):
    id: str
    title: str = ""
    goal: str = ""
    on_enter: str = ""
    npcs: list[Npc] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)
    checks: list[SceneCheck] = Field(default_factory=list)
    enemies: list[Character] = Field(default_factory=list)
    combat_reward_fact: str | None = None


class ScenarioData(BaseModel):
    id: str
    title: str
    premise: str
    start_scene: str
    scenes: list[Scene]


class Scenario:
    def __init__(self, data: ScenarioData) -> None:
        self.data = data
        self._scenes = {scene.id: scene for scene in data.scenes}
        if data.start_scene not in self._scenes:
            raise ValueError(f"start scene not found: {data.start_scene}")
        self._current_id = data.start_scene

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        data = ScenarioData.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return cls(data)

    @property
    def id(self) -> str:
        return self.data.id

    @property
    def premise(self) -> str:
        return self.data.premise

    def current_scene(self) -> Scene:
        return self._scenes[self._current_id]

    def advance(self, trigger: str) -> Scene | None:
        for exit_ in self.current_scene().exits:
            if exit_.trigger == trigger and exit_.to in self._scenes:
                self._current_id = exit_.to
                return self.current_scene()
        return None

    def available_exits(self) -> list[Exit]:
        return list(self.current_scene().exits)

    def check_for_skill(self, skill: str) -> SceneCheck | None:
        for check in self.current_scene().checks:
            if check.skill == skill:
                return check
        return None
