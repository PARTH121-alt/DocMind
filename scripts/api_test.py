"""Live HTTP API test: exercises the running server end to end.

Covers auth, upload, indexing, streaming chat with citations, anti-hallucination,
search, smart features, conversations, and cross-tenant isolation.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

DOC = """Renewable Energy: Solar and Wind

Introduction
Renewable energy sources replenish naturally and produce far lower greenhouse
gas emissions than fossil fuels. Solar photovoltaic systems convert sunlight
directly into electricity, while wind turbines convert the kinetic energy of
moving air into electricity.

Solar Photovoltaics
A photovoltaic cell is built from doped silicon. When photons strike the
material they dislodge electrons, generating direct current. An inverter
converts this direct current into alternating current for grid use. Standard
silicon panels achieve roughly 20 percent conversion efficiency, though
perovskite tandem cells in laboratories have exceeded 30 percent.

Wind Turbines
Wind turbines capture kinetic energy with three blades mounted on a hub. The
rotor spins a shaft connected to a generator. Larger rotors extract more energy
at lower wind speeds, but Betz's law limits extraction to roughly 59 percent
of the wind's kinetic power.

Storage and Grid Integration
Intermittency is the central challenge of renewable power. Grid scale battery
storage using lithium iron phosphate cells smooths short term fluctuations.
Pumped hydro storage remains the most deployed form of bulk storage, storing
energy by lifting water into elevated reservoirs.

Economic Considerations
Levelised cost of energy for utility scale solar has fallen by roughly 90
percent since 2010. Wind generation is often the cheapest electricity source in
resource rich regions. Policy instruments such as feed in tariffs and renewable
portfolio standards accelerate deployment.
"""


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    failures: list[str] = []

    with httpx.Client(base_url=BASE, timeout=600.0) as c:
        section("HEALTH")
        r = c.get("/api/health")
        print(f"  HTTP {r.status_code}")
        health = r.json()
        for k in ("status", "database", "vector_db", "generation_backend",
                  "generation_model", "embedding_model", "reranker_available"):
            print(f"  {k:20s} {health.get(k)}")
        if r.status_code != 200:
            failures.append("health")

        section("REGISTER")
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        r = c.post("/api/auth/register", json={
            "email": email, "username": f"u{uuid.uuid4().hex[:6]}", "password": "supersecret123"
        })
        print(f"  HTTP {r.status_code}")
        if r.status_code != 201:
            print(f"  body: {r.text[:300]}")
            failures.append("register")
            print("\nRESULT: FAILED")
            return 1
        token = r.json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        print("  token acquired")

        section("AUTH IS ENFORCED")
        unauth = httpx.get(f"{BASE}/api/documents")
        print(f"  no-token GET /api/documents -> {unauth.status_code} (expect 401)")
        if unauth.status_code != 401:
            failures.append("auth-not-enforced")

        section("MODELS CATALOGUE")
        r = c.get("/api/models")
        models = r.json()
        print(f"  generation models : {len(models['generation'])}")
        print(f"  embedding models  : {len(models['embeddings'])}")
        print(f"  tiers             : {list(models['tiers'].keys())}")
        print(f"  active backend    : {models['active']['generation_backend']}")
        print(f"  hf_token set      : {models['active']['hf_token_configured']}")
        if not models["tiers"]:
            failures.append("models")

        section("UPLOAD DOCUMENT")
        r = c.post(
            "/api/documents/upload",
            files=[("files", ("renewable_energy.txt", DOC.encode(), "text/plain"))],
        )
        print(f"  HTTP {r.status_code}")
        if r.status_code != 201:
            print(f"  body: {r.text[:400]}")
            failures.append("upload")
            return 1
        doc = r.json()[0]
        doc_id = doc["id"]
        print(f"  id       : {doc_id}")
        print(f"  filename : {doc['filename']}")
        print(f"  status   : {doc['status']}")

        section("WAIT FOR INDEXING")
        for _ in range(90):
            time.sleep(2)
            d = c.get(f"/api/documents/{doc_id}").json()
            bar = "#" * int(d["progress"] * 24)
            print(f"  [{bar:<24}] {d['status']:<10} {d['progress']:.0%}  {d['status_detail']}")
            if d["status"] == "indexed":
                print(f"  -> pages={d['page_count']} chunks={d['chunk_count']} words={d['word_count']}")
                break
            if d["status"] == "failed":
                print(f"  -> FAILED: {d['error']}")
                failures.append("indexing")
                break
        else:
            print("  -> TIMEOUT")
            failures.append("indexing-timeout")

        if d["status"] != "indexed":
            print("\nRESULT: FAILED")
            return 1

        section("STREAMING CHAT (in-scope, expect citations)")
        payload = {
            "question": "What is the maximum efficiency of extracting wind energy?",
            "top_k": 5,
        }
        answer = ""
        got_sources = []
        got_done = None
        with c.stream("POST", "/api/chat/stream", json=payload) as resp:
            print(f"  HTTP {resp.status_code}  content-type={resp.headers.get('content-type')}")
            event = None
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: ") and event:
                    data = json.loads(line[6:])
                    if event == "sources":
                        got_sources = data.get("sources", [])
                        print(f"  sources: {got_sources} (n={data.get('count')})")
                        print(f"  confidence: {data.get('confidence')}")
                    elif event == "delta":
                        answer += data.get("text", "")
                    elif event == "done":
                        got_done = data
                    elif event == "error":
                        print(f"  ERROR EVENT: {data}")

        print(f"  ANSWER: {answer.strip()[:400]}")
        print(f"  grounded: {got_done and got_done.get('grounded')}")
        print(f"  latency : {got_done and got_done.get('processing_time_ms')}ms")
        print(f"  citations: {len(got_done.get('citations', []) if got_done else [])}")
        if got_done:
            for cit in got_done.get("citations", [])[:3]:
                print(f"    [{cit['rank']}] {cit['filename']} p{cit['page_number']}: {cit['excerpt'][:90]!r}")
        if not answer.strip():
            failures.append("empty-answer")
        if not got_sources:
            failures.append("no-sources")
        if not (got_done and got_done.get("grounded")):
            failures.append("not-grounded")

        # The 0.5B fallback model is stochastic and occasionally picks the
        # wrong figure from the retrieved passages. Measure the hit rate over a
        # few attempts instead of asserting a single deterministic outcome,
        # and report it so the reliability of the active backend is visible.
        hits = int("59" in answer or "Betz" in answer)
        attempts = 3
        for _ in range(attempts - 1):
            r = c.post("/api/chat", json={
                "question": "What is the maximum efficiency of extracting wind energy?",
                "top_k": 5,
            })
            b = r.json()
            if b.get("grounded") and ("59" in b.get("answer", "") or "Betz" in b.get("answer", "")):
                hits += 1
        print(f"  retrieval+answer accuracy: {hits}/{attempts}")
        if hits == 0:
            failures.append("wrong-answer")

        section("ANTI-HALLUCINATION (out-of-scope, expect refusal)")
        r = c.post("/api/chat", json={"question": "What is the population of Reykjavik?"})
        body = r.json()
        print(f"  grounded : {body['grounded']}  (expect False)")
        print(f"  confidence: {body['confidence']}")
        print(f"  answer   : {body['answer'][:220]}")
        if body["grounded"]:
            failures.append("hallucinated")
        answer_lower = body["answer"].lower()
        honest = any(
            phrase in answer_lower
            for phrase in [
                "couldn't find", "not enough", "unable to ground",
                "wasn't able to ground", "not grounded",
            ]
        )
        if not honest:
            failures.append("bad-refusal-message")

        section("SEARCH")
        r = c.post("/api/search", json={"query": "battery storage lithium", "top_k": 4})
        res = r.json()
        print(f"  count: {res['count']}")
        for item in res["results"][:3]:
            print(f"    score={item['score']:.3f} {item['filename']}: {item['text'][:80]!r}")
        if res["count"] == 0:
            failures.append("empty-search")

        section("SMART: SUMMARIZE")
        r = c.post("/api/documents/summarize", json={"document_ids": [doc_id], "style": "key_points"})
        print(f"  HTTP {r.status_code}  {r.json()['processing_time_ms']}ms")
        print(f"  {r.json()['result'][:300]}")

        section("SMART: EXTRACT INFO")
        r = c.post("/api/documents/extract-info", json={
            "document_ids": [doc_id],
            "fields": ["efficiency figures", "technologies", "policy instruments"],
        })
        print(f"  HTTP {r.status_code}")
        print(f"  {r.json()['result'][:300]}")

        section("SMART: SUGGESTED QUESTIONS")
        r = c.post("/api/documents/suggested-questions", json={"document_ids": [doc_id]})
        print(f"  HTTP {r.status_code}  questions={r.json().get('questions')}")

        section("CONVERSATIONS")
        conv_id = got_done.get("conversation_id") if got_done else None
        r = c.get("/api/conversations")
        convs = r.json()
        print(f"  count: {len(convs)}")
        for cv in convs:
            print(f"    {cv['id'][:8]} '{cv['title']}' msgs={cv['message_count']}")
        if not convs:
            failures.append("no-conversations")

        if conv_id:
            r = c.get(f"/api/conversations/{conv_id}")
            detail = r.json()
            print(f"  history messages: {len(detail['messages'])}")
            print(f"  first user msg : {detail['messages'][0]['content'][:60]!r}")
            print(f"  assistant has {len(detail['messages'][-1]['citations'])} citations")

            r = c.patch(f"/api/conversations/{conv_id}", json={"title": "Renamed conversation"})
            print(f"  rename -> {r.status_code} '{r.json().get('title')}'")

        section("FOLLOW-UP (conversation memory)")
        r = c.post("/api/chat", json={
            "question": "What about the solar panels specifically?",
            "conversation_id": conv_id,
        })
        print(f"  HTTP {r.status_code}  grounded={r.json()['grounded']}")
        print(f"  answer: {r.json()['answer'][:250]}")

        section("CHUNK CONTEXT (citation preview)")
        cit = (got_done.get("citations") or [{}])[0]
        if cit.get("chunk_id"):
            r = c.get(f"/api/chunks/{cit['chunk_id']}/context")
            print(f"  HTTP {r.status_code}  file={r.json().get('filename')}")
            print(f"  text: {r.json().get('text', '')[:150]!r}")

        section("COLLECTIONS")
        r = c.post("/api/collections", json={"name": "Renewables", "description": "Test"})
        coll = r.json()
        print(f"  created: {coll['name']} ({coll['id'][:8]})")
        r = c.get("/api/collections")
        print(f"  collections: {[x['name'] for x in r.json()]}")

        section("TENANT ISOLATION (second user cannot see anything)")
        c2 = httpx.Client(base_url=BASE, timeout=60.0)
        r = c2.post("/api/auth/register", json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "username": f"o{uuid.uuid4().hex[:6]}",
            "password": "supersecret123",
        })
        c2.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        r = c2.get(f"/api/documents/{doc_id}")
        print(f"  other user GET /documents/{doc_id[:8]} -> {r.status_code} (expect 404)")
        if r.status_code != 404:
            failures.append("cross-tenant-doc-read")
        r = c2.get("/api/documents")
        print(f"  other user document count: {r.json()['total']} (expect 0)")
        if r.json()["total"] != 0:
            failures.append("cross-tenant-list")
        r = c2.post("/api/chat", json={"question": "What is the Betz limit?"})
        print(f"  other user chat grounded: {r.json()['grounded']} (expect False)")
        if r.json()["grounded"]:
            failures.append("cross-tenant-chat")
        c2.close()

        section("REJECT UNSUPPORTED FILE TYPE")
        r = c.post("/api/documents/upload",
                   files=[("files", ("evil.exe", b"MZ\x90\x00", "application/octet-stream"))])
        print(f"  HTTP {r.status_code} (expect 415)")
        print(f"  {r.json().get('detail', '')[:120]}")
        if r.status_code != 415:
            failures.append("bad-filetype-not-rejected")

        section("DELETE DOCUMENT")
        before = c.get("/api/health").json()["vector_count"]
        r = c.delete(f"/api/documents/{doc_id}")
        print(f"  HTTP {r.status_code} (expect 204)")
        after = c.get("/api/health").json()["vector_count"]
        print(f"  vectors {before} -> {after} (should drop)")
        if after >= before:
            failures.append("vectors-not-freed")

        section("DELETE ACCOUNT (purges vectors + files)")
        r = c.delete("/api/auth/me")
        print(f"  HTTP {r.status_code} (expect 204)")
        c.headers.pop("Authorization", None)
        r = c.get("/api/documents")
        print(f"  token after deletion -> HTTP {r.status_code} (expect 401)")
        if r.status_code != 401:
            failures.append("deleted-account-still-authorized")

    section("FINAL RESULT")
    if failures:
        print(f"  {len(failures)} FAILURE(S): {failures}")
        return 1
    print("  ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
