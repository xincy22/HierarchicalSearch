from __future__ import annotations

from .base import DocVectorRecord, SearchHit, SectionVectorRecord


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        dim: int,
        doc_collection: str = "doc_vectors",
        section_collection: str = "section_vectors",
    ):
        from pymilvus import (  # type: ignore
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            connections,
            utility,
        )

        self._Collection = Collection
        self._CollectionSchema = CollectionSchema
        self._DataType = DataType
        self._FieldSchema = FieldSchema
        self._utility = utility

        connections.connect(alias="default", uri=uri)

        self.doc_collection_name = doc_collection
        self.section_collection_name = section_collection
        self.dim = dim
        self.doc_collection = self._ensure_doc_collection()
        self.section_collection = self._ensure_section_collection()
        self.doc_collection.load()
        self.section_collection.load()

    def _ensure_doc_collection(self):
        if self._utility.has_collection(self.doc_collection_name):
            return self._Collection(self.doc_collection_name)

        fields = [
            self._FieldSchema(name="id", dtype=self._DataType.INT64, is_primary=True, auto_id=True),
            self._FieldSchema(name="doc_id", dtype=self._DataType.INT64),
            self._FieldSchema(name="variant", dtype=self._DataType.VARCHAR, max_length=64),
            self._FieldSchema(name="text", dtype=self._DataType.VARCHAR, max_length=8192),
            self._FieldSchema(name="vector", dtype=self._DataType.FLOAT_VECTOR, dim=self.dim),
        ]
        collection = self._Collection(
            self.doc_collection_name,
            schema=self._CollectionSchema(fields=fields, description="Doc vectors"),
        )
        collection.create_index(
            field_name="vector",
            index_params={
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        return collection

    def _ensure_section_collection(self):
        if self._utility.has_collection(self.section_collection_name):
            return self._Collection(self.section_collection_name)

        fields = [
            self._FieldSchema(name="id", dtype=self._DataType.INT64, is_primary=True, auto_id=True),
            self._FieldSchema(name="doc_id", dtype=self._DataType.INT64),
            self._FieldSchema(name="section_id", dtype=self._DataType.VARCHAR, max_length=64),
            self._FieldSchema(name="l1_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="l2_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="l3_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="text", dtype=self._DataType.VARCHAR, max_length=8192),
            self._FieldSchema(name="vector", dtype=self._DataType.FLOAT_VECTOR, dim=self.dim),
        ]
        collection = self._Collection(
            self.section_collection_name,
            schema=self._CollectionSchema(fields=fields, description="Section vectors"),
        )
        collection.create_index(
            field_name="vector",
            index_params={
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        return collection

    def _delete_by_doc_ids(self, collection, doc_ids: set[int]) -> None:
        if not doc_ids:
            return
        ids = ",".join(str(d) for d in doc_ids)
        collection.delete(expr=f"doc_id in [{ids}]")

    def add_doc_vectors(self, rows: list[DocVectorRecord]) -> None:
        if not rows:
            return
        self._delete_by_doc_ids(self.doc_collection, {row.doc_id for row in rows})
        self.doc_collection.insert([
            [row.doc_id for row in rows],
            [row.variant for row in rows],
            [row.text[:8192] for row in rows],
            [row.vector for row in rows],
        ])
        self.doc_collection.flush()

    def add_section_vectors(self, rows: list[SectionVectorRecord]) -> None:
        if not rows:
            return
        self._delete_by_doc_ids(self.section_collection, {row.doc_id for row in rows})
        self.section_collection.insert([
            [row.doc_id for row in rows],
            [row.section_id for row in rows],
            [row.l1_title[:1024] for row in rows],
            [row.l2_title[:1024] for row in rows],
            [row.l3_title[:1024] for row in rows],
            [row.text[:8192] for row in rows],
            [row.vector for row in rows],
        ])
        self.section_collection.flush()

    @staticmethod
    def _to_payload(hit, fields: list[str]) -> dict[str, object]:
        return {key: hit.entity.get(key) for key in fields}

    def search_doc_vectors(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        fields = ["doc_id", "variant", "text"]
        results = self.doc_collection.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=top_k,
            output_fields=fields,
        )
        return [
            SearchHit(score=float(hit.distance), payload=self._to_payload(hit, fields))
            for hit in (results[0] if results else [])
        ]

    def search_section_vectors(
        self, query_vector: list[float], doc_id: int, top_k: int
    ) -> list[SearchHit]:
        fields = ["doc_id", "section_id", "text", "l1_title", "l2_title", "l3_title"]
        results = self.section_collection.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            expr=f"doc_id == {doc_id}",
            limit=top_k,
            output_fields=fields,
        )
        return [
            SearchHit(score=float(hit.distance), payload=self._to_payload(hit, fields))
            for hit in (results[0] if results else [])
        ]
