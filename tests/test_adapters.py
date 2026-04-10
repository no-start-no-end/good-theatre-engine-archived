from src.adapters.inputs.mock import MockCamera, MockMicrophone, MockMotionSensor
from src.adapters.outputs.mock import MockAudioAdapter, MockDisplayAdapter, MockLightAdapter


def test_mock_inputs_emit_messages():
    motion = MockMotionSensor(interval=0, motion_probability=1.0)
    motion.start()
    assert motion.read() is not None

    camera = MockCamera(interval=0)
    camera.start()
    assert camera.read() is not None

    mic = MockMicrophone(trigger_interval=0)
    mic.start()
    assert mic.read() is not None


def test_mock_outputs_store_state():
    lights = MockLightAdapter()
    lights.set(1, 0.6)
    assert lights.status()["channels"][1] == 0.6

    audio = MockAudioAdapter()
    audio.set_volume(1, 0.4)
    assert audio.status()["volumes"][1] == 0.4

    display = MockDisplayAdapter()
    display.show("Hello")
    assert display.status()["current_text"] == "Hello"
