import json

from src.ai.pattern_learner import PatternLearner
from src.core.knowledge import KnowledgeBase
from src.core.message import MessageType, UniversalMessage, human_input, output_command


def test_pattern_learner_extracts_and_persists_patterns(tmp_path):
    kb = KnowledgeBase(str(tmp_path / "kb"))
    learner = PatternLearner(kb)
    log_path = tmp_path / "events.jsonl"

    trigger = human_input("keyboard", {"action": "applause", "approved": True})
    trace_id = trigger.id
    trigger.metadata.trace_id = trace_id
    output = output_command("lights", {"action": "fade", "channel": 1, "value": 0.8, "duration": 1.0})
    output.metadata.trace_id = trace_id

    with log_path.open("w", encoding="utf-8") as handle:
        for message in (trigger, output):
            handle.write(json.dumps({"trace_id": trace_id, "message": message.to_dict()}) + "\n")

    analysis = learner.learn(str(log_path))

    assert analysis["summary"]["learned"] == 1
    assert kb.get_patterns("keyboard")
