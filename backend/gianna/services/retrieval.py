"""Recuperación híbrida: denso + BM25 español (RRF en LanceDB) fusionado con un cross-encoder.

La unidad de recuperación es el chunk; la unidad que ve el agente es la ficha
completa (small-to-big). Cada llamada devuelve fichas públicas con sus condiciones,
nivel de evidencia y fuentes, listas para citar.
"""
import json
import time
from functools import lru_cache

from ..domain import ZONES, record_kind, zone_names
from ..chunking import CONTEXTUALIZER_VERSION, input_prefix
from ..errors import DomainError
from .neural import LEGACY_ENGINE_VERSION

RRF_K = 60


def _fuse(*rankings, weights=None):
    """Reciprocal Rank Fusion sobre listas de ids ordenadas de mejor a peor."""
    weights = weights or [1.0] * len(rankings)
    scores = {}
    for weight, ranking in zip(weights, rankings):
        for rank, key in enumerate(ranking, 1):
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank)
    return scores


class Retriever:
    def __init__(self, db, knowledge, embeddings, vector_store):
        self.db = db
        self.knowledge = knowledge
        self.embeddings = embeddings
        self.vector_store = vector_store

    def version(self, version_id=None):
        version = self.db.one('SELECT * FROM versions WHERE id=?', (version_id,)) if version_id else self.knowledge.active()
        if not version or version['status'] != 'ready':
            raise DomainError('Todavía no hay una base lista para consultar.', 503, 'no_knowledge')
        return version

    def engine(self, version):
        profile = json.loads(version['profile_json'])
        engine = self.embeddings.for_profile(profile) if hasattr(self.embeddings, 'for_profile') else self.embeddings
        if engine.model is None:
            raise DomainError('El motor se está preparando. Volvé a intentar en unos segundos.', 503, 'warming_up')
        if engine.profile['fingerprint'] != profile.get('fingerprint'):
            raise DomainError('La base usa otra versión del modelo. Reindexá antes de publicarla.', 503, 'embedding_mismatch')
        expected = 'bekko-context-v2' if profile.get('engine') == LEGACY_ENGINE_VERSION else CONTEXTUALIZER_VERSION
        if profile.get('contextualizer_version') != expected:
            raise DomainError('La base usa otra representación documental. Reindexá antes de consultarla.', 503, 'index_profile_mismatch')
        return engine

    def records(self, version_id, keys):
        keys = list(dict.fromkeys(keys))
        if not keys:
            return {}
        marks = ','.join('?' for _ in keys)
        rows = self.db.all(f'SELECT record_key,content_json FROM version_records WHERE version_id=? AND record_key IN ({marks})',
                           (version_id, *keys))
        return {row['record_key']: json.loads(row['content_json']) for row in rows}

    def sources(self, version_id, record):
        result = []
        for source_id in record.get('source_refs', []):
            row = self.db.one('SELECT content_json FROM version_sources WHERE version_id=? AND source_key=?', (version_id, source_id))
            if row:
                result.append(json.loads(row['content_json']))
        return result

    def card(self, version_id, record, score=0.0, channels=()):
        return {
            'record_id': record['id'], 'title': record['title'], 'topic': record['topic'],
            'section': record.get('section', ''), 'kind': record_kind(record), 'text': record['text'],
            'conditions': record.get('conditions', []), 'zones': record.get('zones', []),
            'opportunity_id': record.get('opportunity_id'), 'evidence_type': record['evidence_type'],
            'cutoff_date': record.get('cutoff_date'), 'period': record.get('period', ''),
            'locator': record.get('source_locator', ''), 'source_refs': record.get('source_refs', []),
            'score': round(score, 5), 'channels': list(channels), 'version_id': version_id,
        }

    def search(self, query, settings, version_id=None, zones=None, kinds=None, limit=8, mode='hybrid'):
        """Devuelve (fichas, trace). ``zones`` y ``kinds`` son filtros opcionales y blandos.

        ``mode``: 'hybrid' (denso + BM25 con RRF, 60 ms; predeterminado), 'fused' (agrega el cross-encoder,
        ~5 s en CPU) o 'rerank'. En la evaluación con el conjunto de oro el cross-encoder no mejoró el
        resultado híbrido, por eso no está en el camino de las consultas.
        """
        started = time.perf_counter()
        version = self.version(version_id)
        engine = self.engine(version)
        zones = [z for z in (zones or []) if z in ZONES]
        text = query.strip()
        if zones:
            text += ' | ' + '; '.join(zone_names(zones))
        dense, lexical = engine.query(text)
        pool = settings.retrieval_candidates
        points = self.vector_store.search(version['collection_name'], dense, lexical, pool, pool)
        if zones:
            # Búsqueda adicional restringida a la zona: las fichas generales no se pierden
            # porque la búsqueda sin filtro ya las incluye.
            points += self.vector_store.search(version['collection_name'], dense, lexical, pool, pool, zones=zones)
        if kinds:
            points += self.vector_store.search(version['collection_name'], dense, lexical, pool, pool, record_types=kinds)
        if not points:
            return [], {'query': text, 'candidates': 0, 'ms': round((time.perf_counter() - started) * 1000, 1)}
        by_chunk = {}
        for point in points:
            known = by_chunk.get(str(point['id']))
            if known:
                known['score'] += point['score']
                known['channels'] = sorted(set(known['channels']) | set(point.get('channels', [])))
            else:
                by_chunk[str(point['id'])] = {**point, 'id': str(point['id']), 'channels': list(point.get('channels', []))}
        ordered_chunks = sorted(by_chunk.values(), key=lambda p: (-p['score'], p['id']))[:pool]
        marks = ','.join('?' for _ in ordered_chunks)
        chunks = {row['id']: row for row in self.db.all(
            f'SELECT id,record_key,text FROM chunks WHERE version_id=? AND id IN ({marks})',
            (version['id'], *[p['id'] for p in ordered_chunks]))}
        records = self.records(version['id'], [c['record_key'] for c in chunks.values()])

        candidates = []
        seen = set()
        for point in ordered_chunks:
            chunk = chunks.get(point['id'])
            record = records.get(chunk['record_key']) if chunk else None
            if not record or record.get('audience') != 'public' or record['id'] in seen:
                continue
            seen.add(record['id'])
            candidates.append({'record': record, 'chunk': chunk['text'], 'hybrid': point['score'], 'channels': point.get('channels', [])})

        rerank_scores = []
        if mode != 'hybrid':
            try:
                rerank_scores = engine.rerank(query, [input_prefix(c['record']) + c['chunk'] for c in candidates])
            except DomainError:
                rerank_scores = []
        hybrid_rank = [c['record']['id'] for c in candidates]
        if rerank_scores:
            reranked = [c['record']['id'] for c, _ in sorted(zip(candidates, rerank_scores), key=lambda x: -x[1])]
            fused = _fuse(reranked) if mode == 'rerank' else _fuse(hybrid_rank, reranked, weights=[1.0, 0.7])
        else:
            fused = _fuse(hybrid_rank)
        zone_set = set(zones)
        for c in candidates:
            record = c['record']
            if zone_set and zone_set & set(record.get('zones', [])):
                fused[record['id']] += 0.004
            if kinds and record_kind(record) in kinds:
                fused[record['id']] += 0.004
        ranked = sorted(candidates, key=lambda c: -fused[c['record']['id']])[:limit]
        cards = [self.card(version['id'], c['record'], fused[c['record']['id']], c['channels']) for c in ranked]
        trace = {'query': text, 'candidates': len(candidates), 'ms': round((time.perf_counter() - started) * 1000, 1),
                 'ids': [card['record_id'] for card in cards]}
        return cards, trace

    def get(self, record_id, version_id=None):
        version = self.version(version_id)
        record = self.records(version['id'], [record_id]).get(record_id)
        if not record or record.get('audience') != 'public':
            return None
        return self.card(version['id'], record)

    @lru_cache(maxsize=4)
    def _outline(self, version_id):
        rows = self.db.all('SELECT record_key,content_json FROM version_records WHERE version_id=? ORDER BY record_key', (version_id,))
        outline = []
        for row in rows:
            record = json.loads(row['content_json'])
            if record.get('audience') == 'public':
                outline.append({'id': record['id'], 'title': record['title'], 'topic': record['topic'], 'kind': record_kind(record),
                                'zones': record.get('zones', []), 'opportunity_id': record.get('opportunity_id'),
                                'evidence_type': record['evidence_type']})
        return outline

    def outline(self, version_id=None):
        version = self.version(version_id)
        return version['id'], self._outline(version['id'])
