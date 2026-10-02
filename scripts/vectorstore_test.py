#!/usr/bin/env python3
"""Vector store unit tests.

Uses a throwaway index in a temp directory so the shared FAISS file is not
touched. Covers add/search/delete semantics and, importantly, that deletions
leave the index internally consistent - a stale positional mapping here would
silently return another user's chunks.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np  # noqa: E402
from app.services.rag.vector_store import FaissVectorStore  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def vec(seed: int, dim: int = 16) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype("float32")
    return v / np.linalg.norm(v)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="docmind-vec-"))
    try:
        print("=" * 68)
        print("1. Basic add + search")
        print("=" * 68)
        store = FaissVectorStore(tmp / "idx")
        check("empty store returns nothing", store.search(vec(0), 5) == [])
        check("empty store counts zero", store.count() == 0)

        ids = ["a", "b", "c", "d"]
        vectors = np.vstack([vec(1), vec(2), vec(3), vec(4)])
        payloads = [
            {"user_id": "u1", "document_id": "doc1", "filename": "one.txt", "text": "alpha", "page_number": 1},
            {"user_id": "u1", "document_id": "doc1", "filename": "one.txt", "text": "beta", "page_number": 2},
            {"user_id": "u2", "document_id": "doc2", "filename": "two.txt", "text": "gamma", "page_number": 1},
            {"user_id": "u2", "document_id": "doc2", "filename": "two.txt", "text": "delta", "page_number": 1},
        ]
        store.add(ids, vectors, payloads)
        check("count reflects additions", store.count() == 4)

        hits = store.search(vec(1), 4)
        check("returns all four", len(hits) == 4)
        check("nearest is the exact match", hits[0][0] == "a", f"got {hits[0][0]}")
        check("payload travels with the hit", hits[0][2]["filename"] == "one.txt")
        check("page number preserved", hits[0][2]["page_number"] == 1)

        print()
        print("=" * 68)
        print("2. Ordering and score sanity")
        print("=" * 68)
        hits = store.search(vec(3), 4)
        check("query finds its own vector first", hits[0][0] == "c", f"got {hits[0][0]}")
        check("scores descending", all(hits[i][1] >= hits[i + 1][1] for i in range(len(hits) - 1)))
        check("self-similarity ~1.0", abs(hits[0][1] - 1.0) < 1e-4)

        print()
        print("=" * 68)
        print("3. Delete by document")
        print("=" * 68)
        removed = store.delete_by_document("doc1")
        check("removed two vectors", removed == 2, f"got {removed}")
        check("count is now two", store.count() == 2)
        remaining = {h[0] for h in store.search(vec(1), 10)}
        check("only the other user's vectors remain", remaining == {"c", "d"}, f"{remaining}")
        # Critical: ids must still map to the right payloads after a rebuild.
        by_id = {h[0]: h[2] for h in store.search(vec(1), 10)}
        check(
            "payloads still aligned after rebuild",
            by_id.get("c", {}).get("text") == "gamma" and by_id.get("d", {}).get("text") == "delta",
            f"{by_id}",
        )
        check("search for a removed id finds nothing", "a" not in by_id)

        print()
        print("=" * 68)
        print("4. Delete by user (account deletion)")
        print("=" * 68)
        removed = store.delete_by_user("u2")
        check("removed both vectors", removed == 2, f"got {removed}")
        check("index is empty", store.count() == 0)
        check("no hits remain", store.search(vec(1), 10) == [])
        check("deleting an unknown user is a no-op", store.delete_by_user("nobody") == 0)

        print()
        print("=" * 68)
        print("5. Delete the last document empties the index")
        print("=" * 68)
        store.add(["x", "y"], np.vstack([vec(7), vec(8)]), [
            {"user_id": "u3", "document_id": "dX", "text": "x"},
            {"user_id": "u3", "document_id": "dY", "text": "y"},
        ])
        check("two added", store.count() == 2)
        store.delete_by_document("dX")
        check("one left", store.count() == 1)
        hits = store.search(vec(8), 5)
        check("survivor still resolves correctly", hits and hits[0][0] == "y", f"{hits}")
        store.delete_by_document("dY")
        check("index empty after removing all", store.count() == 0)

        print()
        print("=" * 68)
        print("6. Persistence across reload")
        print("=" * 68)
        store.add(["p", "q"], np.vstack([vec(11), vec(12)]), [
            {"user_id": "u4", "document_id": "dp", "text": "persisted one"},
            {"user_id": "u4", "document_id": "dp", "text": "persisted two"},
        ])
        reloaded = FaissVectorStore(tmp / "idx")
        check("count survives reload", reloaded.count() == 2)
        hits = reloaded.search(vec(11), 5)
        check("search works after reload", hits[0][0] == "p", f"got {hits[0][0]}")
        check("payload survives reload", hits[0][2]["text"] == "persisted one")
        removed = reloaded.delete_by_document("dp")
        check("delete works after reload", removed == 2 and reloaded.count() == 0)

        print()
        print("=" * 68)
        print("7. top_k larger than the corpus")
        print("=" * 68)
        # Reuse `reloaded`: it is the instance whose state matches the file on
        # disk. Creating a second live store over the same path would give two
        # divergent in-memory indexes (the app only ever uses one).
        store = reloaded
        store.add(["only"], vec(21)[None, :], [{"user_id": "u", "document_id": "d", "text": "solo"}])
        check("added one row", store.count() == 1, f"count={store.count()}")
        check("returns the single row", len(store.search(vec(21), 10)) == 1)
        check("payload correct", store.search(vec(21), 10)[0][2]["text"] == "solo")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("RESULT: ALL VECTOR STORE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())