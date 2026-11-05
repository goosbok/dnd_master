from pathlib import Path

import pytest

from app.scenario import Scenario

SCENARIO_PATH = (
    Path(__file__).resolve().parent.parent
    / "scenarios"
    / "curse_of_the_salted_goat.json"
)


@pytest.fixture()
def scenario() -> Scenario:
    return Scenario.load(SCENARIO_PATH)


def test_loads_demo_scenario(scenario):
    assert scenario.id == "curse-of-the-salted-goat"
    assert scenario.current_scene().id == "tavern"
    assert scenario.premise


def test_available_exits(scenario):
    exits = scenario.available_exits()
    assert len(exits) == 1
    assert exits[0].trigger == "has_contract"
    assert exits[0].to == "docks"


def test_advance_by_trigger_walks_the_whole_story(scenario):
    assert scenario.advance("has_contract").id == "docks"
    assert scenario.advance("found_smuggler_trail").id == "warehouse"
    assert scenario.advance("warehouse_cleared").id == "hideout"
    assert scenario.advance("curse_lifted").id == "epilogue"
    assert scenario.available_exits() == []


def test_unknown_trigger_keeps_current_scene(scenario):
    assert scenario.advance("no_such_trigger") is None
    assert scenario.current_scene().id == "tavern"


def test_scene_content_is_loaded(scenario):
    tavern = scenario.current_scene()
    npc_ids = {npc.id for npc in tavern.npcs}
    assert {"mayor", "innkeeper"} <= npc_ids
    skills = {check.skill for check in tavern.checks}
    assert "persuasion" in skills

    scenario.advance("has_contract")
    scenario.advance("found_smuggler_trail")
    warehouse = scenario.current_scene()
    assert len(warehouse.enemies) == 2
    assert warehouse.combat_reward_fact == "warehouse_cleared"
