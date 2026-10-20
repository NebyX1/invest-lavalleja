"""Regression tests for the supplied-document conversion, independent of inference."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import unittest

from consolidate import parse_fiches, parse_sources, source_union, make_record, remap_inline, CUTOFF

FOLDER = Path(__file__).resolve().parents[1]


class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads((FOLDER / 'consolidated' / 'Invest_Lavalleja_2026_10_19_consolidado.gianna.json').read_text(encoding='utf-8'))
        cls.blocks = raw['conversion_report']['supplement_archive']['blocks']
        cls.by_id = {b['id']: b for b in cls.blocks}
        cls.fiches = parse_fiches(cls.blocks)
        cls.entries = parse_sources(cls.blocks)
        cls.sources, cls.aliases = source_union(cls.entries)
        cls.corpus = raw

    def test_fiche_counts_and_evidence_are_explicit(self):
        self.assertEqual(len(self.fiches), 128)
        self.assertTrue(all(f['refs'] and f['condition'] and f['blocks'] for f in self.fiches))
        self.assertEqual({f['evidence_type'] for f in self.fiches}, {'hypothesis', 'mixed', 'documented_in_source'})

    def test_same_url_sources_keep_all_original_locators(self):
        self.assertEqual(len(self.entries), 127)
        self.assertEqual(len(self.sources), 122)
        self.assertEqual(self.aliases['TS001'], 'EN002')
        self.assertEqual(self.aliases['TS002'], self.aliases['TR003'])
        for source in self.entries:
            canonical = next(s for s in self.sources if s['id'] == self.aliases[source['id']])
            self.assertIn(source['locator'], canonical['description'])
            self.assertEqual(source['url'], canonical['url'])

    def test_no_unmarked_source_reverification(self):
        self.assertTrue(all(s['verification'] == 'transcribed_from_supplied_docx_not_independently_reverified' for s in self.sources))

    def test_all_unmerged_fiche_bodies_and_conditions_retrievable(self):
        records = {r['id']: r for r in self.corpus['records']}
        for fiche in self.fiches:
            if fiche['id'] in ('AG-032', 'TS-022'):
                continue  # This explicit editorial merge has a separate test below.
            record = records[fiche['id']]
            self.assertIn(remap_inline(fiche['body'], self.aliases), record['text'])
            self.assertIn(fiche['condition'], record['text'])
            self.assertIn(fiche['condition'], record['conditions'])
            self.assertEqual(record['cutoff_date'], CUTOFF)

    def test_no_aliased_source_citations_left_dangling(self):
        for fiche in self.fiches:
            record = make_record(fiche, self.aliases, self.by_id)
            self.assertTrue(set(record['source_refs']) <= {s['id'] for s in self.sources})
        self.assertEqual(remap_inline('[TS001, TS002] arts. 43–48, 150 kW y 31/12/2026', self.aliases), '[EN002, AG038] arts. 43–48, 150 kW y 31/12/2026')

    def test_record_merge_cannot_mutate_extracted_input_blocks(self):
        fiche = deepcopy(self.fiches[0]); original_blocks = list(fiche['blocks'])
        record = make_record(fiche, self.aliases, self.by_id)
        record['original_block_ids'].append('example-merge')
        self.assertEqual(fiche['blocks'], original_blocks)

    def test_ecopoints_unique_details_from_both_fiches(self):
        record = next(r for r in self.corpus['records'] if r['id'] == 'AG-032')
        for fact in ('15', '60', '23 de septiembre de 2026', 'plazas Libertad y Rivera', 'UTU Central',
                     'financiamiento privado', 'educación de usuarios', 'titularidad', 'destino autorizado'):
            self.assertIn(fact, record['text'])
        self.assertEqual(len(record['original_block_ids']), 10)
        self.assertFalse(any(r['id'] == 'TS-022' for r in self.corpus['records']))

    def test_territorial_table_preserves_every_cell_with_its_header(self):
        table = self.by_id['t003']
        for row in table['rows'][1:]:
            zone = row['cells'][0].splitlines()[0].lower()
            record = next(r for r in self.corpus['records'] if r['id'] == 'territorio-20261019-' + zone)
            for header, cell in zip(table['rows'][0]['cells'], row['cells']):
                self.assertIn(header + ': ' + cell, record['text'])

    def test_historical_periods_and_closed_calls_not_relabelled_current(self):
        records = {r['id']: r for r in self.corpus['records']}
        self.assertIn('2016/2017', records['EN-024']['text'])
        self.assertIn('2012', records['EN-007']['text'])
        self.assertIn('ya había pasado', records['TS-016']['text'])
        self.assertIn('ya estaba cerrada', records['TS-018']['text'])
        self.assertIn('plazo previo', records['EN-032']['text'])

    def test_internal_archive_not_converted_into_public_records(self):
        content = '\n'.join(r['text'] for r in self.corpus['records'] if r['audience'] == 'public')
        self.assertNotIn('30fb0b45b642d9e7b5b5568fa688def866f599d2', content)
        self.assertNotIn('Las 128 fichas nuevas tienen metadatos', content)
        self.assertIn('p0010', self.corpus['conversion_report']['block_coverage'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConversionTests))
    if args.output:
        args.output.write_text(json.dumps({'tests_run': result.testsRun, 'successful': result.wasSuccessful(),
                                          'failures': [(str(test), detail) for test, detail in result.failures],
                                          'errors': [(str(test), detail) for test, detail in result.errors]},
                                         ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
