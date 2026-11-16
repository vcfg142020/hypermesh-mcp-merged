"""按客户端 mcp.json 里配置的 command/args/env 原样启动，验证客户端会看到什么。

用法
----
    python accept.py                    # 自动找本机已存在的 mcp.json
    python accept.py <path/to/mcp.json>  # 显式指定

自动查找顺序（找到第一个含 mcpServers.hypermesh 的为止）：
    $HWMCP_MCP_JSON
    ~/.workbuddy/mcp.json          （WorkBuddy）
    ~/AppData/Roaming/Claude/claude_desktop_config.json
    script 同级的 mcp.json
"""
import json, os, subprocess, sys, threading, time
from pathlib import Path

CANDIDATES = [
    os.environ.get("HWMCP_MCP_JSON"),
    Path.home() / ".workbuddy" / "mcp.json",
    Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
    Path(__file__).resolve().parent / "mcp.json",
]


def locate() -> Path:
    if len(sys.argv) > 1:
        p = Path(sys.argv[1]).expanduser()
        if not p.is_file():
            sys.exit(f"配置文件不存在：{p}")
        return p
    for c in CANDIDATES:
        if not c:
            continue
        p = Path(c)
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue
        if "hypermesh" in (data.get("mcpServers") or {}):
            return p
    sys.exit("没找到含 mcpServers.hypermesh 的 mcp.json。请把路径作为第一个参数传入，"
             "或设置环境变量 HWMCP_MCP_JSON。参考 mcp.json.example。")


CFG_PATH = locate()
print(f"配置文件：{CFG_PATH}")
CFG = json.loads(CFG_PATH.read_text(encoding="utf-8-sig"))
entry = CFG["mcpServers"]["hypermesh"]
entry["args"] = [os.path.expandvars(os.path.expanduser(a)) for a in entry["args"]]
env = dict(os.environ); env.update(entry.get("env") or {})
print(f"启动命令：{entry['command']} {' '.join(entry['args'])}")

p = subprocess.Popen([entry["command"], *entry["args"]], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     env=env, text=True, encoding="utf-8", bufsize=1)
box = {}
def drain():
    for line in p.stdout:
        line=line.strip()
        if line:
            try: m=json.loads(line)
            except json.JSONDecodeError: continue
            box[m.get("id")]=m
threading.Thread(target=drain, daemon=True).start()

def rpc(i, method, params):
    p.stdin.write(json.dumps({"jsonrpc":"2.0","id":i,"method":method,"params":params})+"\n")
    p.stdin.flush()
    t0=time.perf_counter()
    while time.perf_counter()-t0 < 200:
        if i in box: return box.pop(i), time.perf_counter()-t0
        if p.poll() is not None: return None, time.perf_counter()-t0
        time.sleep(0.02)
    return None, time.perf_counter()-t0

init, dt = rpc(1,"initialize",{"protocolVersion":"2024-11-05","capabilities":{},
                               "clientInfo":{"name":"accept","version":"1"}})
p.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"})+"\n"); p.stdin.flush()
print(f"a) initialize {dt*1000:.0f} ms  -> {'OK' if init else 'FAIL'}")

tl,_ = rpc(2,"tools/list",{})
tools=[t["name"] for t in tl["result"]["tools"]] if tl else []
hm=[t for t in tools if t.startswith("hm_")]
print(f"b) tools/list {len(tools)} 个（hm_ 开头 {len(hm)} 个）")

st,_ = rpc(3,"tools/call",{"name":"hm_status","arguments":{}})
prof = None
if st:
    try: prof = json.loads(st["result"]["content"][0]["text"]).get("profile")
    except Exception: prof = "解析失败"
print(f"c) hm_status profile = {prof}  -> {'OK' if prof=='OptiStruct' else 'FAIL'}")

p.terminate()
try: p.wait(timeout=15)
except Exception: p.kill()
print("已关闭验收会话")
