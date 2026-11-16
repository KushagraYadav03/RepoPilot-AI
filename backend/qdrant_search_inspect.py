
import inspect

from app.services.qdrant_service import QdrantVectorStore

print("\n" + "=" * 65)
print("1. POINT ID GENERATION")
print("=" * 65)

print(inspect.getsource(
    QdrantVectorStore._get_point_id
))

print("\n" + "=" * 65)
print("2. DELETE REPOSITORY FILE")
print("=" * 65)

print(inspect.getsource(
    QdrantVectorStore.delete_repository_file
))

print("\n" + "=" * 65)
print("3. GET REPOSITORY FILE POINT IDS")
print("=" * 65)

print(inspect.getsource(
    QdrantVectorStore.get_repository_file_point_ids
))

print("\n" + "=" * 65)
print("4. DELETE POINTS BY IDS")
print("=" * 65)

print(inspect.getsource(
    QdrantVectorStore.delete_points_by_ids
))

print("\n" + "=" * 65)
print("5. UPDATE COMMIT SHA")
print("=" * 65)

print(inspect.getsource(
    QdrantVectorStore.update_repository_file_commit_sha
))

print("\nINSPECTION COMPLETED")
