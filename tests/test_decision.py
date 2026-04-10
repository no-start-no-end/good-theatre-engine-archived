from src.ai.decision import DecisionEngine
from src.core.knowledge import KnowledgeBase
from src.core.message import human_input, sensor_event


def test_decision_engine_generates_commands(tmp_path):
    kb = KnowledgeBase(str(tmp_path))
    engine = DecisionEngine(kb)
    commands = engine.process(human_input("cli", {"text": "raise the tension"}), kb.get_context())
    assert commands
    assert any(command.payload["target"] == "audio" for command in commands)


def test_constraints_are_applied(tmp_path):
    kb = KnowledgeBase(str(tmp_path))
    state = kb.load_state()
    state.constraints["max_volume"] = 0.2
    kb.save_state(state)
    engine = DecisionEngine(kb)
    commands = engine.process(sensor_event("sensor", {"movement_level": 0.5}), kb.get_context())
    audio = [cmd for cmd in commands if cmd.payload["target"] == "audio"][0]
    assert audio.payload["volume"] <= 0.2
