#!/usr/bin/env python3
"""Convert a DOCX to a self-contained package and a faithful editorial Markdown copy."""
import argparse
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gianna.corpus import convert_docx,export_jsonl,Corpus


def main():
    p=argparse.ArgumentParser()
    p.add_argument('input',type=Path);p.add_argument('--output',type=Path,default=Path('knowledge'))
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    corpus,markdown,blocks=convert_docx(a.input)
    stem='invest_lavalleja_2026' if corpus.document.id=='invest-lavalleja-2026' else corpus.document.id
    (a.output/f'{stem}.gianna.json').write_text(corpus.model_dump_json(indent=2),encoding='utf-8')
    (a.output/f'{stem}.jsonl').write_text(export_jsonl(corpus),encoding='utf-8')
    (a.output/'guia_completa_preservada.md').write_text(markdown,encoding='utf-8')
    (a.output/'fuentes.json').write_text(json.dumps([s.model_dump() for s in corpus.sources],ensure_ascii=False,indent=2),encoding='utf-8')
    (a.output/'informe_conversion.json').write_text(json.dumps(corpus.conversion_report,ensure_ascii=False,indent=2),encoding='utf-8')
    (a.output/'bloques_originales.json').write_text(json.dumps(blocks,ensure_ascii=False,indent=2),encoding='utf-8')
    for audience in ('public','internal'):
        records=[r for r in corpus.records if r.audience==audience]
        if not records: continue
        refs={s for r in records for s in r.source_refs}
        sub=Corpus(document=corpus.document,sources=[s for s in corpus.sources if s.id in refs],records=records)
        (a.output/f'{audience}.jsonl').write_text(export_jsonl(sub),encoding='utf-8')
    print(json.dumps({k:v for k,v in corpus.conversion_report.items() if k!='excluded_from_embedding'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
