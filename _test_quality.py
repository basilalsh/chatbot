"""Quality + timing validation for /ask-stream endpoint."""
import time
import urllib.request
import json

STREAM_URL = "http://127.0.0.1:5000/ask-stream"

def ask_stream(question, history=None):
    body = json.dumps({"question": question, "history": history or []}).encode()
    req = urllib.request.Request(
        STREAM_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.perf_counter()
    answer = ""
    conf = "?"
    sources_count = 0
    followups_count = 0

    with urllib.request.urlopen(req, timeout=120) as r:
        ct = r.getheader("Content-Type", "")
        if "application/json" in ct:
            payload = json.loads(r.read())
            elapsed = time.perf_counter() - t0
            return (
                elapsed,
                payload.get("confidence", "?"),
                payload.get("answer", ""),
                len(payload.get("sources", [])),
                len(payload.get("follow_up_questions", [])),
                "JSON(fast-path)",
            )
        buf = ""
        for chunk in iter(lambda: r.read(512), b""):
            buf += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buf:
                msg, buf = buf.split("\n\n", 1)
                for line in msg.split("\n"):
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except Exception:
                        continue
                    if "token" in ev:
                        answer += ev["token"]
                    if "replace" in ev:
                        answer = ev["replace"]
                    if ev.get("done"):
                        conf = ev.get("confidence", "?")
                        sources_count = len(ev.get("sources", []))
                        followups_count = len(ev.get("follow_up_questions", []))

    elapsed = time.perf_counter() - t0

    # Strip JSON wrapper that model sometimes includes
    raw = answer.strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            answer = parsed.get("answer", raw)
        except Exception:
            pass

    return elapsed, conf, answer, sources_count, followups_count, "SSE"


DIVIDER = "=" * 65

TESTS = [
    ("EN-1", "What is the notice period for termination?"),
    ("AR-1", "\u0645\u0627 \u0647\u064a \u0645\u062f\u0629 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0644\u0625\u0646\u0647\u0627\u0621 \u0627\u0644\u0639\u0642\u062f\u061f"),
    ("EN-2", "What are the annual leave entitlements?"),
    ("AR-2", "\u0645\u0627 \u0647\u064a \u062d\u0642\u0648\u0642 \u0627\u0644\u0625\u062c\u0627\u0632\u0629 \u0627\u0644\u0633\u0646\u0648\u064a\u0629\u061f"),
    ("GREET", "Hello"),
    ("FAQ",   "What is Dhofar Insurance?"),
    ("UNKN",  "What is the price of gold today?"),
]

print(DIVIDER)
print("QUALITY + TIMING VALIDATION  (/ask-stream)")
print(DIVIDER)
print()

cold_times = {}

for label, q in TESTS:
    print(f"[{label}] {q[:60]}")
    t, conf, ans, nsrc, nfup, route = ask_stream(q)
    ans_clean = ans.replace("\n", " ").strip()
    fence  = "FENCE_BUG "  if ans_clean.startswith("```") else ""
    unparsed = "PARSE_BUG " if '"answer"' in ans_clean[:40] else ""
    empty  = "EMPTY "      if not ans_clean else ""
    status = (fence + unparsed + empty).strip() or "OK"
    print(f"  time={t:.2f}s  conf={conf}  src={nsrc}  followups={nfup}  route={route}  [{status}]")
    print(f"  Preview: {ans_clean[:130]}")
    cold_times[label] = t
    print()

print(DIVIDER)
print("CACHE TEST — repeat first 4 questions")
print(DIVIDER)
print()

for label, q in TESTS[:4]:
    t, conf, ans, nsrc, nfup, route = ask_stream(q)
    cache_hit = t < 0.5
    tag = "CACHE_HIT" if cache_hit else "CACHE_MISS"
    print(f"[{label}] {q[:55]}")
    print(f"  time={t:.3f}s  [{tag}]  conf={conf}  route={route}")
    print()

print(DIVIDER)
print("SUMMARY")
print(DIVIDER)
for label, t in cold_times.items():
    print(f"  {label:8s} {t:.1f}s")
