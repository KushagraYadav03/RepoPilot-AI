
from app.services.embedding_service import embed_query
from app.services.qdrant_service import query_repository_embeddings
from app.core.config import settings

QUERY = "How does RAG retrieve relevant code chunks?"
REPOSITORY_ID = 1

print("=" * 70)
print("RAG RETRIEVAL ROOT CAUSE DIAGNOSTIC")
print("=" * 70)

print("\n1. CONFIGURATION")
print("Qdrant path:", settings.qdrant_path)
print("Collection:", settings.qdrant_collection)
print("Repository ID:", REPOSITORY_ID)
print("Query:", QUERY)

print("\n2. GENERATING QUERY EMBEDDING")

try:
    vector = embed_query(QUERY)
    print("Embedding generated:", vector is not None)
    print("Embedding dimension:", len(vector) if vector else 0)
except Exception as exc:
    print("EMBEDDING ERROR:", repr(exc))
    raise

if not vector:
    raise RuntimeError("Query embedding is empty.")

print("\n3. RAW QDRANT SEARCH")

try:
    results = query_repository_embeddings(
        repository_id=REPOSITORY_ID,
        query_vector=vector,
        limit=10,
        score_threshold=None,
    )
except Exception as exc:
    print("QDRANT SEARCH ERROR:", repr(exc))
    raise

print("Total returned points:", len(results))

print("\n4. TOP MATCHES")

for index, point in enumerate(results, start=1):
    payload = point.payload or {}

    print("\n" + "-" * 60)
    print("Rank:", index)
    print("Score:", point.score)
    print("Point ID:", point.id)
    print("Repository ID:", payload.get("repository_id"))
    print("File:", payload.get("file_path"))
    print("Symbol:", payload.get("symbol_name"))
    print("Kind:", payload.get("symbol_kind"))
    print("Lines:", payload.get("start_line"), "-", payload.get("end_line"))
    print("Content length:", len(payload.get("content") or ""))
    print("Content preview:")
    print((payload.get("content") or "")[:500])

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETED")
print("=" * 70)
