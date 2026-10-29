"""Dobles deterministas para las pruebas del agente. No son embeddings ni una base vectorial reales."""
import hashlib

import numpy as np

from gianna.errors import DomainError


class FakeEmbeddings:
    def __init__(self):
        self.model = None
        self.calls = 0
        self.queries = []
        self.profile = {'fingerprint': 'test-fingerprint', 'dim': 384, 'runtime': 'DETERMINISTIC_TEST_DOUBLE'}

    def load(self, on_progress=None):
        self.model = True

    def count(self, text):
        return len(text.split()) + 2

    def documents(self, texts, lexical):
        self.load()
        self.calls += len(texts)
        dense = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            vector = np.random.default_rng(seed).normal(size=384)
            vector /= np.linalg.norm(vector)
            dense.append(vector.tolist())
        return dense, list(lexical)

    def query(self, text):
        self.queries.append(text)
        return [0.0] * 384, text

    def rerank(self, query, texts):
        return [1.0 / (i + 1) for i in range(len(texts))]


class FakeLanceStore:
    def __init__(self):
        self.collections = {}

    def create(self, name):
        self.collections.setdefault(name, {})

    def upsert(self, name, chunks, dense, sparse):
        for chunk in chunks:
            self.collections[name][chunk['id']] = {'id': chunk['id'], 'zones': chunk.get('zones', []),
                                                   'record_type': chunk.get('record_type')}

    def finalize(self, name):
        pass

    def count(self, name):
        return len(self.collections[name])

    def delete(self, name):
        self.collections.pop(name, None)

    def search(self, name, dense, lexical, candidates=30, limit=20, zones=None, opportunity_ids=None, record_types=None):
        points = list(self.collections[name].values())
        if zones:
            points = [p for p in points if set(zones) & set(p['zones'])]
        if record_types:
            points = [p for p in points if p['record_type'] in set(record_types)]
        return [{'id': p['id'], 'score': .5, 'channels': ['dense']} for p in points[:limit]]
