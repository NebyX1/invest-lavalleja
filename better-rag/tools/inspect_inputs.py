"""Inspect the supplied knowledge files without changing them."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def inspect_docx(path):
    doc=Document(path);blocks=[];paragraphs=0;tables=0
    for node in doc.element.body:
        if node.tag==qn('w:p'):
            paragraphs+=1;p=Paragraph(node,doc);text=p.text.strip();links=[]
            for link in node.iter(qn('w:hyperlink')):
                rel=link.get(qn('r:id'))
                if rel in doc.part.rels:links.append(doc.part.rels[rel].target_ref)
            if text:blocks.append({'id':f'p{paragraphs:04}','kind':'paragraph','style':p.style.name,'text':text,'links':links})
        elif node.tag==qn('w:tbl'):
            tables+=1;table=Table(node,doc);rows=[]
            for index,row in enumerate(table.rows):
                seen=set();cells=[]
                for cell in row.cells:
                    if cell._tc in seen:continue
                    seen.add(cell._tc);cells.append(cell.text.strip())
                rows.append({'id':f't{tables:03}.r{index:02}','cells':cells})
            blocks.append({'id':f't{tables:03}','kind':'table','rows':rows})
    with ZipFile(path) as package:
        xml=package.read('word/document.xml').decode('utf-8')
        extras={name:package.read(name).decode('utf-8') for name in package.namelist()
            if name.startswith(('word/footnotes','word/endnotes','word/comments')) and name.endswith('.xml')}
    return {'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'blocks':blocks,
        'structure':{'paragraphs':paragraphs,'tables':tables,'inline_images':len(doc.inline_shapes),
            'tracked_insertions':xml.count('<w:ins '),'tracked_deletions':xml.count('<w:del '),
            'textboxes':xml.count('<w:txbxContent'),'extra_parts':list(extras)},'extra_xml':extras}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True);args=parser.parse_args();args.work.mkdir(parents=True,exist_ok=True)
    for path in sorted(args.folder.iterdir()):
        if path.suffix.lower()=='.docx':
            data=inspect_docx(path);output=args.work/(path.stem+'.blocks.json')
            output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in data.items() if k not in {'blocks','extra_xml'}},ensure_ascii=False))
            for block in data['blocks']:
                if block['kind']=='table':print(json.dumps({'id':block['id'],'rows':len(block['rows']),'header':block['rows'][0]['cells']},ensure_ascii=False))
                elif block['style'].startswith(('Heading','Title','Subtitle')):print(json.dumps(block,ensure_ascii=False))
        elif path.suffix.lower()=='.json':
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            print(json.dumps({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'records':len(data.get('records',[])),'sources':len(data.get('sources',[])),
                'audiences':dict(Counter(r.get('audience') for r in data.get('records',[])))},ensure_ascii=False))
            inventory=[{k:record.get(k) for k in ('id','title','topic','audience','evidence_type','source_refs')} for record in data['records']]
            (args.work/(path.stem+'.inventory.json')).write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
