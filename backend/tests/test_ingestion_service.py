
class FakeDB:
    def __init__(self, job=None, repository=None):
        self.job = job
        self.repository = repository

        self.files = []
        self.chunks = []

        self.commits = []
        self.commit_count = 0

        self.rollback_called = False
        self.next_chunk_id = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def get(self, model, job_id):
        return self.job

    def add(self, instance):

        if isinstance(instance, ingestion_service.RepositoryFile):
            self.files.append(instance)

        elif isinstance(instance, ingestion_service.RepositoryChunk):
            self.chunks.append(instance)

    def flush(self):
        """
        Simulate PostgreSQL assigning primary keys
        to newly inserted RepositoryChunk records.
        """

        for chunk in self.chunks:

            if getattr(chunk, "id", None) is None:
                chunk.id = self.next_chunk_id
                self.next_chunk_id += 1

    def scalar(self, query):
        sql = str(query).lower()

        if "repository_files" in sql:
            return self.files[0] if self.files else None

        return self.repository

    def scalars(self, query):
        sql = str(query).lower()

        if "repository_chunks" in sql:
            return FakeScalarResult(self.chunks)

        if "repository_files" in sql:
            return FakeScalarResult(self.files)

        return FakeScalarResult([])

    def delete(self, instance):

        if instance in self.files:
            self.files.remove(instance)

        if instance in self.chunks:
            self.chunks.remove(instance)

    def commit(self):
        """
        Track every commit, including intermediate
        PostgreSQL persistence commits.
        """

        self.commit_count += 1
        self.commits.append(self.job.status)

    def rollback(self):
        self.rollback_called = True
