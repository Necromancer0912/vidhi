"""Benchmark candidate Ollama Cloud models on the production RAG prompt.

For each model x prompt this measures TTFT (first streamed token), total
latency and throughput, then scores answer grounding with the critic using a
fixed judge model so quality comparison is fair across candidates.

    python scripts/benchmark_llm.py

Results: data/benchmarks/llm_bench_<date>.json plus a printed table.
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_ollama import ChatOllama  # noqa: E402

from src.agents.generator import _build_messages, assemble_context  # noqa: E402
from src.retrieval.sparse import BM25Retriever  # noqa: E402

CANDIDATES = [
    "minimax-m3:cloud",   # current production model (baseline)
    "gemma4:31b-cloud",
    "gpt-oss:20b-cloud",
]

# Fixed judge for grounding checks — never one of the systems under test twice
JUDGE_MODEL = "gemma4:31b-cloud"

PROMPTS = [
    "What is Section 154 CrPC and how do I file an FIR?",
    "How do I file a consumer complaint about a defective product?",
    "What is the fee for filing an RTI application and how long does a reply take?",
    "What notice period does a landlord need to evict a tenant?",
    "धारा 302 के तहत सजा क्या है?",
    "मुझे अपनी ग्रेच्युटी कब मिलती है?",
    "Explain Section 206 of the Motor Vehicles Act about licence seizure.",
    "My employer has not deposited EPF for 6 months and refuses to respond. What are my legal remedies and which authorities should I approach?",
]


async def score_grounding(answer: str, chunks, judge) -> float:
    """Fraction of judge-extracted claims supported by the retrieved context."""
    from src.agents.critic import critique_answer

    try:
        result = await critique_answer(answer, chunks, judge)
        return float(result.overall_confidence)
    except Exception:
        return -1.0


async def bench_model(model: str, retriever: BM25Retriever, judge) -> dict:
    llm = ChatOllama(model=model, base_url="http://localhost:11434", temperature=0.1)
    rows = []
    for prompt in PROMPTS:
        chunks = retriever.retrieve(prompt, top_k=20)[:5]
        context, _ = assemble_context(chunks)
        messages = _build_messages(prompt, context, "", False, None)

        t0 = time.perf_counter()
        ttft = None
        parts = []
        try:
            async for piece in llm.astream(messages):
                content = piece.content if hasattr(piece, "content") else str(piece)
                if content:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    parts.append(content)
            total = time.perf_counter() - t0
        except Exception as exc:
            rows.append({"prompt": prompt[:40], "error": str(exc)[:120]})
            continue

        answer = "".join(parts)
        if not answer:
            rows.append({"prompt": prompt[:40], "error": "empty response"})
            print(f"  {model} | {prompt[:35]:35s} | empty response", flush=True)
            continue
        grounding = await score_grounding(answer, chunks, judge)
        rows.append(
            {
                "prompt": prompt[:40],
                "ttft_s": round(ttft or total, 2),
                "total_s": round(total, 2),
                "chars": len(answer),
                "chars_per_s": round(len(answer) / total, 1) if total else 0,
                "grounding": round(grounding, 3),
            }
        )
        print(f"  {model} | {prompt[:35]:35s} | ttft {ttft:5.1f}s | total {total:5.1f}s | ground {grounding:.2f}", flush=True)

    ok = [r for r in rows if "error" not in r]
    grounded = [r["grounding"] for r in ok if r["grounding"] >= 0]
    return {
        "model": model,
        "runs": rows,
        "median_ttft_s": round(statistics.median([r["ttft_s"] for r in ok]), 2) if ok else None,
        "median_total_s": round(statistics.median([r["total_s"] for r in ok]), 2) if ok else None,
        "mean_grounding": round(statistics.mean(grounded), 3) if grounded else None,
        "errors": len(rows) - len(ok),
    }


async def main() -> None:
    retriever = BM25Retriever.load_index()
    judge = ChatOllama(model=JUDGE_MODEL, base_url="http://localhost:11434", temperature=0.0)

    results = []
    for model in CANDIDATES:
        print(f"\n=== {model} ===", flush=True)
        results.append(await bench_model(model, retriever, judge))

    out = ROOT / "data/benchmarks" / f"llm_bench_{time.strftime('%Y%m%d')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    print(f"\n{'model':22s} {'ttft':>7s} {'total':>7s} {'grounding':>10s} {'errors':>7s}")
    for r in results:
        print(f"{r['model']:22s} {r['median_ttft_s']!s:>7s} {r['median_total_s']!s:>7s} {r['mean_grounding']!s:>10s} {r['errors']:>7d}")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
