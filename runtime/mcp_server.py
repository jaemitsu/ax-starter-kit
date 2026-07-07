#!/usr/bin/env python3
"""AX Grounding & Action MCP 서버 (stdio, JSON-RPC 2.0 / MCP 2025-06-18).

설계 원칙: 범용 질의(run_cypher/run_sparql)를 노출하지 않는다.
좁은 목적의 도구 6종만 제공하며, 쓰기는 전부 Action Gateway를 경유한다.

Claude Desktop / Claude Code 등록 예:
  {"mcpServers": {"ax-ontology": {"command": "python3",
    "args": ["<경로>/runtime/mcp_server.py", "<경로>/domains/ad-reporting",
             "<경로>/runtime/sample-instances.ttl"]}}}
"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway, GatewayError

TOOLS = [
    {"name": "get_object",
     "description": "온톨로지 객체 조회: 타입, 정의, 상태·속성, 들어오고 나가는 관계, 책임자(owner)를 반환한다.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "description": "객체 ID (예: run2)"}}, "required": ["id"]}},
    {"name": "find_objects",
     "description": "타입(과 선택적 상태)으로 객체 목록 조회. 예: 실패 상태의 ReportRun 전부.",
     "inputSchema": {"type": "object", "properties": {"type": {"type": "string"}, "status": {"type": "string"}}, "required": ["type"]}},
    {"name": "trace_lineage",
     "description": "데이터 계보 추적: ReportRun→CleanDataSet→RawAdPerformance→Campaign 상류 사슬을 반환한다. '이 숫자는 어디서 왔나'에 답한다.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "check_rules",
     "description": "현재 인스턴스 전체에 대해 온톨로지 규칙(SHACL)을 평가하고 위반 목록(규칙 ID, 대상, 위반 시 행동)을 반환한다.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "resolve_term",
     "description": "업무 용어를 온톨로지 대표어·객체로 해석한다 (동의어 사전). 예: '보정 건' → ExceptionCase.",
     "inputSchema": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]}},
    {"name": "execute_action",
     "description": "Action Gateway를 통한 행동 실행. 온톨로지에 정의된 액션만 가능하며 권한·자율성·승인·멱등성이 집행되고 감사 로그가 남는다. 거부 시 사유가 반환된다.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string"}, "target": {"type": "string"},
         "actor": {"type": "string", "description": "예: AI-Agent, 데이터 QA 담당"},
         "approval": {"type": "string", "description": "조건부 승인 토큰 (예: 팀장:김OO)"},
         "params": {"type": "object"}}, "required": ["action", "target", "actor"]}},
]

class Server:
    def __init__(self, domain_dir, instances):
        self.store = OntologyStore(domain_dir, instances)
        self.gw = ActionGateway(self.store)

    def call_tool(self, name, args):
        s, gw = self.store, self.gw
        if name == "get_object":
            return s.get_object(args["id"]) or {"error": f"객체 없음: {args['id']}"}
        if name == "find_objects":
            return {"ids": s.find_by_type(args["type"], args.get("status"))}
        if name == "trace_lineage":
            return s.trace_lineage(args["id"])
        if name == "check_rules":
            return {"violations": s.check_rules()}
        if name == "resolve_term":
            return s.resolve_term(args["term"]) or {"error": "미등록 용어", "hint": list(s.objects)}
        if name == "execute_action":
            try:
                eff = gw.execute(args["action"], args["target"], args["actor"],
                                 approval=args.get("approval"), **(args.get("params") or {}))
                return {"result": "success", "effect": eff}
            except GatewayError as e:
                return {"result": "rejected", "reason": str(e)}
        raise ValueError(f"unknown tool {name}")

    def handle(self, req):
        m, rid = req.get("method"), req.get("id")
        if m == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ax-ontology", "version": "1.0.0"}}}
        if m == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
        if m == "tools/call":
            p = req["params"]
            try:
                out = self.call_tool(p["name"], p.get("arguments") or {})
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}],
                    "isError": False}}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": f"오류: {e}"}], "isError": True}}
        if rid is not None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {m}"}}
        return None  # notification은 무응답

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line: continue
            try: req = json.loads(line)
            except json.JSONDecodeError: continue
            resp = self.handle(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n"); sys.stdout.flush()

if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    domain = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "domains/ad-reporting")
    inst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(base, "runtime/sample-instances.ttl")
    Server(domain, inst).run()
