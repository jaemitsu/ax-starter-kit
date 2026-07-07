"""지식 레이어 — MD 정본 로더 + BM25 하이브리드 검색 + 질의 라우터.
설계 원칙 (knowledge-judgment-layer-design.md):
  · 정본은 MD(Git), 인덱스는 파생물 · 만료 문서는 경고와 함께 반환, 확정 근거 사용 금지
  · 검색 전 메타데이터 필터(권한·종류) · 질의는 라우팅한다 (Graph / policy / experience)
프로덕션 전환: BM25 → pgvector/Qdrant 하이브리드+리랭커로 교체 (인터페이스 유지)
"""
import os, re, math, datetime
import yaml

def _tokenize(text):
    text = re.sub(r"[^\w가-힣]+", " ", text.lower())
    toks = []
    for w in text.split():
        toks.append(w)
        # 한국어 조사 대응: 2글자 이상 어절의 접두 n-gram을 보조 토큰으로
        if re.match(r"^[가-힣]{3,}$", w):
            toks.append(w[:2]); toks.append(w[:3])
    return toks

class Chunk:
    def __init__(self, doc, section, text, meta, title=""):
        self.doc, self.section, self.text, self.meta = doc, section, text, meta
        self.tokens = _tokenize(title + " " + section + " " + text)
    @property
    def cite(self): return f"{self.doc}#{self.section}"

class KnowledgeBase:
    def __init__(self, root, today=None):
        self.root = root
        self.today = today or datetime.date.today()
        self.chunks, self.docs = [], {}
        self._load()
        self._build_bm25()

    def _load(self):
        for dirpath, _, files in os.walk(self.root):
            for fn in sorted(files):
                if not fn.endswith(".md"): continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, self.root).replace(os.sep, "/")
                raw = open(path, encoding="utf-8").read()
                meta = {}
                m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
                if m:
                    meta = yaml.safe_load(m.group(1)) or {}
                    raw = raw[m.end():]
                exp = meta.get("expires")
                if isinstance(exp, str): exp = datetime.date.fromisoformat(exp)
                meta["expired"] = bool(exp and exp < self.today)
                if not meta.get("kind"):  # 경로 기반 폴백: 메타 누락 문서도 분류
                    meta["kind"] = "policy" if "/policies/" in "/" + rel else ("experience" if "/cases/" in "/" + rel else "other")
                self.docs[rel] = meta
                # 섹션 청킹 (## 기준, 구조 기반) — 제목 토큰 포함 색인
                lines_ = raw.splitlines()
                title = next((l[2:].strip() for l in lines_ if l.startswith("# ")), "")
                meta["title"] = title
                cur_sec, buf = "본문", []
                for line in lines_:
                    if line.startswith("# ") and line[2:].strip() == title: continue
                    if line.startswith("## "):
                        if buf: self.chunks.append(Chunk(rel, cur_sec, "\n".join(buf), meta, title))
                        cur_sec, buf = line[3:].strip(), []
                    else:
                        buf.append(line)
                if buf: self.chunks.append(Chunk(rel, cur_sec, "\n".join(buf), meta, title))

    def _build_bm25(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.df, self.avgdl = {}, 0
        for c in self.chunks:
            self.avgdl += len(c.tokens)
            for t in set(c.tokens):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = self.avgdl / max(len(self.chunks), 1)
        self.N = len(self.chunks)

    def _score(self, q_tokens, chunk):
        score, tf = 0.0, {}
        for t in chunk.tokens: tf[t] = tf.get(t, 0) + 1
        for t in q_tokens:
            if t not in tf: continue
            idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
            d = tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(chunk.tokens) / self.avgdl))
            score += idf * d
        return score

    def search(self, query, k=3, kind=None, access=("internal", "public"), related_object=None):
        """메타데이터 필터 → BM25 랭킹 → 만료 경고 첨부."""
        q = _tokenize(query)
        cands = [c for c in self.chunks
                 if (kind is None or c.meta.get("kind") == kind)
                 and c.meta.get("accessLevel", "internal") in access
                 and (related_object is None or related_object in (c.meta.get("relatedObjects") or []))]
        ranked = sorted(cands, key=lambda c: self._score(q, c), reverse=True)
        out = []
        for c in ranked[:k]:
            s = self._score(q, c)
            if s <= 0: continue
            matches = len(set(q) & set(c.tokens))
            out.append({"cite": c.cite, "matches": matches,
                        "title": c.meta.get("title"), "section": c.section,
                        "text": c.text.strip()[:400], "score": round(s, 3),
                        "kind": c.meta.get("kind"), "owner": c.meta.get("owner"),
                        "expired": c.meta.get("expired"),
                        "warning": "⚠ 검토 기한 초과 — 확정 근거로 사용 금지" if c.meta.get("expired") else None})
        return out

class QueryRouter:
    """질의를 지식 형태로 라우팅한다. Graph(구조·상태) / policy(규범) / experience(경험)."""
    GRAPH = ["상태", "왜 안", "왜 막", "계보", "어디서 왔", "누가 담당", "차단", "몇 건", "현재", "지금", "실패한", "연결"]
    POLICY = ["정책", "규정", "규칙", "해도 되", "해도 돼", "가능한가", "승인", "허용", "기준", "절차", "원칙", "해야 하"]
    EXPERIENCE = ["사례", "과거", "전에", "비슷한", "겪은", "지난번", "해결했", "이력"]

    def __init__(self, store=None):
        self.store = store

    def route(self, query):
        scores = {"graph": 0, "policy": 0, "experience": 0}
        for w in self.GRAPH:
            if w in query: scores["graph"] += 1
        for w in self.POLICY:
            if w in query: scores["policy"] += 1
        for w in self.EXPERIENCE:
            if w in query: scores["experience"] += 1
        # 객체 ID/용어가 질의에 있으면 graph 가중
        if self.store:
            for tok in re.findall(r"[A-Za-z][A-Za-z0-9_]*|[가-힣]{2,}", query):
                if self.store.exists(tok) or tok in self.store.objects: scores["graph"] += 2
                elif self.store.resolve_term(tok): scores["graph"] += 1
        prio = {"policy": 0, "experience": 1, "graph": 2}   # 동점 시 규범 우선 (틀리면 안 되는 지식부터)
        best = min(scores, key=lambda k: (-scores[k], prio[k]))
        if scores[best] == 0: best = "experience"   # 무신호 → 유사 사례 탐색이 안전한 기본값
        return {"route": best, "scores": scores}
