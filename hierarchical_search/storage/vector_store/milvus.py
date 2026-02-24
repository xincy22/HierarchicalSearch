from __future__ import annotations

from typing import Any

from .base import DocVectorRecord, SearchHit, SectionVectorRecord


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        dim: int,
        doc_collection: str = "doc_vectors",
        section_collection: str = "section_vectors",
    ):
        try:
            from pymilvus import (  # type: ignore
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )
        except ImportError as exc:
            raise RuntimeError(
                "pymilvus is required for Milvus backend. Install with `pip install pymilvus`."
            ) from exc

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
            self._FieldSchema(
                name="id", dtype=self._DataType.INT64, is_primary=True, auto_id=True
            ),
            self._FieldSchema(name="doc_id", dtype=self._DataType.INT64),
            self._FieldSchema(name="variant", dtype=self._DataType.VARCHAR, max_length=64),
            self._FieldSchema(name="text", dtype=self._DataType.VARCHAR, max_length=8192),
            self._FieldSchema(name="vector", dtype=self._DataType.FLOAT_VECTOR, dim=self.dim),
        ]
        schema = self._CollectionSchema(fields=fields, description="Doc vectors")
        collection = self._Collection(self.doc_collection_name, schema=schema)
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
            self._FieldSchema(
                name="id", dtype=self._DataType.INT64, is_primary=True, auto_id=True
            ),
            self._FieldSchema(name="doc_id", dtype=self._DataType.INT64),
            self._FieldSchema(name="section_id", dtype=self._DataType.VARCHAR, max_length=64),
            self._FieldSchema(name="l1_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="l2_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="l3_title", dtype=self._DataType.VARCHAR, max_length=1024),
            self._FieldSchema(name="text", dtype=self._DataType.VARCHAR, max_length=8192),
            self._FieldSchema(name="vector", dtype=self._DataType.FLOAT_VECTOR, dim=self.dim),
        ]
        schema = self._CollectionSchema(fields=fields, description="Section vectors")
        collection = self._Collection(self.section_collection_name, schema=schema)
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
        for doc_id in doc_ids:
            collection.delete(expr=f"doc_id == {doc_id}")

    def add_doc_vectors(self, rows: list[DocVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = {row.doc_id for row in rows}
        self._delete_by_doc_ids(self.doc_collection, doc_ids)
        entities = [
            [row.doc_id for row in rows],
            [row.variant for row in rows],
            [row.text[:8192] for row in rows],
            [row.vector for row in rows],
        ]
        self.doc_collection.insert(entities)
        self.doc_collection.flush()

    def add_section_vectors(self, rows: list[SectionVectorRecord]) -> None:
        if not rows:
            return
        doc_ids = {row.doc_id for row in rows}
        self._delete_by_doc_ids(self.section_collection, doc_ids)
        entities = [
            [row.doc_id for row in rows],
            [row.section_id for row in rows],
            [row.l1_title[:1024] for row in rows],
            [row.l2_title[:1024] for row in rows],
            [row.l3_title[:1024] for row in rows],
            [row.text[:8192] for row in rows],
            [row.vector for row in rows],
        ]
        self.section_collection.insert(entities)
        self.section_collection.flush()

    def _to_hit_payload(self, hit: Any) -> dict[str, object]:
        entity = getattr(hit, "entity", None)
        if entity is None:
            return {}
        payload: dict[str, object] = {}
        for key in ("doc_id", "section_id", "variant", "text", "l1_title", "l2_title", "l3_title"):
            try:
                payload[key] = entity.get(key)
            except Exception:
                pass
        return payload

    def search_doc_vectors(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        results = self.doc_collection.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=top_k,
            output_fields=["doc_id", "variant", "text"],
        )
        hits = results[0] if results else []
        return [
            SearchHit(score=float(getattr(hit, "distance", 0.0)), payload=self._to_hit_payload(hit))
            for hit in hits
        ]

    def search_section_vectors(
        self, query_vector: list[float], doc_id: int, top_k: int
    ) -> list[SearchHit]:
        results = self.section_collection.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            expr=f"doc_id == {doc_id}",
            limit=top_k,
            output_fields=["doc_id", "section_id", "text", "l1_title", "l2_title", "l3_title"],
        )
        hits = results[0] if results else []
        return [
            SearchHit(score=float(getattr(hit, "distance", 0.0)), payload=self._to_hit_payload(hit))
            for hit in hits
        ]
