"""按 mcp.json 里配置的 command/args/env 原样启动，验证客户端会看到什么。"""
import json, os, subprocess, sys, threading, time
from pathlib import Path

CFG = json.loads(Path(r"C:/Users/2025057553/.workbuddy/mcp.json").read_text(encoding="utf-8"))
entry = CFG["mcpServers"]["hypermesh"]
env = dict(os.environ); env.update(entry.get("env") or {})

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
