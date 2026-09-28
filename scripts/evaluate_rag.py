"""RAG quality/latency evaluation against a running backend.

Runs the fixed test set (data/test_set/questions.json) through POST /chat/sync
and records per-question latency, confidence, legal standing and citation counts.
Results land in data/benchmarks/eval_<tag>.json so runs can be compared.

Usage:
    python scripts/evaluate_rag.py --tag baseline --base-url http://127.0.0.1:8001
    python scripts/evaluate_rag.py --tag after-switch

Clear the semantic cache before each run (scripts/clear_cache.py) so cached
answers from a previous run don't skew the comparison.
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


async def run_one(client: httpx.AsyncClient, base_url: str, item: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{base_url}/api/v1/chat/sync",
                json={"message": item["question"], "session_id": f"eval-{abs(hash(item['question'])) % 10**8}"},
                timeout=300,
            )
            latency = time.perf_counter() - t0
            data = resp.json()
            return {
                "question": item["question"],
                "category": item.get("category", ""),
                "latency_s": round(latency, 2),
                "answer_len": len(data.get("answer", "")),
                "confidence": data.get("confidence_score"),
                "legal_standing": data.get("legal_standing_score"),
                "citations": len(data.get("citations") or []),
                "cache_hit": data.get("cache_hit", False),
                "route": data.get("route"),
                "error": None if resp.status_code == 200 else f"HTTP {resp.status_code}",
            }
        except Exception as exc:
            return {"question": item["question"], "latency_s": round(time.perf_counter() - t0, 2), "error": str(exc)[:200]}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="label for this run, e.g. baseline")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--test-set", default=str(ROOT / "data/test_set/questions.json"))
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="cap number of questions (0 = all)")
    args = parser.parse_args()

    items = json.load(open(args.test_set))
    if args.limit:
        items = items[: args.limit]

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(run_one(client, args.base_url, it, sem) for it in items))

    ok = [r for r in results if not r.get("error")]
    fresh = [r for r in ok if not r.get("cache_hit")]
    confs = [r["confidence"] for r in ok if r.get("confidence") is not None]
    summary = {
        "tag": args.tag,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_questions": len(items),
        "n_ok": len(ok),
        "n_cache_hits": len(ok) - len(fresh),
        "latency_median_s": round(statistics.median([r["latency_s"] for r in fresh]), 2) if fresh else None,
        "latency_p90_s": round(sorted(r["latency_s"] for r in fresh)[int(0.9 * len(fresh))], 2) if fresh else None,
        "confidence_mean": round(statistics.mean(confs), 3) if confs else None,
        "citations_mean": round(statistics.mean([r["citations"] for r in ok]), 2) if ok else None,
        "answer_len_mean": round(statistics.mean([r["answer_len"] for r in ok])) if ok else None,
        "errors": [r for r in results if r.get("error")],
    }

    out_dir = ROOT / "data/benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"eval_{args.tag}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nsaved -> {out_path}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
