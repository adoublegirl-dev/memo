"""Memo Boot Server.

A tiny bootstrap web server that starts instantly on port 9120, shows a cinematic
Memo boot screen, waits for the real dashboard on MEMO_DASHBOARD_TARGET_PORT, and
then proxies requests to it. This prevents the browser from showing connection
refused while Memo services are still warming up.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BOOT_PORT = int(os.getenv("MEMO_BOOT_PORT", "9120"))
TARGET_HOST = os.getenv("MEMO_DASHBOARD_TARGET_HOST", "127.0.0.1")
TARGET_PORT = int(os.getenv("MEMO_DASHBOARD_TARGET_PORT", "9121"))
STARTED_AT = time.time()

BOOT_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Memo Core Boot</title>
<style>
:root{--bg:#05070d;--panel:rgba(15,23,42,.46);--line:rgba(188,170,116,.22);--gold:#d7c17a;--green:#8bd8b4;--text:#f2efe5;--muted:#8f9aad;--blue:#7aa2ff;--danger:#ff8b8b}
*{box-sizing:border-box}body{margin:0;min-height:100vh;overflow:hidden;background:radial-gradient(circle at 50% 45%,#172033 0,#070a12 42%,#03050a 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,"Microsoft YaHei",sans-serif;letter-spacing:.02em}
body:before{content:"";position:fixed;inset:0;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:64px 64px;mask-image:radial-gradient(circle at 50% 50%,black,transparent 72%);opacity:.5}body:after{content:"";position:fixed;inset:-20%;background:radial-gradient(circle at 22% 20%,rgba(215,193,122,.12),transparent 16%),radial-gradient(circle at 80% 30%,rgba(139,216,180,.10),transparent 18%),radial-gradient(circle at 55% 82%,rgba(122,162,255,.10),transparent 22%);filter:blur(10px);animation:nebula 12s ease-in-out infinite alternate}
.boot{position:relative;z-index:1;min-height:100vh;display:grid;grid-template-columns:minmax(360px,1fr) 390px;gap:32px;padding:42px;align-items:center}.space{position:relative;min-height:620px;display:grid;place-items:center}.core{position:relative;width:min(54vw,580px);aspect-ratio:1;display:grid;place-items:center}.halo{position:absolute;inset:12%;border:1px solid rgba(215,193,122,.22);border-radius:50%;box-shadow:0 0 80px rgba(215,193,122,.13),inset 0 0 70px rgba(139,216,180,.07);animation:pulse 3.8s ease-in-out infinite}.halo:before,.halo:after{content:"";position:absolute;inset:12%;border:1px solid rgba(139,216,180,.18);border-radius:50%;transform:rotateX(68deg) rotateZ(25deg);box-shadow:0 0 28px rgba(139,216,180,.12)}.halo:after{inset:20%;transform:rotateX(72deg) rotateZ(-35deg);border-color:rgba(122,162,255,.16)}
.orbit{position:absolute;inset:4%;border-radius:50%;border:1px solid rgba(255,255,255,.08);animation:spin 22s linear infinite}.orbit.o2{inset:18%;transform:rotate(35deg);animation-duration:16s}.orbit.o3{inset:29%;transform:rotate(-20deg);animation-duration:28s}.node{position:absolute;width:7px;height:7px;border-radius:50%;background:var(--gold);box-shadow:0 0 18px var(--gold)}.node.n1{top:10%;left:50%}.node.n2{right:13%;top:60%;background:var(--green);box-shadow:0 0 18px var(--green)}.node.n3{left:18%;bottom:22%;background:var(--blue);box-shadow:0 0 18px var(--blue)}
.singularity{width:168px;height:168px;border-radius:50%;background:radial-gradient(circle at 42% 38%,#f6e6a7 0 4%,#d7c17a 5% 9%,#384153 10% 36%,#080b13 52%,#020308 70%);box-shadow:0 0 36px rgba(215,193,122,.38),0 0 130px rgba(139,216,180,.18);position:relative}.singularity:after{content:"";position:absolute;left:-105px;right:-105px;top:72px;height:24px;border-radius:50%;background:linear-gradient(90deg,transparent,rgba(139,216,180,.05),rgba(215,193,122,.85),rgba(255,255,255,.95),rgba(215,193,122,.78),rgba(139,216,180,.06),transparent);filter:blur(.2px);transform:rotate(-8deg);box-shadow:0 0 28px rgba(215,193,122,.42)}
.brand{position:absolute;left:4px;top:8px}.eyebrow{color:var(--green);font-size:12px;letter-spacing:.28em;text-transform:uppercase}.brand h1{font-size:58px;line-height:.9;margin:12px 0 10px;letter-spacing:-.06em}.brand p{margin:0;color:var(--muted);max-width:560px;line-height:1.8}.ticks{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,rgba(215,193,122,.5) 0 1deg,transparent 1deg 12deg);mask:radial-gradient(circle,transparent 59%,black 60%,black 61%,transparent 62%);opacity:.28;animation:spin 45s linear infinite reverse}
.panel{border:1px solid var(--line);border-radius:28px;background:linear-gradient(135deg,rgba(15,23,42,.72),rgba(5,7,13,.45));backdrop-filter:blur(22px);box-shadow:0 24px 80px rgba(0,0,0,.36);padding:24px}.panel-head{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:18px}.panel-title{font-size:13px;color:var(--gold);letter-spacing:.22em;text-transform:uppercase}.timer{font-family:"JetBrains Mono",Consolas,monospace;color:var(--text);font-size:22px}.phase{font-size:25px;font-weight:720;letter-spacing:-.03em;margin:8px 0 4px}.sub{color:var(--muted);font-size:13px;line-height:1.7}.steps{display:grid;gap:10px;margin-top:18px}.step{display:grid;grid-template-columns:22px 1fr auto;gap:10px;align-items:center;padding:11px 12px;border:1px solid rgba(255,255,255,.08);border-radius:16px;background:rgba(255,255,255,.03);transition:all .3s ease}.dot{width:9px;height:9px;border-radius:50%;background:#465066;box-shadow:0 0 0 transparent}.step.active{border-color:rgba(215,193,122,.36);background:rgba(215,193,122,.08)}.step.active .dot{background:var(--gold);box-shadow:0 0 18px var(--gold);animation:blink 1s ease-in-out infinite}.step.done{border-color:rgba(139,216,180,.22)}.step.done .dot{background:var(--green);box-shadow:0 0 14px var(--green)}.step-name{font-size:14px}.step-code{font:12px "JetBrains Mono",Consolas,monospace;color:var(--muted)}.progress{height:7px;border-radius:999px;background:rgba(255,255,255,.07);overflow:hidden;margin-top:18px}.bar{height:100%;width:0;background:linear-gradient(90deg,var(--green),var(--gold));box-shadow:0 0 22px rgba(215,193,122,.5);transition:width .5s ease}.footer{display:flex;justify-content:space-between;align-items:center;margin-top:16px;color:var(--muted);font:12px "JetBrains Mono",Consolas,monospace}.ready{color:var(--green)}.waiting{color:var(--gold)}
@keyframes spin{to{rotate:360deg}}@keyframes pulse{50%{transform:scale(1.035);opacity:.72}}@keyframes blink{50%{opacity:.45}}@keyframes nebula{to{transform:translate3d(2%,-1%,0) scale(1.04)}}@media(max-width:900px){.boot{grid-template-columns:1fr;padding:24px;overflow:auto}.space{min-height:430px}.brand h1{font-size:42px}.panel{margin-top:-40px}.core{width:min(86vw,460px)}}
</style>
</head>
<body>
<div class="boot">
  <section class="space">
    <div class="brand">
      <div class="eyebrow">LOCAL PRIVATE AI CONTEXT HUB</div>
      <h1>MEMO<br/>CORE</h1>
      <p>秩序化长期记忆、Context Space、人格画像与行动线索正在进入同一张星图。那些零散的片段会被重新点亮，形成可追溯、可治理、可被再次唤起的关联。</p>
    </div>
    <div class="core" aria-hidden="true">
      <div class="ticks"></div><div class="orbit"><span class="node n1"></span></div><div class="orbit o2"><span class="node n2"></span></div><div class="orbit o3"><span class="node n3"></span></div><div class="halo"></div><div class="singularity"></div>
    </div>
  </section>
  <aside class="panel">
    <div class="panel-head"><div><div class="panel-title">BOOT SEQUENCE</div><div class="phase" id="phase">正在唤醒记忆核心</div><div class="sub" id="sub">建立本地私有上下文引擎的初始秩序。</div></div><div class="timer" id="timer">00:00</div></div>
    <div class="steps" id="steps"></div>
    <div class="progress"><div class="bar" id="bar"></div></div>
    <div class="footer"><span id="state" class="waiting">WAITING FOR DASHBOARD</span><span>PORT 9120 // MEMO</span></div>
  </aside>
</div>
<script>
const bootedAt=Date.now();
const steps=[
 ['runtime','校准本地运行环境','PYTHON RUNTIME'],
 ['database','开启记忆穹顶','DATABASE / MIGRATIONS'],
 ['index','构建记忆索引','VECTOR + BM25 + GRAPH'],
 ['relate','关联记忆星图','HEBBIAN LINKS'],
 ['space','挂载 Context Space','SPACE LAYER'],
 ['persona','同步人格画像','PERSONA SIGNALS'],
 ['spark','发现灵光节点','INSIGHT SPARKS'],
 ['dashboard','进入管理平台','DASHBOARD READY']
];
const phaseText=['正在唤醒记忆核心','正在构建记忆索引','正在关联长期记忆','正在梳理上下文空间','正在发现灵光节点','等待管理平台接管'];
const subText=['建立本地私有上下文引擎的初始秩序。','把散落片段压入可检索的轨道。','让相似、因果与共现关系重新发光。','把项目、产品、写作和行动放回各自星域。','寻找值得再次被想起的闪光点。','所有序列已完成，等待服务完全启动。'];
const elSteps=document.getElementById('steps');
elSteps.innerHTML=steps.map((s,i)=>`<div class="step" id="step-${i}"><span class="dot"></span><span class="step-name">${s[1]}</span><span class="step-code">${s[2]}</span></div>`).join('');
function paint(progress,ready){
 const done=Math.min(steps.length-1,Math.floor(progress*(steps.length-1)));
 steps.forEach((_,i)=>{const el=document.getElementById('step-'+i);el.className='step '+(ready||i<done?'done':i===done?'active':'')});
 document.getElementById('bar').style.width=Math.round(progress*100)+'%';
 const p=Math.min(phaseText.length-1,Math.floor(progress*(phaseText.length-1)));
 document.getElementById('phase').textContent=ready?'管理平台已就绪':phaseText[p];
 document.getElementById('sub').textContent=ready?'正在折叠启动舱，进入 Memo 管理平台。':subText[p];
 document.getElementById('state').textContent=ready?'ALL SYSTEMS READY':'WAITING FOR DASHBOARD';
 document.getElementById('state').className=ready?'ready':'waiting';
}
function tick(){const sec=Math.floor((Date.now()-bootedAt)/1000);document.getElementById('timer').textContent=String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0')}
async function poll(){
 tick();
 const elapsed=(Date.now()-bootedAt)/1000;
 let ready=false;
 try{const r=await fetch('/boot-health',{cache:'no-store'});const j=await r.json();ready=!!j.ready}catch(e){}
 const progress=ready?1:Math.min(.92,.08+elapsed/18);
 paint(progress,ready);
 if(ready){setTimeout(()=>location.reload(),850)} else setTimeout(poll,650);
}
poll();setInterval(tick,500);
</script>
</body>
</html>
"""


def dashboard_ready(timeout: float = 0.6) -> bool:
    try:
        conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=timeout)
        conn.request("GET", "/api/health")
        res = conn.getresponse()
        ok = 200 <= res.status < 300
        conn.close()
        return ok
    except Exception:
        return False


class BootHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path.startswith("/boot-health"):
            self._json({"ready": dashboard_ready(), "target": f"http://{TARGET_HOST}:{TARGET_PORT}", "elapsed": round(time.time() - STARTED_AT, 2)})
            return
        if dashboard_ready():
            self._proxy()
            return
        self._html(BOOT_HTML)

    def do_POST(self):
        if dashboard_ready():
            self._proxy()
            return
        self._json({"error": "dashboard is still starting"}, 503)

    def _html(self, content: str):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self):
        body = None
        if self.command in {"POST", "PUT", "PATCH"}:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else None
        try:
            conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=12)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection", "content-length"}}
            conn.request(self.command, self.path, body=body, headers=headers)
            res = conn.getresponse()
            data = res.read()
            self.send_response(res.status, res.reason)
            skip = {"transfer-encoding", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"}
            for k, v in res.getheaders():
                if k.lower() not in skip:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except Exception as exc:
            self._json({"error": f"proxy failed: {exc}"}, 502)


def wait_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) != 0


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", BOOT_PORT), BootHandler)
    print(f"Memo Boot Server → http://localhost:{BOOT_PORT}  proxy target {TARGET_HOST}:{TARGET_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Memo Boot Server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
