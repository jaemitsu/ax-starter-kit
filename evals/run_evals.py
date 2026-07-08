#!/usr/bin/env python3
"""검색·라우팅 회귀 평가. python evals/run_evals.py → 기준 미달 시 exit 1.
골든셋 100문항 (routing 60 / hit@3 30 / top-1 10) + 난이도 태그(difficulty) 지원.
합격 기준: easy·medium 100%, hard ≥ 90% (엣지케이스는 라우터·검색 개선의 여지로 남긴다).
난이도 미표기 문항은 easy로 취급한다 (구버전 골든셋 호환)."""
import os, sys, yaml
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.kb import KnowledgeBase, QueryRouter
from runtime.store import OntologyStore

HARD_PASS_RATE = 0.90   # hard 난이도 합격선 (easy/medium은 전수 통과)

def evaluate(cases, check):
    """check(case) -> (ok, detail). 난이도별 집계와 실패 목록을 돌려준다."""
    stats = {}   # difficulty -> [ok, total]
    fails = []
    for c in cases:
        d = c.get("difficulty", "easy")
        ok, detail = check(c)
        s = stats.setdefault(d, [0, 0])
        s[1] += 1
        if ok: s[0] += 1
        else: fails.append((d, detail))
    return stats, fails

def summarize(name, stats, fails):
    total_ok = sum(s[0] for s in stats.values())
    total = sum(s[1] for s in stats.values())
    bits = [f"{d} {s[0]}/{s[1]}" for d, s in sorted(stats.items()) if s[1]]
    print(f"{name}: {total_ok}/{total}  ({', '.join(bits)})")
    # 게이트: easy/medium 전수, hard는 HARD_PASS_RATE 이상
    gate_fails = []
    for d, s in stats.items():
        rate = s[0] / s[1] if s[1] else 1.0
        if d == "hard":
            if rate < HARD_PASS_RATE:
                gate_fails.append(f"{name}/hard {rate:.0%} < {HARD_PASS_RATE:.0%}")
        elif s[0] != s[1]:
            gate_fails.append(f"{name}/{d} {s[0]}/{s[1]} (전수 통과 필요)")
    hard_only = [f for d, f in fails if d == "hard"] if not gate_fails else []
    for d, f in fails:
        marker = "△" if d == "hard" and f in hard_only else "✗"
        print(f"  {marker} [{d}] {f}")
    return gate_fails

def main():
    g = yaml.safe_load(open(os.path.join(BASE, "evals/golden.yaml"), encoding="utf-8"))
    kb = KnowledgeBase(os.path.join(BASE, "knowledge"))
    store = OntologyStore(os.path.join(BASE, "domains/ad-reporting"),
                          os.path.join(BASE, "runtime/sample-instances.ttl"))
    router = QueryRouter(store)

    def check_route(c):
        got = router.route(c["query"])["route"]
        return got == c["expect"], f"'{c['query']}' → {got} (기대 {c['expect']})"

    def check_hit3(c):
        hits = kb.search(c["query"], k=3, kind=c["kind"])
        docs = [h["cite"].split("#")[0] for h in hits]
        return c["expectDoc"] in docs, f"'{c['query']}' → {docs} (기대 {c['expectDoc']})"

    def check_top1(c):
        hits = kb.search(c["query"], k=3, kind=c["kind"])
        top = hits[0]["cite"].split("#")[0] if hits else None
        return top == c["expectDoc"], f"'{c['query']}' → {top} (기대 {c['expectDoc']})"

    gate_fails = []
    for name, cases, check in (("라우팅 정확도", g["routing"], check_route),
                               ("검색 hit@3", g["retrieval"], check_hit3),
                               ("검색 top-1", g["retrieval_top1"], check_top1)):
        stats, fails = evaluate(cases, check)
        gate_fails += summarize(name, stats, fails)

    if gate_fails:
        print("\n❌ 합격 기준 미달:")
        for f in gate_fails: print(" ✗", f)
        sys.exit(1)
    print("\n✅ 평가 통과 (easy/medium 전수, hard ≥ 90%)")

if __name__ == "__main__":
    main()
