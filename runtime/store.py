"""OntologyStore — 온톨로지 정본(YAML)과 인스턴스 그래프를 결합한 런타임 저장소.
Grounding API의 본체: get_object / trace_lineage / check_rules / blocking_cases / resolve_term
"""
import os, sys
from rdflib import Graph, Namespace, Literal, RDF, XSD

_TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, _TOOLS)
import validate as V  # tools/validate.py 재사용 (build_owl, build_shapes, load)

AX = Namespace("https://example.co/ax/ont#")
DT = {"decimal": XSD.decimal, "integer": XSD.integer, "date": XSD.date}

class OntologyStore:
    def __init__(self, domain_dir, instances_path):
        self.doc = V.load(os.path.join(domain_dir, "ontology-state.yaml"))
        self.owl = V.build_owl(self.doc)
        self.shapes, _ = V.build_shapes(self.doc)
        self.g = Graph()
        self.g.parse(instances_path)
        self.objects = {o["name"]: o for o in self.doc["objectTypes"]}
        self.actions = {a["name"]: a for a in self.doc["actions"]}
        self.glossary = (self.doc.get("ontology") or {}).get("glossary", []) or []

    # ── 기본 유틸 ──
    def uri(self, local): return AX[local]
    def local(self, u): return str(u).split("#")[-1]
    def exists(self, node_id): return (self.uri(node_id), None, None) in self.g

    def type_of(self, node_id):
        for t in self.g.objects(self.uri(node_id), RDF.type):
            return self.local(t)
        return None

    # ── Grounding: 객체 조회 ──
    def get_object(self, node_id):
        if not self.exists(node_id): return None
        n = self.uri(node_id)
        props, links_out, links_in = {}, [], []
        for p, o in self.g.predicate_objects(n):
            if p == RDF.type: continue
            if isinstance(o, Literal): props[self.local(p)] = str(o)
            else: links_out.append({"predicate": self.local(p), "target": self.local(o)})
        for s, p in self.g.subject_predicates(n):
            links_in.append({"predicate": self.local(p), "source": self.local(s)})
        t = self.type_of(node_id)
        spec = self.objects.get(t) or {}
        return {"id": node_id, "type": t, "definition": spec.get("definition"),
                "owner": spec.get("owner"), "properties": props,
                "linksOut": links_out, "linksIn": links_in}

    def status(self, node_id):
        o = self.get_object(node_id)
        return (o or {}).get("properties", {}).get("status")

    def find_by_type(self, type_name, status=None):
        out = []
        for s in self.g.subjects(RDF.type, AX[type_name]):
            nid = self.local(s)
            if status is None or self.status(nid) == status:
                out.append(nid)
        return sorted(out)

    # ── Grounding: 계보 추적 (하류 → 상류) ──
    def trace_lineage(self, node_id):
        chain, notes = [node_id], []
        cur = node_id
        ds = [self.local(o) for o in self.g.objects(self.uri(cur), AX.consumes)]
        if ds:
            cur = ds[0]; chain.append(cur); notes.append(f"{node_id} --consumes--> {cur}")
        raws = [self.local(o) for o in self.g.objects(self.uri(cur), AX.derivedFrom)]
        if raws:
            prev = cur; cur = raws[0]; chain.append(cur); notes.append(f"{prev} --derivedFrom--> {cur}")
        camps = [self.local(s) for s in self.g.subjects(AX.produces, self.uri(cur))]
        if camps:
            chain.append(camps[0]); notes.append(f"{camps[0]} --produces--> {cur}")
        return {"chain": chain, "edges": notes}

    def upstream_of(self, node_id):
        return self.trace_lineage(node_id)["chain"]

    # ── Grounding: 규칙 평가 (SHACL) ──
    def check_rules(self):
        from pyshacl import validate as sv
        _, rg, _ = sv(self.g, shacl_graph=self.shapes, ont_graph=self.owl, inference="rdfs")
        SH = V.SH
        out = []
        for res in rg.subjects(RDF.type, SH.ValidationResult):
            msg = str(rg.value(res, SH.resultMessage) or "")
            focus = self.local(rg.value(res, SH.focusNode) or "")
            out.append({"rule": msg.split(" ")[0], "focus": focus, "message": msg})
        return sorted(out, key=lambda r: (r["rule"], r["focus"]))

    # ── Grounding: 차단 예외 (R-05) ──
    def blocking_cases(self, run_id):
        return [self.local(s) for s in self.g.subjects(AX.blocks, self.uri(run_id))
                if self.status(self.local(s)) in ("오픈", "처리 중")]

    # ── Grounding: 용어 해석 ──
    def resolve_term(self, term):
        for e in self.glossary:
            if term == e.get("prefLabel") or term in (e.get("altLabels") or []):
                return {"prefLabel": e["prefLabel"], "object": e.get("object"), "definition": e.get("definition")}
        if term in self.objects:
            return {"prefLabel": term, "object": term, "definition": self.objects[term]["definition"]}
        return None

    # ── 쓰기 (Gateway와 시스템 이벤트만 사용) ──
    def set_status(self, node_id, value):
        n = self.uri(node_id)
        self.g.remove((n, AX.status, None))
        self.g.add((n, AX.status, Literal(value)))

    def set_prop(self, node_id, prop, value, datatype=None):
        n = self.uri(node_id)
        self.g.remove((n, AX[prop], None))
        dt = DT.get(datatype)
        # 주의: 파이썬 int로 만든 typed Literal은 ill_typed 검증을 건너뛰어 SHACL datatype 검사에 걸린다 → lexical form으로 생성
        self.g.add((n, AX[prop], Literal(str(value), datatype=dt) if dt else Literal(value)))

    def add_object(self, node_id, type_name, **props):
        n = self.uri(node_id)
        self.g.add((n, RDF.type, AX[type_name]))
        for k, v in props.items():
            self.g.add((n, AX[k], Literal(v)))

    def add_link(self, s, p, o):
        self.g.add((self.uri(s), AX[p], self.uri(o)))

    # ── 시스템 이벤트 (스케줄러 등 외부 시스템의 상태 반영 — Gateway 경유 아님) ──
    def system_complete_run(self, run_id, file_id):
        self.set_status(run_id, "완료")
        self.add_object(file_id, "ReportFile", status="생성됨")
        self.add_link(run_id, "generates", file_id)
        return file_id
