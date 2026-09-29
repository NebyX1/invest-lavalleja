"""Canonical, reviewable knowledge. Conversion preserves wording and never verifies its truth."""
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
import hashlib
import json
import re
import unicodedata
import zipfile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from .errors import DomainError

SCHEMA='gianna.corpus.v1'
AUDIENCES=('public','internal')
EVIDENCE=('documented_in_source','hypothesis','mixed','didactic_example','institutional_proposal','reference')


class Source(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=100,pattern=r'^[\w.-]+$')
    title: str = Field(min_length=1,max_length=500)
    description: str = Field(default='',max_length=5000)
    url: str = Field(default='',max_length=2048)
    accessed_at: str | None = None
    verification: str = Field(default='transcribed_from_document_not_reverified',max_length=200)
    locator: str = Field(default='',max_length=500)

    @field_validator('url')
    @classmethod
    def valid_url(cls,value):
        if value:
            u=urlsplit(value)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
                raise ValueError('Solo enlaces HTTP/HTTPS, sin credenciales.')
        return value


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=140,pattern=r'^[\w.-]+$')
    title: str = Field(min_length=1,max_length=500)
    section: str = Field(default='',max_length=500)
    topic: str = Field(default='General',min_length=1,max_length=160)
    audience: Literal['public','internal']='internal'
    evidence_type: Literal['documented_in_source','hypothesis','mixed','didactic_example','institutional_proposal','reference']='mixed'
    text: str = Field(min_length=1,max_length=80000)
    conditions: list[str] = Field(default_factory=list,max_length=24)
    source_refs: list[str] = Field(default_factory=list,max_length=100)
    zones: list[str] = Field(default_factory=list,max_length=20)
    opportunity_id: str | None = None
    cutoff_date: str | None = None
    period: str = Field(default='',max_length=300)
    source_locator: str = Field(default='',max_length=1500)
    original_block_ids: list[str] = Field(default_factory=list,max_length=500)
    original_sha256: str = ''
    enabled: bool = True

    @field_validator('cutoff_date')
    @classmethod
    def valid_date(cls,v):
        if v: date.fromisoformat(v)
        return v

    @field_validator('conditions')
    @classmethod
    def conditions_bounded(cls,v):
        if any(len(s)>6000 for s in v): raise ValueError('Condición demasiado extensa.')
        return v


class DocumentInfo(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=140)
    title: str = Field(min_length=1,max_length=500)
    filename: str = Field(default='',max_length=300)
    sha256: str = ''
    cutoff_date: str | None = None
    conversion_note: str = Field(default='',max_length=4000)


class Corpus(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version: Literal['gianna.corpus.v1']=SCHEMA
    document: DocumentInfo
    sources: list[Source] = Field(default_factory=list,max_length=10000)
    records: list[Record] = Field(min_length=1,max_length=10000)
    conversion_report: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def unique_and_linked(self):
        ids=[r.id for r in self.records]; source_ids=[s.id for s in self.sources]
        if len(ids)!=len(set(ids)): raise ValueError('Identificadores de registros duplicados.')
        if len(source_ids)!=len(set(source_ids)): raise ValueError('Identificadores de fuentes duplicados.')
        missing={ref for r in self.records for ref in r.source_refs}-set(source_ids)
        if missing: raise ValueError('Referencias sin registro de fuente: '+', '.join(sorted(missing)))
        return self


def slug(text):
    text=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',text).strip('-')[:80] or 'contenido'


def source_refs(text):
    refs=set(re.findall(r'\bS\d{2}\b',text))
    for a,b in re.findall(r'\bS(\d{2})\s*[–—-]\s*S?(\d{2})\b',text):
        if 0<int(a)<=int(b)<=99:
            refs.update(f'S{x:02}' for x in range(int(a),int(b)+1))
    return sorted(refs)


def validate_docx(path):
    if not zipfile.is_zipfile(path): raise DomainError('El archivo no es un DOCX válido.')
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        if len(infos)>2000 or sum(i.file_size for i in infos)>40*1024*1024:
            raise DomainError('El DOCX expandido supera los límites de seguridad.')
        if 'word/document.xml' not in z.namelist(): raise DomainError('Falta el documento Word principal.')
        for i in infos:
            p=PurePosixPath(i.filename)
            if '..' in p.parts or p.is_absolute() or i.flag_bits&1 or i.filename.lower().endswith('vbaproject.bin'):
                raise DomainError('Contenedor DOCX no permitido.')
            if i.file_size>1024*1024 and i.file_size/max(i.compress_size,1)>300:
                raise DomainError('Compresión excesiva en el DOCX.')
            if i.filename.endswith(('.xml','.rels')) and b'<!DOCTYPE' in z.read(i):
                raise DomainError('Definiciones XML externas no permitidas.')


def extract_docx(path):
    """Paragraph/table order is preserved. Locator counts are DOCX blocks, not inferred pages."""
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    from docx.oxml.ns import qn
    validate_docx(path)
    doc=Document(path); blocks=[]; paragraph_number=0; table_number=0
    for body_index,node in enumerate(doc.element.body):
        if node.tag==qn('w:p'):
            p=Paragraph(node,doc); paragraph_number+=1
            # python-docx 1.2 preserves hyperlinks and explicit line/tab breaks in paragraph text.
            text=Paragraph(node, doc).text.strip()
            urls=[]
            for h in node.iter(qn('w:hyperlink')):
                relation=h.get(qn('r:id'))
                if relation and relation in doc.part.rels:
                    urls.append(doc.part.rels[relation].target_ref)
            if text:
                blocks.append({'id':f'p{paragraph_number:04}','kind':'paragraph','style':p.style.name,'text':text,'urls':urls,'body_index':body_index})
        elif node.tag==qn('w:tbl'):
            table_number+=1; table=Table(node,doc); rows=[]
            for ri,row in enumerate(table.rows):
                cells=[]; seen=set()
                for cell in row.cells:
                    # A merged cell is stored just once in the logical row.
                    if cell._tc in seen: continue
                    seen.add(cell._tc)
                    cells.append('\n'.join(p.text for p in cell.paragraphs).strip())
                rows.append(cells)
            text='\n'.join(' | '.join(cells) for cells in rows)
            if text.strip(): blocks.append({'id':f't{table_number:03}','kind':'table','style':'Table','text':text,'rows':rows,'urls':[],'body_index':body_index})
    return blocks


def make_sections(blocks):
    result=[]; current=None; pending=None
    for block in blocks:
        text=block['text']
        is_label=(block['kind']=='paragraph' and block['style'] not in ('Heading 1','Heading 2','Title','Subtitle') and len(text)<150 and
                 ('ANEXO INTERNO /' in text or 'FUENTES Y TRAZABILIDAD'==text or re.match(r'^(\d{2}|Z\d)\s*/',text) or text in {'APERTURA','LECTURA','ÍNDICE'}))
        if is_label:
            if pending:
                if current: current['blocks'].append(pending)
            pending=block
            continue
        if block['style'] in ('Heading 1','Title'):
            if current: result.append(current)
            current={'title':text,'label':pending['text'] if pending else '', 'blocks':([pending] if pending else [])+[block]}
            pending=None
        else:
            if current is None: current={'title':'Apertura','label':'','blocks':[]}
            if pending: current['blocks'].append(pending); pending=None
            current['blocks'].append(block)
    if pending:
        if current is None: current={'title':'Contenido','label':'','blocks':[]}
        current['blocks'].append(pending)
    if current: result.append(current)
    return result


def markdown_blocks(blocks):
    out=[]
    for b in blocks:
        if b['kind']=='table':
            rows=b['rows']
            cols=max(map(len,rows),default=1)
            def row(cells): return '| '+' | '.join(x.replace('|','\\|').replace('\n','<br>') for x in cells+['']*(cols-len(cells)))+' |'
            out += [row(rows[0]),'| '+' | '.join(['---']*cols)+' |']+[row(r) for r in rows[1:]]+['']
        else:
            prefix={'Title':'# ','Heading 1':'## ','Heading 2':'### '}.get(b['style'],'')
            out.append(prefix+b['text'])
            for u in b['urls']: out.append('Fuente enlazada: '+u)
            out.append('')
    return '\n'.join(out)


def convert_docx(path, default_audience='internal', cutoff_date=None):
    path=Path(path); blocks=extract_docx(path); sections=make_sections(blocks)
    alltext='\n'.join(b['text'] for b in blocks)
    profile=('INVEST LAVALLEJA' in alltext and 'Dieciséis fichas' in alltext and 'CORTE DOCUMENTAL: 18 DE SEPTIEMBRE DE 2026' in alltext)
    cutoff_date='2026-09-18' if profile else cutoff_date
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    sources=[]; source_blocks=set()
    for section in sections:
        if not (section['label']=='FUENTES Y TRAZABILIDAD' or section['title'].startswith('Registro de fuentes')): continue
        current=[]
        def finish_source(group):
            if not group: return
            m=re.match(r'^(S\d{2})\s+(.+)',group[0]['text'])
            if not m: return
            urls=[u for b in group for u in b['urls']]
            sources.append(Source(id=m[1],title=m[2],description='\n'.join(b['text'] for b in group[1:]),url=urls[0] if urls else '',accessed_at=cutoff_date,
                                  locator=','.join(b['id'] for b in group)))
            source_blocks.update(b['id'] for b in group)
        for b in section['blocks']:
            if re.match(r'^S\d{2}\s+',b['text']):
                finish_source(current); current=[b]
            elif current and b['style']!='Heading 2': current.append(b)
            elif b['style']=='Heading 2': finish_source(current); current=[]
        finish_source(current)
    known_sources={s.id for s in sources}
    records=[]; represented=set(); excluded=[]; unresolved=[]
    for sn,section in enumerate(sections,1):
        label=section['label']; title=section['title']
        if label in ('ÍNDICE','APERTURA') or title.startswith('Registro de fuentes'):
            excluded.extend({'block_id':b['id'],'reason':'bibliography_registry' if b['id'] in source_blocks else 'navigation_or_editorial_front_matter'} for b in section['blocks'])
            continue
        audience='internal' if 'ANEXO INTERNO' in label else ('public' if profile else default_audience)
        evidence='institutional_proposal' if audience=='internal' else 'mixed'
        if 'EJEMPLO' in label: evidence='didactic_example'
        elif 'EVIDENCIA' in label: evidence='documented_in_source'
        elif label.startswith('Z') or 'CARTERA' in label: evidence='hypothesis'
        topic=label.split(' · ')[0] if label else title
        if '/' in topic: topic=topic.split('/',1)[1].strip()
        subtitles=[b['text'] for b in section['blocks'] if b['style']=='Subtitle']
        captions=[b['text'] for b in section['blocks'] if b['style']=='Caption' and not b['text'].startswith(('ZONAS:','MEDIR:'))]
        # Footnotes remain attached to each subunit as constraints, not silently discarded.
        conditions=(subtitles+captions)[:24]
        groups=[]; group=[]; group_title=title
        def flush():
            nonlocal group,group_title
            if group: groups.append((group_title,group)); group=[]
        for b in section['blocks']:
            if b['style']=='Heading 2':
                flush(); group_title=b['text']; group=[b]
            else: group.append(b)
        flush()
        for gn,(gt,group) in enumerate(groups,1):
            opportunity=re.match(r'^(O\d{2})\s*[·:]',gt)
            # Tabular rows keep column names. Callouts with a single row remain intact.
            units=[]; accumulated=[]
            for b in group:
                if b['kind']=='table' and len(b['rows'])>2 and not opportunity:
                    if accumulated: units.append((gt,accumulated,None)); accumulated=[]
                    headers=b['rows'][0]
                    for ri,row in enumerate(b['rows'][1:],1):
                        txt='\n'.join(f'{headers[i] if i<len(headers) else "Campo "+str(i+1)}: {cell}' for i,cell in enumerate(row))
                        unit=dict(b);unit['text']=txt;unit['id']=f'{b["id"]}.r{ri:02}';unit['parent_block_id']=b['id']
                        units.append((gt+' · '+(row[0][:90] if row else str(ri)),[unit],ri))
                    represented.add(b['id'])
                else: accumulated.append(b)
            if accumulated: units.append((gt,accumulated,None))
            for un,(ut,unit,ri) in enumerate(units,1):
                meaningful=[b for b in unit if b['style'] not in ('Heading 1','Title','Subtitle') and b['text']!=label]
                if not meaningful:
                    # The metadata will preserve these labels; there is nothing to retrieve alone.
                    excluded.extend({'block_id':b['id'],'reason':'heading_preserved_as_metadata'} for b in unit)
                    continue
                text='\n\n'.join(b['text'] for b in meaningful)
                refs=source_refs(text+'\n'+'\n'.join(conditions))
                missing=set(refs)-known_sources
                if missing:
                    unresolved.append({'section':title,'unit':ut,'references':sorted(missing)})
                    refs=[r for r in refs if r in known_sources]
                zs=sorted(set(re.findall(r'\bZ[1-7]\b',text)))
                zone=re.match(r'^(Z[1-7])\s*/',label)
                if zone: zs=[zone[1]]
                if opportunity and 'Todas las zonas' in text: zs=[f'Z{i}' for i in range(1,8)]
                ev='hypothesis' if opportunity else evidence
                rec_id=opportunity[1] if opportunity else f's{sn:02}-{gn:02}-{un:02}'
                orig=[b['id'] for b in unit]
                represented.update(b.get('parent_block_id',b['id']) for b in unit)
                records.append(Record(id=rec_id,title=ut,section=title,topic=topic[:160],audience=audience,evidence_type=ev,
                    text=text,conditions=conditions,source_refs=refs,zones=zs,opportunity_id=opportunity[1] if opportunity else None,
                    cutoff_date=cutoff_date,source_locator='DOCX '+', '.join(orig),original_block_ids=orig,
                    original_sha256=hashlib.sha256(text.encode()).hexdigest()))
    # Preserve all content in original Markdown, including front matter and all internal sections.
    accounted=represented|{x['block_id'] for x in excluded}|source_blocks
    unaccounted=[b['id'] for b in blocks if b['id'] not in accounted]
    report={'profile':'invest-lavalleja-2026' if profile else 'generic-docx', 'blocks_total':len(blocks),
            'paragraphs_with_text':sum(b['kind']=='paragraph' for b in blocks),'tables':sum(b['kind']=='table' for b in blocks),
            'records':len(records),'public_records':sum(r.audience=='public' for r in records),
            'internal_records':sum(r.audience=='internal' for r in records),'sources':len(sources),
            'all_blocks_preserved_in_markdown':True,'unaccounted_block_ids':unaccounted,'excluded_from_embedding':excluded,
            'unresolved_source_references':unresolved,'truth_verification':'not_performed','page_policy':'DOCX block locators are used; printed and rendered page numbers are not inferred.',
            'token_policy':'Logical records only. Exact E5 tokens are computed in the admin indexing job.',
            'publication_policy':'All imported records require editorial approval; internal records never enter public vector collections.'}
    corpus=Corpus(document=DocumentInfo(id='invest-lavalleja-2026' if profile else slug(path.stem),title='Invest Lavalleja · Guía de inversiones 2026' if profile else path.stem,
        filename=path.name,sha256=digest,cutoff_date=cutoff_date,
        conversion_note='Conversión estructural, sin actualización ni verificación externa de los hechos. Tablas conservadas con sus encabezados. Los anexos internos no se publican.'),sources=sources,records=records,conversion_report=report)
    return corpus,markdown_blocks(blocks),blocks


def load_corpus(path, default_audience='internal', cutoff_date=None):
    path=Path(path); suffix=path.suffix.lower()
    if suffix=='.docx': return convert_docx(path,default_audience,cutoff_date)[0]
    if suffix=='.json': return Corpus.model_validate_json(path.read_text(encoding='utf-8-sig'))
    if suffix=='.jsonl':
        # JSONL is self-contained: source and document lines precede record lines.
        document=None; sources=[]; records=[]
        for i,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip(): continue
            d=json.loads(line); kind=d.pop('_kind','record')
            if kind=='document': document=d
            elif kind=='source': sources.append(d)
            elif kind=='record': records.append(d)
            else: raise DomainError(f'Tipo JSONL inválido en línea {i}.')
        if not document: document={'id':slug(path.stem),'title':path.stem,'filename':path.name}
        return Corpus(document=document,sources=sources,records=records)
    if suffix in ('.md','.txt'):
        text=path.read_text(encoding='utf-8-sig'); groups=re.split(r'(?m)^(?=##?\s)',text)
        records=[]
        for i,group in enumerate(groups):
            if not group.strip(): continue
            first=group.splitlines()[0].lstrip('# ').strip()
            records.append(Record(id=f'md-{i:04}',title=first[:500] or path.stem,topic='Importación de texto',
                audience=default_audience,evidence_type='mixed',text=group.strip(),cutoff_date=cutoff_date,source_locator=f'{path.name}: sección {i+1}'))
        return Corpus(document={'id':slug(path.stem),'title':path.stem,'filename':path.name,'cutoff_date':cutoff_date},records=records)
    raise DomainError('Formatos admitidos: .gianna.json, .jsonl, .docx, .md y .txt. No se aceptan ZIP ni ejecutables.')


def export_jsonl(corpus):
    rows=[{'_kind':'document',**corpus.document.model_dump()}]
    rows += [{'_kind':'source',**s.model_dump()} for s in corpus.sources]
    rows += [{'_kind':'record',**r.model_dump()} for r in corpus.records]
    return '\n'.join(json.dumps(r,ensure_ascii=False,allow_nan=False) for r in rows)+'\n'
