#!/usr/bin/env python3
"""AX 온톨로지 검증 CI.
사용법: python tools/validate.py domains/<domain>
단계: ①구조 검사(Definition of Done) ②참조 무결성 ③OWL/SHACL 생성 ④테스트 인스턴스 검증(미탐+오탐)
"""
import sys, os, yaml
from rdflib import Graph, Namespace, Literal, BNode, URIRef, RDF, RDFS, OWL, XSD
from rdflib.collection import Collection
from pyshacl import validate as shacl_validate

AX = Namespace("https://example.co/ax/ont#")
SH = Namespace("http://www.w3.org/ns/shacl#")
DT = {"decimal": XSD.decimal, "integer": XSD.integer, "string": XSD.string, "date": XSD.date}
AUTONOMY = {"auto", "auto-then-escalate", "human-approval"}

def load(p):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)

# ── ① 구조 검사 + ② 참조 무결성 ──────────────────────────────
def structural_checks(doc):
    errors, warnings = [], []
    objs = {o["name"]: o for o in doc.get("objectTypes", [])}
    preds = {l.get("predicate") for l in doc.get("linkTypes", [])}
    acts = {a.get("name") for a in doc.get("actions", [])}
    if not (8 <= len(objs) <= 15):
        warnings.append(f"객체 수 {len(objs)}개 — 권장 8~15")
    for name, o in objs.items():
        if not o.get("definition"): errors.append(f"[DoD] {name}: definition 누락")
        ow = o.get("owner") or {}
        if not (ow.get("typeLevel") and ow.get("instanceLevel")):
            errors.append(f"[DoD] {name}: owner(typeLevel/instanceLevel) 누락")
        if not ((o.get("lifecycle") or {}).get("states")):
            errors.append(f"[DoD] {name}: lifecycle.states 누락")
        if not ((o.get("identity") or {}).get("key")):
            errors.append(f"[DoD] {name}: identity.key 누락")
        for t in (o.get("lifecycle") or {}).get("transitions", []) or []:
            states = o["lifecycle"]["states"]
            for endp in ("from", "to"):
                if t.get(endp) not in states:
                    errors.append(f"[참조] {name}: 전이 '{t.get(endp)}'가 states에 없음")
            if t.get("via") and t["via"] not in acts:
                errors.append(f"[참조] {name}: 전이 via '{t['via']}'가 actions에 없음")
    for l in doc.get("linkTypes", []):
        for endp in ("subject", "object"):
            if l.get(endp) not in objs:
                errors.append(f"[참조] link {l.get('predicate')}: {endp} '{l.get(endp)}' 미정의 객체")
        if not l.get("cardinality"):
            errors.append(f"[DoD] link {l.get('predicate')}: cardinality 누락")
    for r in doc.get("rules", []):
        for f in ("id", "kind", "statement", "onViolation", "severity"):
            if not r.get(f): errors.append(f"[DoD] rule {r.get('id','?')}: {f} 누락")
        chk = r.get("check")
        if chk and chk.get("targetClass") not in objs:
            errors.append(f"[참조] rule {r['id']}: targetClass 미정의")
    for a in doc.get("actions", []):
        if a.get("target") not in objs:
            errors.append(f"[참조] action {a.get('name')}: target '{a.get('target')}' 미정의")
        if str(a.get("autonomy", "")).split("(")[0] not in AUTONOMY:
            errors.append(f"[DoD] action {a.get('name')}: autonomy 값 오류 ({a.get('autonomy')})")
        for f in ("precondition", "effect", "permission", "idempotency", "audit"):
            if not a.get(f): errors.append(f"[DoD] action {a.get('name')}: {f} 누락")
    for cq in (doc.get("ontology") or {}).get("competencyQuestions", []) or []:
        refs = cq.get("answeredBy") or []
        if not refs: errors.append(f"[DoD] {cq.get('id')}: answeredBy 누락")
        for ref in refs:
            head = str(ref).split(".")[0]
            if head not in objs and head not in preds and head not in acts:
                errors.append(f"[참조] {cq.get('id')}: answeredBy '{ref}' 미정의 참조")
    return errors, warnings

# ── ③ OWL / SHACL 생성 ──────────────────────────────────────
def build_owl(doc):
    g = Graph(); g.bind("ax", AX); g.bind("owl", OWL)
    g.add((URIRef(str(AX)), RDF.type, OWL.Ontology))
    # 속성명 → 사용하는 객체 수 집계 (공유 속성엔 domain 미부여: 복수 rdfs:domain은 교집합 의미라 타입 오염 유발)
    prop_owners = {}
    for o in doc["objectTypes"]:
        for p in o.get("properties", []) or []:
            prop_owners.setdefault(p["name"], set()).add(o["name"])
    for o in doc["objectTypes"]:
        c = AX[o["name"]]
        g.add((c, RDF.type, OWL.Class))
        g.add((c, RDFS.label, Literal(o["definition"][:100], lang="ko")))
        for p in o.get("properties", []) or []:
            pu = AX[p["name"]]
            kind = OWL.ObjectProperty if p.get("type") == "link" else OWL.DatatypeProperty
            g.add((pu, RDF.type, kind))
            if len(prop_owners[p["name"]]) == 1:
                g.add((pu, RDFS.domain, c))
    for l in doc.get("linkTypes", []):
        pu = AX[l["predicate"]]
        g.add((pu, RDF.type, OWL.ObjectProperty))
        g.add((pu, RDFS.domain, AX[l["subject"]])); g.add((pu, RDFS.range, AX[l["object"]]))
    return g

def build_shapes(doc):
    g = Graph(); g.bind("sh", SH); g.bind("ax", AX)
    n = 0
    for r in doc.get("rules", []):
        chk = r.get("check")
        if not chk: continue
        n += 1
        shape = AX[f"Shape_{r['id'].replace('-', '_')}"]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, AX[chk["targetClass"]]))
        prop = BNode(); g.add((shape, SH.property, prop))
        path = chk.get("path")
        if isinstance(path, list):
            pl = BNode(); Collection(g, pl, [AX[p] for p in path]); g.add((prop, SH.path, pl))
        else:
            g.add((prop, SH.path, AX[path]))
        _dt = DT.get(chk.get("datatype"))
        if "minInclusive" in chk: g.add((prop, SH.minInclusive, Literal(chk["minInclusive"], datatype=_dt)))
        if "maxInclusive" in chk: g.add((prop, SH.maxInclusive, Literal(chk["maxInclusive"], datatype=_dt)))
        if "datatype" in chk: g.add((prop, SH.datatype, DT[chk["datatype"]]))
        if "minCount" in chk: g.add((prop, SH.minCount, Literal(int(chk["minCount"]))))
        if "maxCount" in chk: g.add((prop, SH.maxCount, Literal(int(chk["maxCount"]))))
        if "hasValue" in chk: g.add((prop, SH.hasValue, Literal(chk["hasValue"])))
        if "in" in chk:
            il = BNode(); Collection(g, il, [Literal(v) for v in chk["in"]]); g.add((prop, SH["in"], il))
        g.add((prop, SH.message, Literal(f"{r['id']} 위반: {r['statement']} — {r['onViolation']}")))
        g.add((prop, SH.severity, SH.Violation))
    return g, n

# ── ④ 테스트 인스턴스 검증 ───────────────────────────────────
def run_tests(domain_dir, owl_g, shapes_g):
    inst = os.path.join(domain_dir, "tests", "instances.ttl")
    exp_p = os.path.join(domain_dir, "tests", "expected.yaml")
    if not os.path.exists(inst):
        return None, ["tests/instances.ttl 없음 — 테스트 인스턴스는 필수"]
    data = Graph(); data.parse(inst)
    _, rg, _ = shacl_validate(data, shacl_graph=shapes_g, ont_graph=owl_g, inference="rdfs")
    found = set()
    for res in rg.subjects(RDF.type, SH.ValidationResult):
        msg = str(rg.value(res, SH.resultMessage) or "")
        focus = str(rg.value(res, SH.focusNode) or "").split("#")[-1]
        found.add((msg.split(" ")[0], focus))
    expected = {(e["rule"], e["focus"]) for e in (load(exp_p) or {}).get("expectViolations", [])} if os.path.exists(exp_p) else set()
    failures = [f"[미탐] 기대 위반 미검출: {r} @ {f}" for r, f in sorted(expected - found)]
    failures += [f"[오탐] 예상 밖 위반: {r} @ {f}" for r, f in sorted(found - expected)]
    return found, failures

def main():
    domain_dir = sys.argv[1] if len(sys.argv) > 1 else "domains/ad-reporting"
    doc = load(os.path.join(domain_dir, "ontology-state.yaml"))
    print(f"=== AX 온톨로지 검증: {doc['ontology']['domain']} v{doc['ontology']['version']} ===\n")
    errors, warnings = structural_checks(doc)
    for w in warnings: print(f"  ⚠ {w}")
    if errors:
        print(f"\n[1/3] 구조·참조 검사 실패 ({len(errors)}건):")
        for e in errors: print(f"  ✗ {e}")
        sys.exit(1)
    print(f"[1/3] 구조·참조 검사 통과 — 객체 {len(doc['objectTypes'])}, 관계 {len(doc.get('linkTypes',[]))}, 규칙 {len(doc.get('rules',[]))}, 액션 {len(doc.get('actions',[]))}, CQ {len(doc['ontology'].get('competencyQuestions',[]))}")
    owl_g = build_owl(doc)
    shapes_g, n_shapes = build_shapes(doc)
    exp = os.path.join(domain_dir, "exports"); os.makedirs(exp, exist_ok=True)
    owl_g.serialize(os.path.join(exp, "ontology.ttl"), format="turtle")
    shapes_g.serialize(os.path.join(exp, "shapes.shacl.ttl"), format="turtle")
    print(f"[2/3] 파생물 생성 — exports/ontology.ttl ({len(owl_g)} triples), shapes.shacl.ttl (기계 검증 규칙 {n_shapes}건)")
    found, failures = run_tests(domain_dir, owl_g, shapes_g)
    if failures:
        print(f"[3/3] 테스트 인스턴스 검증 실패:")
        for f in failures: print(f"  ✗ {f}")
        sys.exit(1)
    print(f"[3/3] 테스트 인스턴스 검증 통과 — 기대 위반 {len(found)}건 전부 검출, 오탐 0건")
    print("\n✅ 전체 통과 — 릴리스 가능")

if __name__ == "__main__":
    main()
