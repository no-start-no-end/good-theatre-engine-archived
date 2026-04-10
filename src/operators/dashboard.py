"""Broadcast-style theatre control dashboard using stdlib HTTP + SSE."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from ..core.interface import InterfaceLayer
from ..core.knowledge import KnowledgeBase
from ..core.message import UniversalMessage, human_input, sensor_event

# Daniel palette
PHASE_COLORS = {
    "detecting":   "#f5e6c8",
    "stabilizing":  "#00979a",
    "suspended":   "#7ad4c2",
    "escalating":  "#ff8a86",
    "dispersing":  "#d9d9d9",
    "idle":        "#f4f4f4",
    "emergency_stop": "#ff5f56",
}


class Dashboard:
    """Theatre-ready control room dashboard served on the network."""

    def __init__(
        self,
        interface: InterfaceLayer,
        knowledge: KnowledgeBase,
        decision_engine,
        outputs: dict | None = None,
        performance_runner=None,
        cue_runner=None,
        matrix_runner=None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.interface = interface
        self.knowledge = knowledge
        self.decision_engine = decision_engine
        self.outputs = outputs or {}
        self.performance_runner = performance_runner
        self.cue_runner = cue_runner
        self.matrix_runner = matrix_runner
        self.host = host
        self.port = port
        self.clients: list = []
        self.timeline: list[dict] = []
        self.interface.bus.subscribe_all(self.broadcast)

    def broadcast(self, message: UniversalMessage):
        """Send the latest event to all connected SSE clients."""
        event = message.to_dict()
        self.timeline.append(event)
        self.timeline = self.timeline[-50:]
        dead = []
        payload = f"data: {json.dumps(event)}\n\n".encode()
        for client in list(self.clients):
            try:
                client.wfile.write(payload)
                client.wfile.flush()
            except Exception:
                dead.append(client)
        for client in dead:
            if client in self.clients:
                self.clients.remove(client)

    def snapshot(self) -> dict:
        """Return a UI-ready state snapshot."""
        state = self.knowledge.load_state().to_dict()
        phase_runtime = self.performance_runner.phase_runtime() if self.performance_runner else 0.0
        performance_runtime = self.performance_runner.performance_runtime() if self.performance_runner else 0.0

        cue_info: dict | None = None
        if self.cue_runner:
            cues = self.cue_runner.cue_list
            cue_info = {
                "name": cues.name,
                "total": len(cues.all()),
                "fired": len(cues._fired),
                "pending": [c.number for c in cues.pending()],
                "cues": [
                    {
                        "number": c.number,
                        "description": c.description,
                        "fired": cues.is_fired(c.number),
                        "targets": list(c.targets.keys()),
                        "offset": c.offset_seconds,
                    }
                    for c in cues.all()
                ],
            }

        matrix_info = None
        if self.matrix_runner:
            matrix_status = self.matrix_runner.status()
            dims = matrix_status.get("space", {}).get("dimensions", {})
            matrix_info = {
                "mode": matrix_status.get("mode"),
                "current_region": matrix_status.get("current_region"),
                "current_phase": matrix_status.get("current_phase"),
                "dimensions": dims,
                "regions": matrix_status.get("space", {}).get("regions", []),
                "transitions": matrix_status.get("transitions", []),
                "phase_color": PHASE_COLORS.get(matrix_status.get("current_region", "idle"), PHASE_COLORS["idle"]),
            }

        return {
            "state": state,
            "outputs": {name: adapter.status() for name, adapter in self.outputs.items()},
            "timeline": self.timeline[-50:],
            "patterns": self.knowledge.get_context()["recent_patterns"][-10:],
            "cues": cue_info,
            "matrix": matrix_info,
            "performance": {
                "phase_runtime": round(phase_runtime, 1),
                "runtime": round(performance_runtime, 1),
                "allowed_outputs": state.get("constraints", {}).get("allowed_outputs", []),
                "target_energy": (
                    getattr(self.performance_runner.config, "target_energy", state.get("energy_level", 0.0))
                    if self.performance_runner
                    else state.get("energy_level", 0.0)
                ),
                "phase_color": PHASE_COLORS.get(state.get("phase", "idle"), PHASE_COLORS["idle"]),
            },
        }

    def start(self):
        """Start the dashboard HTTP server."""
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, data: dict | list, status: int = 200):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/":
                    body = HTML.encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/snapshot":
                    self._send_json(dashboard.snapshot())
                elif self.path == "/events":
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    dashboard.clients.append(self)
                    try:
                        while True:
                            threading.Event().wait(20)
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                    except Exception:
                        if self in dashboard.clients:
                            dashboard.clients.remove(self)
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode()
                data = json.loads(raw) if raw else {}
                if self.path == "/inject":
                    kind = data.get("type", "sensor_event")
                    source = data.get("source", "dashboard")
                    payload = data.get("payload", {})
                    msg = human_input(source, payload) if kind == "human_input" else sensor_event(source, payload)
                    dashboard.interface.receive(msg)
                    self._send_json({"ok": True})
                elif self.path == "/control":
                    action = data.get("action")
                    if dashboard.matrix_runner:
                        phase_name = data.get("phase")
                        ordered = ["detecting", "stabilizing", "suspended", "escalating", "dispersing"]
                        current = dashboard.matrix_runner.current_region or "detecting"

                        def snap_to_region(region_name: str):
                            region = dashboard.matrix_runner.space.regions.get(region_name)
                            if not region:
                                return
                            for dim_name, (lo, hi) in region.boundaries.items():
                                dashboard.matrix_runner.space.set(dim_name, (lo + hi) / 2)

                        if action == "transition" and phase_name:
                            snap_to_region(str(phase_name))
                            dashboard.matrix_runner.jump(str(phase_name))
                        elif action == "next_phase":
                            idx = ordered.index(current) if current in ordered else 0
                            target_region = ordered[(idx + 1) % len(ordered)]
                            snap_to_region(target_region)
                            dashboard.matrix_runner.jump(target_region)
                        elif action == "set_energy":
                            target = max(0.0, min(1.0, float(data.get("target_energy", 0.5))))
                            dashboard.matrix_runner.space.set("energy", target)
                            dashboard.matrix_runner.tick(delta_seconds=0.0)
                        elif action in {"emergency_stop", "stop"}:
                            dashboard.matrix_runner.performance_runner.emergency_stop()
                            dashboard.matrix_runner.stop()
                        elif dashboard.performance_runner:
                            dashboard.performance_runner.handle_operator_message(
                                human_input("dashboard.control", {**data, "action": action, "approved": True})
                            )
                    elif dashboard.performance_runner:
                        dashboard.performance_runner.handle_operator_message(
                            human_input("dashboard.control", {**data, "action": action, "approved": True})
                        )
                    self._send_json({"ok": True, "action": action})
                elif self.path == "/cue":
                    number = data.get("cue")
                    if dashboard.cue_runner and number is not None:
                        dashboard.cue_runner.jump_to(int(number))
                    self._send_json({"ok": True, "cue": number})
                else:
                    self.send_error(404)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Dashboard running at http://{self.host}:{self.port}")
        server.serve_forever()


HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Good Theatre Control Room</title><style>
:root{--bg:#f4f4f4;--panel:#ffffff;--line:#d9d9d9;--cream:#f5e6c8;--mint:#7ad4c2;--teal:#00979a;--ink:#0a0a0a;--coral:#ff8a86;--text:#111;--muted:#666;--danger:#ff5f56}
*{box-sizing:border-box}body{margin:0;background:var(--scene-bg,linear-gradient(180deg,#e8e8e8,#f9f9f9));color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif;transition:background 700ms ease,color 400ms ease}body::before{content:'';position:fixed;inset:0;background:var(--scene-glow,transparent);pointer-events:none;opacity:.9;transition:background 700ms ease;z-index:0}body::after{content:'';position:fixed;inset:0;background:var(--cue-flash,transparent);opacity:0;pointer-events:none;transition:opacity 220ms ease;z-index:0}body.cue-firing::after{opacity:1}button,input,textarea,select{width:100%;background:#fff;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px}button{cursor:pointer;font-weight:600}button:hover{border-color:var(--teal)}.wrap{padding:18px;position:relative;z-index:1}.grid{display:grid;grid-template-columns:1.05fr 1fr 1fr;gap:14px}.panel{background:var(--panel-bg,rgba(255,255,255,.9));backdrop-filter:blur(8px);border:1px solid var(--panel-line,var(--line));border-radius:16px;padding:14px;box-shadow:0 8px 24px rgba(0,0,0,.05);transition:background 500ms ease,border-color 500ms ease,box-shadow 500ms ease,transform 260ms ease}body.transitioning .panel{box-shadow:0 14px 36px rgba(0,0,0,.12)}body.cue-firing .panel{transform:translateY(-1px);box-shadow:0 16px 40px rgba(0,0,0,.14)}.phase{font-size:38px;font-weight:800;letter-spacing:1px;text-align:center}.statline{display:flex;justify-content:space-between;margin:8px 0;color:var(--muted);gap:12px}.timer{font-size:24px;font-weight:700}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}.danger{border-color:rgba(255,95,86,.6);color:var(--danger)}.timeline,.patterns,.outputs,.cue-list,.transition-log{height:280px;overflow:auto;font-size:12px}.event{padding:8px 0;border-bottom:1px solid #efefef}.badge{display:inline-block;padding:2px 7px;border-radius:999px;margin-right:8px;border:1px solid var(--line);color:var(--teal)}.badge-soft{display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;background:#fafafa;border:1px solid var(--line);font-size:12px;font-weight:600;color:var(--ink)}.status-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 12px}.top-status{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 12px}.health-good{border-color:rgba(0,151,154,.25);background:rgba(0,151,154,.06)}.health-warn{border-color:rgba(255,138,134,.35);background:rgba(255,138,134,.10)}.health-badge{transition:transform .35s ease,box-shadow .35s ease,background .35s ease,border-color .35s ease}.health-badge.health-warn{box-shadow:0 0 0 1px rgba(255,138,134,.12),0 0 24px rgba(255,138,134,.16);animation:warnPulse 1.6s ease-in-out infinite}.confidence-low{box-shadow:0 0 0 1px rgba(255,95,86,.10),0 0 18px rgba(255,95,86,.10)}.confidence-mid{box-shadow:0 0 0 1px rgba(245,230,200,.14),0 0 16px rgba(245,230,200,.12)}.confidence-high{box-shadow:0 0 0 1px rgba(0,151,154,.10),0 0 16px rgba(0,151,154,.10)}@keyframes warnPulse{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}.toast{position:fixed;right:14px;bottom:14px;max-width:320px;padding:12px 14px;border-radius:12px;background:#111;color:#fff;box-shadow:0 10px 28px rgba(0,0,0,.22);opacity:0;transform:translateY(8px);transition:opacity .18s ease,transform .18s ease;pointer-events:none;z-index:50}.toast.show{opacity:1;transform:translateY(0)}.toast.error{background:#7d1d17}.toast.transition{background:linear-gradient(135deg,#0a0a0a,#00979a);font-weight:700}.empty{color:var(--muted);font-style:italic;padding:8px 0}.section-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}.help{font-size:12px;color:var(--muted);line-height:1.45}.control-group{margin-top:10px}.debug-panel summary{cursor:pointer;font-weight:700}.debug-panel{margin-top:8px}.debug-panel[open]{padding-top:8px}pre{white-space:pre-wrap;margin:0}.small{font-size:12px;color:var(--muted)}.gauge{width:220px;height:120px;position:relative;margin:0 auto}.arc{position:absolute;inset:0;border-radius:220px 220px 0 0;border:12px solid #ececec;border-bottom:none}.fill{position:absolute;left:0;right:0;bottom:0;height:calc(var(--energy,0)*100%);background:linear-gradient(180deg,rgba(245,230,200,.3),rgba(255,138,134,.7));clip-path:polygon(0 100%,100% 100%,100% 45%,50% 0,0 45%)}.needle{position:absolute;left:50%;bottom:0;width:4px;height:92px;background:var(--ink);transform-origin:bottom center}.target{position:absolute;left:50%;bottom:0;width:2px;height:78px;background:var(--teal);transform-origin:bottom center;opacity:.9}.cue-row{display:flex;align-items:center;padding:6px 0;border-bottom:1px solid #efefef}.cue-row.fired{opacity:.45}.cue-num{width:40px;color:var(--teal);font-weight:bold}.cue-desc{flex:1;color:var(--text)}.cue-targets{color:var(--muted);font-size:11px}.cue-fire{margin-left:8px;padding:3px 10px;background:#fff;border:1px solid var(--teal);border-radius:6px;color:var(--teal);cursor:pointer;font-size:11px}.cue-fire:hover{background:var(--teal);color:#fff}.matrix-panel{grid-column:span 2}.phase-space{height:320px;border:1px solid var(--line);border-radius:12px;background:radial-gradient(circle at 50% 60%,rgba(0,151,154,.08),transparent 35%),linear-gradient(180deg,#fff,#f8f8f8);padding:10px;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}.legend{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px}.sw{width:10px;height:10px;border-radius:999px}.dim-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.dim{padding:8px;border:1px solid var(--line);border-radius:10px;background:#fff}.bar{height:8px;border-radius:999px;background:#eee;overflow:hidden;margin-top:6px}.bar > span{display:block;height:100%;background:linear-gradient(90deg,var(--mint),var(--teal))}.transition-log .event strong{color:var(--teal)}.phase-caption{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:8px}.phase-caption .small strong{color:var(--ink)}.arrival{margin-top:10px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,#fff,#fbfbfb)}.arrival strong{display:block;margin-bottom:4px}.arrival .small{line-height:1.45}svg text{fill:#666;font-size:11px}@media (max-width:1100px){.grid{grid-template-columns:1fr 1fr}.matrix-panel{grid-column:span 2}}@media (max-width:760px){.wrap{padding:10px}.grid{grid-template-columns:1fr}.matrix-panel{grid-column:span 1}.controls{grid-template-columns:1fr 1fr}.phase{font-size:30px}.timer{font-size:20px}.timeline,.patterns,.outputs,.cue-list,.transition-log{height:220px}}
</style></head><body><div class='wrap'><div class='top-status'><span class='badge-soft health-good health-badge confidence-high' id='health_badge'>system: healthy</span><span class='badge-soft' id='confidence_badge'>confidence: high</span><span class='badge-soft' id='outputs_badge'>outputs: 0</span><span class='badge-soft' id='events_badge'>events: 0</span></div><div class='grid'>
<div class='panel'><h2>PHASE</h2><div id='phase' class='phase'>IDLE</div><div class='small' id='phase_signature'>A threshold field waiting for motion.</div><div class='statline'><span>Target energy</span><span id='target'>0.00</span></div><div id='gauge' class='gauge' style='--energy:0'><div class='arc'></div><div class='fill'></div><div id='targetNeedle' class='target'></div><div id='needle' class='needle'></div></div><div class='statline'><span>Current energy</span><span id='energy'>0.00</span></div><div class='statline'><span>Allowed outputs</span><span id='allowed'>none</span></div><div class='statline'><span>Phase timer</span><span id='phase_timer' class='timer'>0.0s</span></div><div class='statline'><span>Show timer</span><span id='show_timer' class='timer'>0.0s</span></div></div>
<div class='panel'><h2>CONTROL SURFACE</h2><div class='status-row'><span class='badge-soft' id='mode_badge'>matrix</span><span class='badge-soft' id='region_badge'>region: detecting</span></div><div class='section-label'>Safety + transport</div><div class='controls'><button class='danger' onclick="control('emergency_stop')">Emergency Stop</button><button onclick="control('next_phase')">Next Region</button><button onclick="control('mute_toggle')">Mute All</button></div><div class='control-group'><div class='section-label'>Direct region jump</div><div class='controls'><button onclick="phase('detecting')">DETECTING</button><button onclick="phase('stabilizing')">STABILIZING</button><button onclick="phase('suspended')">SUSPENDED</button><button onclick="phase('escalating')">ESCALATING</button><button onclick="phase('dispersing')">DISPERSING</button><button onclick="control('resume')">Resume</button></div></div><div class='control-group'><div class='section-label'>Energy override</div><input id='energy_input' type='number' min='0' max='1' step='0.05' value='0.5'><button onclick='setEnergy()'>Set energy target</button></div><p class='help'>Use direct region jump when you need deterministic repositioning. Use energy override for gentle steering inside the matrix.</p></div>
<div class='panel'><h2>OUTPUT STATUS</h2><p class='help'>Adapter state is surfaced here so degraded transport is visible before the operator feels it.</p><div id='outputs' class='outputs'></div></div>
<div class='panel matrix-panel' id='matrix_panel' style='display:none'><h2>PHASE SPACE</h2><div class='status-row'><span class='badge-soft' id='matrix_current'>current: intro</span><span class='badge-soft' id='matrix_last_transition'>last: none</span><span class='badge-soft' id='matrix_drift'>drift: settling</span><span class='badge-soft' id='matrix_forecast'>forecast: holding</span></div><div class='small'>Live energy × tempo slice. Dark marker = current state. The trail shows recent motion through the field. Colored regions are viable attractors.</div><div class='legend' id='matrix_legend'></div><div class='phase-space'><svg id='phase_space_svg' viewBox='0 0 560 240' width='100%' height='220'></svg><div class='phase-caption'><div class='small'><strong>X</strong> energy, low to high</div><div class='small'><strong>Y</strong> tempo, calm to urgent</div></div></div><div class='arrival'><strong id='arrival_title'>Arrival quality</strong><div class='small' id='arrival_text'>The system is settling into its current attractor.</div></div><div class='arrival'><strong id='forecast_title'>Forecast</strong><div class='small' id='forecast_text'>Current drift suggests the system will hold its present attractor.</div></div><div class='arrival'><strong id='forecast_rival_title'>Rival attractor</strong><div class='small' id='forecast_rival_text'>No competing pull is currently dominant.</div></div><div class='dim-grid' id='dim_grid'></div></div>
<div class='panel'><h2>EVENT TIMELINE</h2><div id='timeline' class='timeline'></div></div>
<div class='panel'><h2>PATTERN FEED</h2><div id='patterns' class='patterns'></div></div>
<div class='panel'><h2>TRANSITIONS</h2><div id='transition_log' class='transition-log'></div></div>
<div class='panel' id='cue_panel' style='display:none'><h2>CUE LIST</h2><div id='cue_status' class='small' style='margin-bottom:8px'></div><div id='cue_list' class='cue-list'></div></div>
<div class='panel'><details class='debug-panel'><summary>DEBUG / INJECT EVENT</summary><p class='help'>Use this for simulation and testing only. It is intentionally tucked away from primary controls.</p><select id='type'><option value='sensor_event'>sensor_event</option><option value='human_input'>human_input</option></select><input id='source' value='dashboard'><textarea id='payload'>{"text":"raise the tension"}</textarea><button onclick='inject()'>Send event</button></details></div>
</div></div><div id='toast' class='toast'></div><script>
const phaseColors={intro:'#f5e6c8',act_1:'#00979a',intermission:'#7ad4c2',act_2:'#ff8a86',outro:'#d9d9d9',idle:'#f4f4f4',emergency_stop:'#ff5f56'};
const phaseSignatures={intro:'The room is opening, porous and attentive.',act_1:'The engine has traction and intent.',intermission:'A suspended pocket where breath returns.',act_2:'Heat, consequence, and irreversible motion.',outro:'Release, residue, and afterimage.',idle:'A threshold field waiting for motion.'};
const regionAtmospheres={intro:{bg:'linear-gradient(180deg,#efe2c7,#f7f2e8)',glow:'radial-gradient(circle at 50% 10%, rgba(245,230,200,.55), transparent 34%)',panel:'rgba(255,250,244,.88)',line:'rgba(185,165,130,.35)'},act_1:{bg:'linear-gradient(180deg,#d7f0ed,#eef8f7)',glow:'radial-gradient(circle at 20% 20%, rgba(0,151,154,.18), transparent 30%), radial-gradient(circle at 80% 0%, rgba(0,151,154,.12), transparent 28%)',panel:'rgba(245,255,255,.86)',line:'rgba(0,151,154,.25)'},intermission:{bg:'linear-gradient(180deg,#e7faf5,#f7fffc)',glow:'radial-gradient(circle at 50% 20%, rgba(122,212,194,.22), transparent 33%)',panel:'rgba(250,255,253,.88)',line:'rgba(122,212,194,.28)'},act_2:{bg:'linear-gradient(180deg,#ffe6e4,#fff4f3)',glow:'radial-gradient(circle at 75% 18%, rgba(255,138,134,.24), transparent 30%), radial-gradient(circle at 20% 80%, rgba(255,95,86,.12), transparent 24%)',panel:'rgba(255,248,247,.88)',line:'rgba(255,138,134,.30)'},outro:{bg:'linear-gradient(180deg,#ececec,#fafafa)',glow:'radial-gradient(circle at 50% 10%, rgba(180,180,180,.18), transparent 34%)',panel:'rgba(255,255,255,.86)',line:'rgba(170,170,170,.28)'},idle:{bg:'linear-gradient(180deg,#e8e8e8,#f9f9f9)',glow:'transparent',panel:'rgba(255,255,255,.9)',line:'rgba(217,217,217,1)'}};
const regionRects={intro:{x:40,y:120,w:150,h:70},act_1:{x:190,y:80,w:160,h:70},intermission:{x:40,y:140,w:110,h:40},act_2:{x:340,y:30,w:180,h:90},outro:{x:10,y:150,w:80,h:30}};
function regionCenter(name){const r=regionRects[name]; return r ? [r.x + r.w/2, r.y + r.h/2] : [280,120]}
const phaseTrail=[];
const phaseHistory=[];
let previousRegion=null;
let transitionFxTimer=null;
let cueFxTimer=null;
function iconFor(type){return ({sensor_event:'◉',human_input:'◆',output_command:'▶',system:'■'})[type]||'·'}
async function post(path,data){const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); if(!res.ok) throw new Error(`${path} ${res.status}`); return res}
let toastTimer=null
function showToast(message, kind='ok'){const el=document.getElementById('toast'); el.textContent=message; el.className=`toast show ${kind==='error'?'error':kind==='transition'?'transition':''}`.trim(); clearTimeout(toastTimer); toastTimer=setTimeout(()=>{el.className='toast'}, kind==='transition'?3200:2200)}
function applyAtmosphere(region, transitioning=false){const a=regionAtmospheres[region]||regionAtmospheres.idle; const body=document.body; body.style.setProperty('--scene-bg', a.bg); body.style.setProperty('--scene-glow', a.glow); body.style.setProperty('--panel-bg', a.panel); body.style.setProperty('--panel-line', a.line); body.classList.toggle('transitioning', !!transitioning); if(transitionFxTimer) clearTimeout(transitionFxTimer); if(transitioning){transitionFxTimer=setTimeout(()=>body.classList.remove('transitioning'), 900)}}
function pulseCueEffect(){const body=document.body; body.style.setProperty('--cue-flash','radial-gradient(circle at 50% 50%, rgba(255,255,255,.38), rgba(0,151,154,.12) 34%, transparent 62%)'); body.classList.add('cue-firing'); if(cueFxTimer) clearTimeout(cueFxTimer); cueFxTimer=setTimeout(()=>body.classList.remove('cue-firing'), 280)}
function applyConfidenceMood(level){const body=document.body; body.classList.remove('confidence-low-body','confidence-mid-body','confidence-high-body'); body.classList.add(`confidence-${level}-body`)}
async function control(action,data={}){if(action==='emergency_stop' && !confirm('Emergency stop will halt the live engine immediately. Continue?')) return; try{await post('/control',{action,...data}); showToast(`Action sent: ${action}`); await refresh()}catch(err){showToast(`Action failed: ${action}`,'error')}}
async function phase(name){await control('transition',{phase:name})}
async function setEnergy(){await control('set_energy',{target_energy:parseFloat(document.getElementById('energy_input').value||'0.5')})}
async function inject(){try{await post('/inject',{type:document.getElementById('type').value,source:document.getElementById('source').value,payload:JSON.parse(document.getElementById('payload').value)}); showToast('Injected test event'); await refresh()}catch(err){showToast('Inject failed','error')}}
async function fireCue(n){try{pulseCueEffect(); await post('/cue',{cue:n}); showToast(`Cue fired: ${n}`); await refresh()}catch(err){showToast(`Cue failed: ${n}`,'error')}}
function renderTimeline(events){const el=document.getElementById('timeline');if(!events.length){el.innerHTML=`<div class='empty'>No events yet.</div>`;return}el.innerHTML=events.slice().reverse().map(event=>{const stamp=new Date(event.timestamp*1000).toLocaleTimeString();return `<div class='event'><span class='badge'>${iconFor(event.type)}</span><strong>${stamp}</strong> <span>${event.type}</span> <span class='small'>${event.source}</span><pre>${JSON.stringify(event.payload,null,2)}</pre></div>`}).join('')}
function renderPatterns(patterns){const el=document.getElementById('patterns');if(!patterns.length){el.innerHTML=`<div class='empty'>No learned patterns yet.</div>`;return}el.innerHTML=patterns.slice().reverse().map(p=>`<div class='event'><strong>${p.trigger||'pattern'}</strong><div>${p.outcome||p.summary||''}</div><div class='small'>success ${Number(p.success||0).toFixed(2)}</div></div>`).join('')}
function renderOutputs(outputs){const entries=Object.entries(outputs);document.getElementById('outputs_badge').textContent=`outputs: ${entries.length}`;const serialized=entries.map(([,state])=>JSON.stringify(state).toLowerCase());const unhealthy=serialized.filter(s=>s.includes('error')||s.includes('fail'));const thin=entries.length===0;const confidence=unhealthy.length? 'low' : thin ? 'mid' : 'high';const health=document.getElementById('health_badge');health.textContent=unhealthy.length?`system: degraded (${unhealthy.length})`:thin?'system: provisional':'system: healthy';health.className=`badge-soft health-badge ${unhealthy.length?'health-warn':'health-good'} confidence-${confidence}`;const confidenceBadge=document.getElementById('confidence_badge');confidenceBadge.textContent=`confidence: ${confidence}`;confidenceBadge.className=`badge-soft confidence-${confidence}`;document.getElementById('outputs').innerHTML=entries.length?entries.map(([name,state])=>`<div class='event'><strong>${name}</strong><pre>${JSON.stringify(state,null,2)}</pre></div>`).join(''):`<div class='empty'>No output adapters reporting yet.</div>`}
function renderCues(cueInfo){if(!cueInfo||!cueInfo.cues){document.getElementById('cue_panel').style.display='none';return}document.getElementById('cue_panel').style.display='block';const el=document.getElementById('cue_list');document.getElementById('cue_status').textContent=`${cueInfo.name} — ${cueInfo.fired}/${cueInfo.total} fired`;el.innerHTML=cueInfo.cues.map(c=>`<div class='cue-row${c.fired?" fired":""}'><span class='cue-num'>${String(c.number).padStart(3,'0')}</span><span class='cue-desc'>${c.description}</span><span class='cue-targets'>→ ${c.targets.join(', ')}</span>${c.fired?'<span style="color:var(--teal);margin-left:8px">✓</span>':'<button class="cue-fire" onclick="fireCue('+c.number+')">FIRE</button>'}</div>`).join('')}
function rotate(el,value){el.style.transform=`translateX(-50%) rotate(${(-90 + value*180)}deg)`}
function setGauge(current,target){document.getElementById('energy').textContent=current.toFixed(2);document.getElementById('target').textContent=target.toFixed(2);document.getElementById('gauge').style.setProperty('--energy',current.toFixed(2));rotate(document.getElementById('needle'),current);rotate(document.getElementById('targetNeedle'),target)}
function renderMatrix(matrix){const panel=document.getElementById('matrix_panel');if(!matrix){panel.style.display='none';document.getElementById('transition_log').innerHTML='<div class="empty">No matrix transitions yet.</div>';return}panel.style.display='block';document.getElementById('mode_badge').textContent=`mode: ${matrix.mode||'matrix'}`;document.getElementById('region_badge').textContent=`region: ${matrix.current_region||'none'}`;document.getElementById('matrix_current').textContent=`current: ${matrix.current_region||'none'}`;const last=(matrix.transitions||[])[(matrix.transitions||[]).length-1];document.getElementById('matrix_last_transition').textContent=last?`last: ${last.trigger} ${last.to}`:'last: none';const legend=document.getElementById('matrix_legend');legend.innerHTML=(matrix.regions||[]).map(r=>`<span class='pill'><span class='sw' style='background:${phaseColors[r]||'#ddd'}'></span>${r}</span>`).join('');const dims=matrix.dimensions||{};const dimEntries=Object.entries(dims);document.getElementById('dim_grid').innerHTML=dimEntries.map(([name,val])=>{let pct=name==='tempo'?Math.max(0,Math.min(1,(val-20)/120)):name==='color_temp'?Math.max(0,Math.min(1,(val-153)/(6535-153))):Math.max(0,Math.min(1,val));return `<div class='dim'><strong>${name}</strong><div class='small'>${typeof val==='number'?val.toFixed(name==='tempo'||name==='color_temp'?0:2):val}</div><div class='bar'><span style='width:${(pct*100).toFixed(1)}%'></span></div></div>`}).join('');const svg=document.getElementById('phase_space_svg');const currentEnergy=Number(dims.energy||0);const currentTempo=Number(dims.tempo||20);const dotX=40 + currentEnergy*480;const dotY=210 - ((currentTempo-20)/120)*180;phaseTrail.push([dotX,dotY]);while(phaseTrail.length>18) phaseTrail.shift();phaseHistory.push({x:dotX,y:dotY,region:matrix.current_region||'none'});while(phaseHistory.length>120) phaseHistory.shift();const trail=phaseTrail.map((p,i)=>`<circle cx='${p[0]}' cy='${p[1]}' r='${Math.max(2, i/3)}' fill='rgba(10,10,10,${(i+1)/phaseTrail.length*0.25})'/>`).join('');const path=phaseTrail.length>1?`<polyline points='${phaseTrail.map(p=>p.join(',')).join(' ')}' fill='none' stroke='rgba(0,151,154,.35)' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>`:'';const historyCloud=phaseHistory.map((p,i)=>`<circle cx='${p.x}' cy='${p.y}' r='2' fill='${phaseColors[p.region]||'#ccc'}' opacity='${0.04 + (i/phaseHistory.length)*0.12}'/>`).join('');const vx=(phaseTrail.at(-1)?.[0]||dotX)-(phaseTrail.at(-2)?.[0]||dotX);const vy=(phaseTrail.at(-1)?.[1]||dotY)-(phaseTrail.at(-2)?.[1]||dotY);const drift=Math.hypot(vx,vy);const driftText=drift>28?'surging':drift>10?'moving':'settling';document.getElementById('matrix_drift').textContent=`drift: ${driftText}`;const forecastPoint=[dotX + vx*6, dotY + vy*6];const candidates=(matrix.regions||[]).filter(r=>r!==matrix.current_region).map(name=>{const [cx,cy]=regionCenter(name); return {name, dist: Math.hypot(forecastPoint[0]-cx, forecastPoint[1]-cy)}}).sort((a,b)=>a.dist-b.dist);const nearest=candidates[0];const rival=candidates[1];const forecast=drift<=6 || !nearest ? 'holding' : nearest.dist < 150 ? `tending ${nearest.name}` : 'holding';const forecastConfidence=forecast==='holding' ? (drift<=3 ? 'high' : 'medium') : (!rival ? 'high' : (rival.dist - nearest.dist > 45 ? 'high' : rival.dist - nearest.dist > 20 ? 'medium' : 'low'));const tension=forecast==='holding' ? 'low' : (forecastConfidence==='low' ? 'high' : forecastConfidence==='medium' ? 'medium' : 'low');document.getElementById('matrix_forecast').textContent=`forecast: ${forecast} · ${forecastConfidence}`;document.getElementById('forecast_title').textContent=forecast==='holding'?'Forecast':'Likely next attractor';document.getElementById('forecast_text').textContent=forecast==='holding'?'Current drift suggests the system will hold its present attractor.':`If present motion holds, the field is tending toward ${nearest.name} with ${forecastConfidence} confidence and ${tension} tension.`;document.getElementById('forecast_rival_title').textContent=forecast==='holding'?'Field tension':'Rival attractor';document.getElementById('forecast_rival_text').textContent=forecast==='holding'?(driftText==='settling'?'No competing pull is currently dominant.':`Motion is active, but no rival attractor has yet taken precedence.`):(rival?`${rival.name} is the secondary pull, trailing ${nearest.name} by ${Math.round(rival.dist - nearest.dist)} units.`:'No rival attractor is currently close enough to matter.');const regionChanged=previousRegion!==null && previousRegion!==matrix.current_region;if(regionChanged){showToast(`Crossing into ${String(matrix.current_region||'unknown').toUpperCase()}`,'transition'); applyAtmosphere(matrix.current_region||'idle', true)}previousRegion=matrix.current_region;document.getElementById('arrival_title').textContent=regionChanged?`Arrival: ${matrix.current_region||'none'}`:'Arrival quality';document.getElementById('arrival_text').textContent=regionChanged?`A threshold was crossed. The system has entered ${matrix.current_region||'a new region'} and is now re-orienting its motion around that attractor.`:driftText==='surging'?'The field is still carrying momentum. Expect more movement before it settles.':driftText==='moving'?'The system is actively traversing the phase space, but it is no longer chaotic.':'The system is settling into its current attractor with low drift.';svg.innerHTML=`<defs><filter id='glow'><feGaussianBlur stdDeviation='6' result='blur'/><feMerge><feMergeNode in='blur'/><feMergeNode in='SourceGraphic'/></feMerge></filter></defs><rect x='0' y='0' width='560' height='240' fill='white'/>${historyCloud}<line x1='40' y1='210' x2='520' y2='210' stroke='#bbb'/><line x1='40' y1='30' x2='40' y2='210' stroke='#bbb'/><text x='525' y='214'>energy</text><text x='8' y='26'>tempo</text>${Object.entries(regionRects).map(([name,r])=>`<rect x='${r.x}' y='${r.y}' width='${r.w}' height='${r.h}' fill='${phaseColors[name]||'#ddd'}' opacity='${matrix.current_region===name?0.82:0.28}' stroke='${matrix.current_region===name?'#0a0a0a':'#999'}' rx='12'/><text x='${r.x+8}' y='${r.y+18}'>${name}</text>`).join('')}<line x1='${dotX}' y1='30' x2='${dotX}' y2='210' stroke='rgba(0,151,154,.18)' stroke-dasharray='4 4'/><line x1='40' y1='${dotY}' x2='520' y2='${dotY}' stroke='rgba(0,151,154,.18)' stroke-dasharray='4 4'/>${path}${trail}<circle cx='${dotX}' cy='${dotY}' r='14' fill='rgba(0,151,154,.18)' filter='url(#glow)'/><circle cx='${dotX}' cy='${dotY}' r='8' fill='#0a0a0a' stroke='#fff' stroke-width='2'/><text x='${dotX+10}' y='${dotY-10}'>${matrix.current_region||'none'}</text>`;document.getElementById('transition_log').innerHTML=(matrix.transitions||[]).length?(matrix.transitions||[]).slice().reverse().map(t=>`<div class='event'><strong>${t.trigger}</strong><div>${t.from||'∅'} → ${t.to}</div><div class='small'>${t.ts}</div></div>`).join(''):`<div class='empty'>No matrix transitions yet.</div>`}
async function refresh(){const snap=await (await fetch('/snapshot')).json();const state=snap.state||{};const perf=snap.performance||{};const phase=state.phase||snap.matrix?.current_region||'idle';const phaseEl=document.getElementById('phase');phaseEl.textContent=phase.toUpperCase();phaseEl.style.color=perf.phase_color||phaseColors[phase]||'#888';document.getElementById('phase_signature').textContent=phaseSignatures[phase]||phaseSignatures.idle;applyAtmosphere(phase,false);document.getElementById('allowed').textContent=(perf.allowed_outputs||[]).join(', ')||'all';document.getElementById('phase_timer').textContent=`${Number(perf.phase_runtime||0).toFixed(1)}s`;document.getElementById('show_timer').textContent=`${Number(perf.runtime||0).toFixed(1)}s`;document.getElementById('events_badge').textContent=`events: ${(snap.timeline||[]).length}`;setGauge(Number(state.energy_level||0),Number(perf.target_energy||0));renderTimeline(snap.timeline||[]);renderPatterns(snap.patterns||[]);renderOutputs(snap.outputs||{});applyConfidenceMood(document.getElementById('confidence_badge').textContent.split(': ')[1]||'high');renderCues(snap.cues||null);renderMatrix(snap.matrix||null)}
const stream=new EventSource('/events');stream.onmessage=()=>refresh();refresh();setInterval(refresh,3000)
</script></body></html>"""
