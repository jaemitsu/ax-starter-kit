#!/usr/bin/env python3
"""운영 대시보드 생성기 — 시나리오 v2 실행 후 스냅샷(객체·규칙·감사 로그)을 자체완결 HTML로.
python dashboard/gen_dashboard.py → dashboard/ax-dashboard.html"""
import os, sys, json
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.scenario_v2 import run

def snapshot():
    s, gw, loop, log = run(verbose=False)
    objs = []
    for t in s.objects:
        for oid in s.find_by_type(t):
            o = s.get_object(oid)
            objs.append({"id": oid, "type": t, "status": o["properties"].get("status", "-"),
                         "props": o["properties"], "out": o["linksOut"]})
    return {"objects": objs, "violations": s.check_rules(), "audit": gw.audit.records,
            "actions": [{"name": a["name"], "autonomy": a["autonomy"], "target": a["target"],
                         "approval": a.get("approval")} for a in s.doc["actions"]],
            "domain": s.doc["ontology"]["domain"], "version": s.doc["ontology"]["version"]}

def mermaid(data):
    lines = ["graph LR"]
    shown = set()
    for o in data["objects"]:
        nid = o["id"]; shown.add(nid)
        cls = {"완료": "ok", "정상": "ok", "해결": "ok", "전달됨": "ok", "인증": "ok", "활성": "ok",
               "실패": "bad", "오픈": "bad", "재생성": "warn", "생성 중": "warn"}.get(o["status"], "n")
        lines.append(f'  {nid}["{nid}<br/>{o["type"]}<br/>({o["status"]})"]:::{cls}')
    for o in data["objects"]:
        for l in o["out"]:
            if l["target"] in shown:
                lines.append(f'  {o["id"]} -- {l["predicate"]} --> {l["target"]}')
    lines.append("  classDef ok fill:#e9f7f1,stroke:#0e8a5f;")
    lines.append("  classDef bad fill:#fdeeec,stroke:#c0392b;")
    lines.append("  classDef warn fill:#fdf6e9,stroke:#b7791f;")
    lines.append("  classDef n fill:#eaf0ff,stroke:#2456d6;")
    return "\n".join(lines)

def build():
    d = snapshot()
    def _links(o):
        return ", ".join(l["predicate"] + "→" + l["target"] for l in o["out"]) or "-"
    rows_obj = "".join(
        f"<tr><td><code>{o['id']}</code></td><td>{o['type']}</td><td>{o['status']}</td>"
        f"<td>{_links(o)}</td></tr>"
        for o in sorted(d["objects"], key=lambda x: x["type"]))
    rows_audit = "".join(
        f"<tr class='{r['result']}'><td>{r['ts'].split('T')[1]}</td><td>{r['actor']}</td>"
        f"<td><code>{r['action']}</code></td><td>{r['target']}</td><td>{r['result']}</td>"
        f"<td>{', '.join(r.get('grounds') or [])}</td>"
        f"<td>{(r.get('reason') or '')[:70]}</td></tr>" for r in d["audit"])
    rows_act = "".join(
        f"<tr><td><code>{a['name']}</code></td><td>{a['target']}</td><td>{a['autonomy']}</td><td>{a['approval']}</td></tr>"
        for a in d["actions"])
    n_ok = sum(1 for r in d["audit"] if r["result"] == "success")
    n_rej = len(d["audit"]) - n_ok
    grounded = sum(1 for r in d["audit"] if r["result"] == "success" and r.get("grounds"))
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>AX 운영 대시보드 — {d['domain']} v{d['version']}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
 body{{font-family:'Malgun Gothic',sans-serif;margin:0;background:#f6f8fb;color:#1a2233;}}
 header{{background:linear-gradient(135deg,#12204d,#2456d6);color:#fff;padding:26px 32px;}}
 h1{{margin:0;font-size:22px;}} .sub{{opacity:.8;font-size:13px;margin-top:4px;}}
 .wrap{{max-width:1150px;margin:0 auto;padding:24px 32px;}}
 .cards{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px;}}
 .card{{background:#fff;border:1px solid #e3e7ef;border-radius:12px;padding:14px 22px;min-width:150px;}}
 .card b{{font-size:26px;display:block;}} .card span{{color:#5a6478;font-size:13px;}}
 h2{{font-size:17px;border-left:5px solid #2456d6;padding-left:10px;margin:28px 0 10px;}}
 table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;}}
 th{{background:#0f1f4d;color:#fff;text-align:left;padding:7px 10px;}}
 td{{border-bottom:1px solid #e3e7ef;padding:6px 10px;}}
 tr.rejected td{{background:#fdeeec;}} tr.success td{{background:#fbfdfb;}}
 .mer{{background:#fff;border:1px solid #e3e7ef;border-radius:12px;padding:16px;overflow-x:auto;}}
 .ok{{color:#0e8a5f;font-weight:700;}}
</style></head><body>
<header><h1>AX 운영 대시보드 — {d['domain']} 온톨로지 v{d['version']}</h1>
<div class="sub">판단 루프 시나리오 실행 후 스냅샷 · 생성: gen_dashboard.py</div></header>
<div class="wrap">
<div class="cards">
 <div class="card"><b>{len(d['objects'])}</b><span>객체 인스턴스</span></div>
 <div class="card"><b class="ok">{len(d['violations'])}</b><span>현재 규칙 위반</span></div>
 <div class="card"><b>{n_ok} / {n_rej}</b><span>액션 성공 / 거부</span></div>
 <div class="card"><b class="ok">{grounded}/{n_ok}</b><span>근거 있는 성공 행동</span></div>
</div>
<h2>인스턴스 그래프 (상태 색상)</h2>
<div class="mer"><pre class="mermaid">{mermaid(d)}</pre></div>
<h2>감사 로그 — 모든 행동과 그 근거</h2>
<table><tr><th>시각</th><th>주체</th><th>액션</th><th>대상</th><th>결과</th><th>근거(grounds)</th><th>거부 사유</th></tr>{rows_audit}</table>
<h2>객체 인벤토리</h2>
<table><tr><th>ID</th><th>타입</th><th>상태</th><th>관계</th></tr>{rows_obj}</table>
<h2>액션 카탈로그 — AI 자율성 정책</h2>
<table><tr><th>액션</th><th>대상</th><th>자율성</th><th>승인</th></tr>{rows_act}</table>
</div><script>mermaid.initialize({{startOnLoad:true,securityLevel:'loose'}});</script></body></html>"""
    out = os.path.join(BASE, "dashboard", "ax-dashboard.html")
    open(out, "w", encoding="utf-8").write(html)
    print("생성:", out, f"({len(html)//1024}KB)")

if __name__ == "__main__":
    build()
