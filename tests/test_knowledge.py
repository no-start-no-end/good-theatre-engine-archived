from src.core.knowledge import KnowledgeBase, PerformanceState


def test_state_persistence(tmp_path):
    kb = KnowledgeBase(str(tmp_path))
    state = PerformanceState(phase="running", energy_level=0.9)
    kb.save_state(state)
    loaded = kb.load_state()
    assert loaded.phase == "running"
    assert loaded.energy_level == 0.9


def test_pattern_logging(tmp_path):
    kb = KnowledgeBase(str(tmp_path))
    kb.log_pattern("motion", "raised lights", 0.7)
    patterns = kb.get_patterns("motion")
    assert len(patterns) == 1
    assert patterns[0]["outcome"] == "raised lights"
