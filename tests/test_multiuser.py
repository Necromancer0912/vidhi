import asyncio
import time
import httpx
from typing import Dict, Any, List

# Target FastAPI server URL
BASE_URL = "http://localhost:8080"

# List of 10 legal queries to run concurrently
QUERIES = [
    "What is the penalty for domestic violence under Indian law?",
    "How do I file an RTI application online?",
    "What are the key rights under the Consumer Protection Act?",
    "What is the procedure to file a complaint under RERA?",
    "What are the grounds for divorce under the Hindu Marriage Act?",
    "What is the punishment for cheating under the IPC?",
    "How can I claim free legal aid in India?",
    "What is the time limit to file a consumer court complaint?",
    "What are the tenant rights under the rent control act?",
    "What documents are needed to update my Aadhaar details?"
]

# Map queries to 5 distinct session IDs to simulate multiple concurrent users
SESSION_MAPPING = [
    (QUERIES[0], "session_alpha"),
    (QUERIES[1], "session_beta"),
    (QUERIES[2], "session_gamma"),
    (QUERIES[3], "session_delta"),
    (QUERIES[4], "session_epsilon"),
    (QUERIES[5], "session_alpha"),    # Duplicate session (queuing trigger)
    (QUERIES[6], "session_beta"),     # Duplicate session (queuing trigger)
    (QUERIES[7], "session_gamma"),    # Duplicate session (queuing trigger)
    (QUERIES[8], "session_delta"),    # Duplicate session (queuing trigger)
    (QUERIES[9], "session_epsilon")   # Duplicate session (queuing trigger)
]

async def send_query(client: httpx.AsyncClient, query: str, session_id: str, query_idx: int) -> Dict[str, Any]:
    """
    Sends a query post request to the FastAPI app and measures client-side latency.
    """
    url = f"{BASE_URL}/query"
    payload = {
        "query": query,
        "session_id": session_id
    }
    
    start_time = time.time()
    try:
        response = await client.post(url, json=payload, timeout=75.0)
        client_latency_ms = int((time.time() - start_time) * 1000)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "query_idx": query_idx,
                "session_id": session_id,
                "success": True,
                "status_code": 200,
                "client_latency_ms": client_latency_ms,
                "server_latency": data.get("latency", {}),
                "answer": data.get("answer", ""),
                "request_id": data.get("request_id", "")
            }
        else:
            return {
                "query_idx": query_idx,
                "session_id": session_id,
                "success": False,
                "status_code": response.status_code,
                "client_latency_ms": client_latency_ms,
                "error": response.text
            }
    except Exception as e:
        client_latency_ms = int((time.time() - start_time) * 1000)
        return {
            "query_idx": query_idx,
            "session_id": session_id,
            "success": False,
            "status_code": 500,
            "client_latency_ms": client_latency_ms,
            "error": str(e)
        }

async def run_load_test():
    print("==========================================================")
    print("NyayaBot Async Multiuser Concurrent Load Test")
    print(f"Target Server: {BASE_URL}")
    print("==========================================================\n")

    async with httpx.AsyncClient() as client:
        # Check system health first
        try:
            health_resp = await client.get(f"{BASE_URL}/health", timeout=5.0)
            if health_resp.status_code == 200:
                print("✓ System health check PASSED:")
                print(f"  {health_resp.text}\n")
            else:
                print(f"⚠ System health check returned code {health_resp.status_code}. Proceeding anyway...\n")
        except Exception as e:
            print(f"✗ Could not connect to FastAPI server at {BASE_URL}: {e}")
            print("  Please ensure Docker Compose or uvicorn is running locally on the Mac.\n")
            return

        print(f"🚀 Dispatching {len(SESSION_MAPPING)} concurrent queries across 5 user sessions...")
        start_test_time = time.time()
        
        # Build tasks list for concurrent execution
        tasks = []
        for idx, (query, session_id) in enumerate(SESSION_MAPPING):
            tasks.append(send_query(client, query, session_id, idx))
            
        # Execute all queries concurrently
        results = await asyncio.gather(*tasks)
        total_test_time_ms = int((time.time() - start_test_time) * 1000)
        
        print(f"✓ All tasks completed! Total load-test duration: {total_test_time_ms} ms\n")
        
        # --- Process Results & Print Reports ---
        success_count = sum(1 for r in results if r["success"])
        failure_count = len(results) - success_count
        
        print("==========================================================")
        print("CONCURRENT QUERY REPORT")
        print("==========================================================")
        for r in sorted(results, key=lambda x: x["query_idx"]):
            q_text = QUERIES[r["query_idx"]]
            truncated_q = q_text[:50] + "..." if len(q_text) > 50 else q_text
            
            if r["success"]:
                s_lat = r["server_latency"]
                # Local latency = embed_ms + retrieve_ms + rerank_ms
                local_lat_ms = s_lat.get("embed_ms", 0) + s_lat.get("retrieve_ms", 0) + s_lat.get("rerank_ms", 0)
                vllm_lat_ms = s_lat.get("generate_ms", 0)
                
                print(f"Query #{r['query_idx']+1} [{r['session_id']}]: SUCCESS")
                print(f"  Query:      \"{truncated_q}\"")
                print(f"  Client Latency: {r['client_latency_ms']} ms")
                print(f"  └─ Local Mac Pipeline: {local_lat_ms} ms (Embed: {s_lat.get('embed_ms')}ms | Retrieve: {s_lat.get('retrieve_ms')}ms | Rerank: {s_lat.get('rerank_ms')}ms)")
                print(f"  └─ Remote vLLM: {vllm_lat_ms} ms")
            else:
                print(f"Query #{r['query_idx']+1} [{r['session_id']}]: FAILED")
                print(f"  Query:      \"{truncated_q}\"")
                print(f"  Status:     {r['status_code']}")
                print(f"  Error:      {r.get('error', 'Unknown Error')}")
            print("-" * 58)

        # --- Aggregate Statistics ---
        successful_results = [r for r in results if r["success"]]
        if successful_results:
            avg_client_lat = sum(r["client_latency_ms"] for r in successful_results) / len(successful_results)
            avg_local_lat = sum(
                r["server_latency"].get("embed_ms", 0) + 
                r["server_latency"].get("retrieve_ms", 0) + 
                r["server_latency"].get("rerank_ms", 0)
                for r in successful_results
            ) / len(successful_results)
            avg_vllm_lat = sum(r["server_latency"].get("generate_ms", 0) for r in successful_results) / len(successful_results)
            
            print("\n==========================================================")
            print("AGGREGATE LATENCY METRICS")
            print("==========================================================")
            print(f"Total Successful Queries:     {success_count}/{len(results)}")
            print(f"Average Total Client Latency: {avg_client_lat:.2f} ms")
            print(f"Average Local Mac Pipeline:   {avg_local_lat:.2f} ms")
            print(f"Average Remote vLLM:{avg_vllm_lat:.2f} ms")
            print("==========================================================")
        else:
            print("\n✗ Error: No queries completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_load_test())
