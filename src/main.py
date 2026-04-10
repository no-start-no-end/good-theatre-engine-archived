"""Good Theatre Engine - Main Entry Point."""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

from .adapters.inputs.keyboard import KeyboardAdapter
from .adapters.inputs.mock import MockCamera, MockMicrophone, MockMotionSensor
from .adapters.inputs.real.motion import MotionSensor
from .adapters.mqtt_adapter import MQTTAdapter
from .adapters.outputs.mock import MockAudioAdapter, MockDisplayAdapter, MockLightAdapter
from .adapters.outputs.osc import OSCAdapter
from .adapters.outputs.real.dmx import DMXAdapter
from .adapters.outputs.real.midi import MIDIAdapter
from .ai.decision import DecisionEngine
from .ai.pattern_learner import PatternLearner
from .core.bus import MessageBus
from .core.interface import InterfaceLayer
from .core.knowledge import KnowledgeBase
from .core.message import MessageType, UniversalMessage
from .cues import CueList
from .cues.runner import CueRunner
from .dimension_driver import DimensionDriver
from .matrix_runner import MatrixRunner, Mode
from .operators.cli import CLI
from .operators.dashboard import Dashboard
from .performance import PerformanceConfig, PerformanceRunner, Phase
from .performance_matrix import PhaseSpace


# ------------------------------------------------------------------
# Default phase space for matrix mode
# ------------------------------------------------------------------

def build_default_space() -> PhaseSpace:
    """Build the standard 5-region phase space with energy/tempo/audience/tension dims."""
    space = PhaseSpace()

    space.add_dimension("energy",     current=0.2, min=0.0, max=1.0)
    space.add_dimension("tempo",     current=60,  min=20, max=140)
    space.add_dimension("audience",  current=0.0, min=0.0, max=1.0)
    space.add_dimension("tension",   current=0.0, min=0.0, max=1.0)
    space.add_dimension("color_temp", current=3200, min=153, max=6535)

    space.add_region("detecting", {
        "energy": (0.00, 0.30),
        "tempo":  (40,   70),
        "color_temp": (2000, 3200),
    })
    space.add_region("stabilizing", {
        "energy": (0.30, 0.65),
        "tempo":  (70,   100),
        "color_temp": (3200, 4800),
    })
    space.add_region("suspended", {
        "energy": (0.00, 0.25),
        "tempo":  (30,   55),
        "color_temp": (2400, 3000),
    })
    space.add_region("escalating", {
        "energy": (0.55, 1.00),
        "tempo":  (90,   140),
        "color_temp": (4500, 6500),
    })
    space.add_region("dispersing", {
        "energy": (0.00, 0.15),
        "tempo":  (20,   40),
        "color_temp": (2000, 2700),
    })

    return space


# ------------------------------------------------------------------
# Engine wiring
# ------------------------------------------------------------------

def build_outputs(output_profile: str = "mock", osc_host: str = "localhost", osc_port: int = 53000) -> dict:
    if output_profile == "osc":
        return {
            "lights": OSCAdapter(host=osc_host, port=osc_port),
            "audio": MIDIAdapter(host=osc_host, port=osc_port),
            "display": MockDisplayAdapter(),
        }
    if output_profile == "real":
        return {
            "lights": DMXAdapter(),
            "audio": MIDIAdapter(host=osc_host, port=osc_port),
            "display": MockDisplayAdapter(),
        }
    return {
        "lights": MockLightAdapter(),
        "audio": MockAudioAdapter(),
        "display": MockDisplayAdapter(),
    }


def build_input_adapters(input_profile: str = "mock", motion_host: str = "0.0.0.0", motion_port: int = 5001):
    if input_profile == "real":
        return [MotionSensor(host=motion_host, port=motion_port), MockCamera(interval=2.0), MockMicrophone(trigger_interval=4.0)]
    return [MockMotionSensor(interval=1.0), MockCamera(interval=2.0), MockMicrophone(trigger_interval=4.0)]


def start_adapter_pump(interface: InterfaceLayer, adapters: list):
    def loop():
        while True:
            for adapter in adapters:
                try:
                    msg = adapter.read()
                    if msg:
                        interface.receive(msg)
                except Exception:
                    pass
            time.sleep(0.1)
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def wire_mqtt(bus: MessageBus, host: str = "localhost", port: int = 1883) -> MQTTAdapter | None:
    """Create and wire an MQTTAdapter to the MessageBus.

    Inbound:  MQTT messages → MQTTAdapter → bus (as UniversalMessage)
    Outbound: bus OUTPUT_COMMAND → MQTTAdapter → MQTT broker

    Returns None if paho-mqtt is not installed.
    """
    try:
        mqtt_adapter = MQTTAdapter(broker_host=host, broker_port=port)
    except ImportError:
        return None

    def mqtt_to_bus(msg_dict: dict):
        from .core.message import UniversalMessage
        try:
            msg = UniversalMessage.from_dict(msg_dict)
            bus.publish(msg)
        except (KeyError, TypeError, ValueError):
            pass  # malformed message — drop silently

    def bus_to_mqtt(msg):
        if msg.type == MessageType.OUTPUT_COMMAND:
            target = msg.payload.get("target", "unknown")
            mqtt_adapter.publish_output(target, msg.payload)

    mqtt_adapter.on_message = mqtt_to_bus
    bus.subscribe(MessageType.OUTPUT_COMMAND, bus_to_mqtt)
    mqtt_adapter.start()
    return mqtt_adapter


def wire_engine(log_dir: str, gate: str, outputs: dict | None = None, mqtt_host: str | None = None, mqtt_port: int = 1883):
    knowledge = KnowledgeBase(log_dir)
    bus = MessageBus()
    interface = InterfaceLayer(bus, knowledge, gate_mode=gate, log_dir=log_dir)
    decision = DecisionEngine(knowledge)
    outputs = outputs or build_outputs()

    def on_input(message: UniversalMessage):
        if message.type not in {MessageType.SENSOR_EVENT, MessageType.HUMAN_INPUT, MessageType.SYSTEM}:
            return
        for command in decision.process(message, knowledge.get_context()):
            interface.receive(command)

    def on_output(message: UniversalMessage):
        state = knowledge.load_state()
        allowed_outputs = state.constraints.get("allowed_outputs", list(outputs))
        target = message.payload.get("target")
        adapter = outputs.get(target)
        if adapter and target in allowed_outputs:
            adapter.send(message)

    bus.subscribe_all(on_input)
    bus.subscribe(MessageType.OUTPUT_COMMAND, on_output)
    return knowledge, bus, interface, decision, outputs


def build_dimension_driver(space: PhaseSpace, bus: MessageBus) -> DimensionDriver:
    """Wire mock sensor adapters into PhaseSpace dimensions via DimensionDriver."""
    driver = DimensionDriver(space)

    # mock.motion → energy (movement_level is 0–1)
    driver.map("mock.motion", "movement_level",
               to_dimension="energy", scale=0.7, smoothing=0.3)

    # mock.camera → audience (people_count 0–30 → 0–1)
    driver.map("mock.camera", "people_count",
               to_dimension="audience", scale=1/30, smoothing=0.4)

    # Wire driver into bus — DimensionDriver.on_bus_event subscribes to tags
    def forward_to_driver(msg):
        driver.on_bus_event(msg)
    bus.subscribe_all(forward_to_driver)

    return driver


# ------------------------------------------------------------------
# Phase configs (shared between sequence and matrix modes)
# ------------------------------------------------------------------

DEFAULT_PHASE_CONFIGS: dict[Phase, PerformanceConfig] = {
    Phase.INTRO:       PerformanceConfig("Good Theatre", Phase.INTRO,       0.2, ["lights", "audio", "display"], 1.0, True),
    Phase.ACT_1:       PerformanceConfig("Good Theatre", Phase.ACT_1,       0.5, ["lights", "audio", "display"], 1.0, True),
    Phase.INTERMISSION: PerformanceConfig("Good Theatre", Phase.INTERMISSION, 0.2, ["lights", "display"],        1.0, True),
    Phase.ACT_2:       PerformanceConfig("Good Theatre", Phase.ACT_2,       0.8, ["lights", "audio", "display"], 1.0, True),
    Phase.OUTRO:       PerformanceConfig("Good Theatre", Phase.OUTRO,       0.1, ["lights", "display"],        1.0, True),
}


# ------------------------------------------------------------------
# Run loops
# ------------------------------------------------------------------

def run_mock(interface: InterfaceLayer):
    adapters = [MockMotionSensor(), MockCamera(), MockMicrophone()]
    for adapter in adapters:
        adapter.start()
    print("Mock mode running. Press Ctrl+C to stop.")
    try:
        while True:
            for adapter in adapters:
                message = adapter.read()
                if message:
                    interface.receive(message)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for adapter in adapters:
            adapter.stop()


def run_matrix(
    interface: InterfaceLayer,
    knowledge: KnowledgeBase,
    bus: MessageBus,
    decision: DecisionEngine,
    outputs: dict,
    input_profile: str = "mock",
    motion_host: str = "0.0.0.0",
    motion_port: int = 5001,
    mqtt_host: str | None = None,
    mqtt_port: int = 1883,
):
    """Run the matrix-first performance engine.

    PhaseSpace drives all transitions. DimensionDriver maps sensor events to
    dimension values. PerformanceRunner handles canonical state + constraints.
    """
    space = build_default_space()
    driver = build_dimension_driver(space, bus)

    matrix_runner = MatrixRunner(
        space=space,
        knowledge=knowledge,
        interface=interface,
        decision_engine=decision,
        dimension_driver=driver,
        phase_configs=DEFAULT_PHASE_CONFIGS,
        mode=Mode.MATRIX_FIRST,
    )

    # Register what happens in each phase
    matrix_runner.on_phase_enter("detecting",    lambda s: _phase_enter("detecting", outputs))
    matrix_runner.on_phase_enter("stabilizing",  lambda s: _phase_enter("stabilizing", outputs))
    matrix_runner.on_phase_enter("suspended",    lambda s: _phase_enter("suspended", outputs))
    matrix_runner.on_phase_enter("escalating",   lambda s: _phase_enter("escalating", outputs))
    matrix_runner.on_phase_enter("dispersing",   lambda s: _phase_enter("dispersing", outputs))

    keyboard = KeyboardAdapter()
    keyboard.start()

    adapters = build_input_adapters(input_profile=input_profile, motion_host=motion_host, motion_port=motion_port)
    for adapter in adapters:
        adapter.start()

    matrix_runner.start()
    mqtt_adapter = None
    if mqtt_host:
        mqtt_adapter = wire_mqtt(bus, host=mqtt_host, port=mqtt_port)
        if mqtt_adapter:
            print(f"  MQTT: connected to {mqtt_host}:{mqtt_port}")
        else:
            print("  MQTT: paho-mqtt not installed — skipping")

    print("Matrix mode running.")
    print(f"  Regions: {list(space.regions.keys())}")
    print(f"  Dimensions: {list(space.dimensions.keys())}")
    print("  Press Ctrl+C to stop.")
    print()
    _print_space_status(matrix_runner)

    try:
        tick_count = 0
        while True:
            # Read sensors → bus → DimensionDriver → PhaseSpace (via bus subscription)
            for adapter in adapters:
                msg = adapter.read()
                if msg:
                    interface.receive(msg)

            # Keyboard operator commands
            key_msg = keyboard.read()
            if key_msg:
                _handle_keyboard(key_msg, matrix_runner)

            # Tick matrix runner (push detection + velocity advancement)
            matrix_runner.tick()

            # Print space status every 2 seconds
            tick_count += 1
            if tick_count % 20 == 0:
                _print_space_status(matrix_runner)

            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        matrix_runner.stop()
        keyboard.stop()
        for adapter in adapters:
            adapter.stop()
        if mqtt_adapter:
            mqtt_adapter.stop()


def _phase_enter(region: str, outputs: dict):
    """Fire output presets when entering a phase region."""
    presets = {
        "detecting":    {"lights": "intro_preset",   "audio": "ambient_drone"},
        "stabilizing":  {"lights": "act_1_full",     "audio": "score_1"},
        "suspended":    {"lights": "intermission",   "audio": "pause"},
        "escalating":   {"lights": "act_2_intense",  "audio": "score_2"},
        "dispersing":   {"lights": "blackout",       "audio": "stop_all"},
    }
    # In mock mode, just print — real mode would call actual adapters
    preset = presets.get(region, {})
    print(f"  → {region.upper()}: {preset}")


def _print_space_status(matrix_runner: MatrixRunner):
    """Print current phase space state to terminal."""
    status = matrix_runner.status()
    dims = status["space"]["dimensions"]
    print(
        f"  [{status['current_region'] or '?'}] "
        f"energy={dims.get('energy', 0):.2f} "
        f"tempo={dims.get('tempo', 0):.0f} "
        f"audience={dims.get('audience', 0):.2f} "
        f"tension={dims.get('tension', 0):.2f}"
    )


def _handle_keyboard(key_msg: UniversalMessage, matrix_runner: MatrixRunner):
    """Handle keyboard operator messages for matrix mode."""
    action = key_msg.payload.get("action", "")
    if action in {"emergency_stop", "stop"}:
        matrix_runner.stop()
        print("Matrix runner stopped.")
    elif action == "jump_intro":
        matrix_runner.jump("detecting")
    elif action == "jump_act_1":
        matrix_runner.jump("stabilizing")
    elif action == "jump_intermission":
        matrix_runner.jump("suspended")
    elif action == "jump_act_2":
        matrix_runner.jump("escalating")
    elif action == "jump_outro":
        matrix_runner.jump("dispersing")
    elif action == "status":
        _print_space_status(matrix_runner)


def run_performance(
    interface: InterfaceLayer,
    knowledge: KnowledgeBase,
    decision: DecisionEngine,
    outputs: dict,
    config_path: str | None,
    cue_runner: CueRunner | None = None,
):
    config, phase_configs, cue_list = load_show_config(config_path)
    if phase_configs:
        _phase_configs = phase_configs
    else:
        _phase_configs = DEFAULT_PHASE_CONFIGS
    runner = PerformanceRunner(config, knowledge, interface, decision, phase_configs=_phase_configs)
    keyboard = KeyboardAdapter()
    keyboard.start()
    learner = PatternLearner(knowledge)

    adapters = build_input_adapters()
    for adapter in adapters:
        adapter.start()

    runner.start()
    if cue_runner and cue_list:
        cue_runner.cue_list._fired.clear()
        cue_runner.start()

    print("Performance mode running. Press Ctrl+C to stop.")
    try:
        while True:
            for adapter in adapters:
                message = adapter.read()
                if message:
                    interface.receive(message)
            key_message = keyboard.read()
            if key_message:
                runner.handle_operator_message(key_message)
            time.sleep(0.1)
    except KeyboardInterrupt:
        if cue_runner:
            cue_runner.stop()
        runner.end()
        learner.learn(str(interface.event_log_path))
    finally:
        keyboard.stop()
        for adapter in adapters:
            adapter.stop()


def load_show_config(config_path: str | None):
    """Load PHASES and optional CUE_LIST from a config Python file."""
    if not config_path:
        return None, None, None

    path = Path(config_path)
    spec = importlib.util.spec_from_file_location("show_config", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    phases = getattr(module, "PHASES")
    base = phases.get(Phase.INTRO, next(iter(phases.values())))
    cue_list: CueList | None = getattr(module, "CUE_LIST", None)
    return base, phases, cue_list


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Good Theatre Engine")
    parser.add_argument(
        "--mode",
        choices=["mock", "cli", "dashboard", "dashboard-matrix", "performance", "matrix", "test"],
        default="mock",
    )
    parser.add_argument("--gate", default="advisory")
    parser.add_argument("--log-dir", default="./logs")
    parser.add_argument("--config", default=None, help="Path to show config Python file")
    parser.add_argument("--outputs", choices=["mock", "osc", "real"], default="mock")
    parser.add_argument("--inputs", choices=["mock", "real"], default="mock")
    parser.add_argument("--osc-host", default="localhost")
    parser.add_argument("--osc-port", type=int, default=53000)
    parser.add_argument("--motion-host", default="0.0.0.0")
    parser.add_argument("--motion-port", type=int, default=5001)
    parser.add_argument("--mqtt-host", default=None, help="MQTT broker host (e.g. 192.168.1.50). If omitted, MQTT is disabled.")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    args = parser.parse_args()

    outputs = build_outputs(output_profile=args.outputs, osc_host=args.osc_host, osc_port=args.osc_port)
    knowledge, bus, interface, decision, outputs = wire_engine(args.log_dir, args.gate, outputs=outputs)

    if args.mode == "matrix":
        run_matrix(
            interface, knowledge, bus, decision, outputs,
            input_profile=args.inputs,
            motion_host=args.motion_host,
            motion_port=args.motion_port,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
        )

    elif args.mode == "performance":
        _, phase_configs, cue_list = load_show_config(args.config)
        base_config = (phase_configs or DEFAULT_PHASE_CONFIGS).get(
            Phase.INTRO, next(iter(DEFAULT_PHASE_CONFIGS.values()))
        )
        runner = PerformanceRunner(base_config, knowledge, interface, decision, phase_configs=phase_configs or DEFAULT_PHASE_CONFIGS)
        cue_runner: CueRunner | None = None
        if cue_list:
            cue_runner = CueRunner(cue_list=cue_list, interface=interface, performance_runner=runner)
        run_performance(interface, knowledge, decision, outputs, args.config, cue_runner)

    elif args.mode in {"cli", "dashboard", "dashboard-matrix"}:
        base_config = DEFAULT_PHASE_CONFIGS[Phase.INTRO]
        runner = PerformanceRunner(base_config, knowledge, interface, decision, phase_configs=DEFAULT_PHASE_CONFIGS)
        cue_runner: CueRunner | None = None

        if args.mode == "cli":
            cli = CLI(interface, knowledge, performance_runner=runner, cue_runner=cue_runner)
            cli.run()
        elif args.mode == "dashboard":
            Dashboard(
                interface, knowledge, decision,
                outputs=outputs,
                performance_runner=runner,
                cue_runner=cue_runner,
            ).start()
        else:
            # dashboard-matrix: live matrix runner + dashboard
            space = build_default_space()
            driver = build_dimension_driver(space, bus)
            adapters = build_input_adapters(input_profile=args.inputs, motion_host=args.motion_host, motion_port=args.motion_port)
            for adapter in adapters:
                adapter.start()
            start_adapter_pump(interface, adapters)
            matrix_runner = MatrixRunner(
                space=space,
                knowledge=knowledge,
                interface=interface,
                decision_engine=decision,
                dimension_driver=driver,
                phase_configs=DEFAULT_PHASE_CONFIGS,
                mode=Mode.MATRIX_FIRST,
            )
            matrix_runner.on_phase_enter("detecting",    lambda s: _phase_enter("detecting", outputs))
            matrix_runner.on_phase_enter("stabilizing",  lambda s: _phase_enter("stabilizing", outputs))
            matrix_runner.on_phase_enter("suspended",    lambda s: _phase_enter("suspended", outputs))
            matrix_runner.on_phase_enter("escalating",   lambda s: _phase_enter("escalating", outputs))
            matrix_runner.on_phase_enter("dispersing",   lambda s: _phase_enter("dispersing", outputs))
            matrix_runner.start()
            mqtt_adapter = None
            if args.mqtt_host:
                mqtt_adapter = wire_mqtt(bus, host=args.mqtt_host, port=args.mqtt_port)
            Dashboard(
                interface, knowledge, decision,
                outputs=outputs,
                performance_runner=matrix_runner.performance_runner,
                cue_runner=cue_runner,
                matrix_runner=matrix_runner,
            ).start()

    elif args.mode == "mock":
        run_mock(interface)

    elif args.mode == "test":
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], check=False)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
