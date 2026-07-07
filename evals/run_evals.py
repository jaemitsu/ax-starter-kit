#!/usr/bin/env python3
"""검색·라우팅 회귀 평가. python evals/run_evals.py → 기준 미달 시 exit 1.
기준: 라우팅 정확도 100%, hit@3 100%, top-1 정확도 100% (골든셋은 작으므로 전수 통과가 기준)"""
import os, sys, yaml
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.kb import KnowledgeBase, QueryRouter
from runtime.store import OntologyStore

def main():
    g = yaml.safe_load(open(os.path.join(BASE, "evals/golden.yaml"), encoding="utf-8"))
    kb = KnowledgeBase(os.path.join(BASE, "knowledge"))
    store = OntologyStore(os.path.join(BASE, "domains/ad-reporting"),
                          os.path.join(BASE, "runtime/sample-instances.ttl"))
    router = QueryRouter(store)
    fails = []

    r_ok = 0
    for c in g["routing"]:
        got = router.route(c["query"])["route"]
        if got == c["expect"]: r_ok += 1
        else: fails.append(f"[라우팅] '{c['query']}' → {got} (기대 {c['expect']})")
    print(f"라우팅 정확도: {r_ok}/{len(g['routing'])}")

    h_ok = 0
    for c in g["retrieval"]:
        hits = kb.search(c["query"], k=3, kind=c["kind"])
        docs = [h["cite"].split("#")[0] for h in hits]
        if c["expectDoc"] in docs: h_ok += 1
        else: fails.append(f"[hit@3] '{c['query']}' → {docs} (기대 {c['expectDoc']})")
    print(f"검색 hit@3: {h_ok}/{len(g['retrieval'])}")

    t_ok = 0
    for c in g["retrieval_top1"]:
        hits = kb.search(c["query"], k=3, kind=c["kind"])
        top = hits[0]["cite"].split("#")[0] if hits else None
        if top == c["expectDoc"]: t_ok += 1
        else: fails.append(f"[top1] '{c['query']}' → {top} (기대 {c['expectDoc']})")
    print(f"검색 top-1: {t_ok}/{len(g['retrieval_top1'])}")

    if fails:
        print("\n실패 목록:")
        for f in fails: print(" ✗", f)
        sys.exit(1)
    print("\n✅ 평가 전수 통과")

if __name__ == "__main__":
    main()
