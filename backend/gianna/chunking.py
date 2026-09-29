"""Exact token budgets, paragraph-aware packing and small overlap. No semantic text rewriting."""
import hashlib
import re
import uuid
from .errors import DomainError


def input_prefix(record):
    return f"passage: {record['title'][:200]}\nTema: {record['topic'][:100]}\n"


def pack_record(record,counter,limit=420,overlap=40):
    if not 180<=limit<=480 or not 0<=overlap<=80:raise DomainError('Perfil de fragmentación inválido.')
    prefix=input_prefix(record)
    if counter(prefix)>limit-30:raise DomainError('El encabezado no deja espacio suficiente para el texto.')
    text=record['text']; spans=[]; start=0
    # Splitting uses source character offsets. Binary search prevents silent tokenizer truncation.
    while start<len(text):
        rest=text[start:]
        if counter(prefix+rest)<=limit:
            end=len(text)
        else:
            lo=start+1;hi=len(text)
            while lo<hi:
                mid=(lo+hi+1)//2
                if counter(prefix+text[start:mid])<=limit:lo=mid
                else:hi=mid-1
            end=lo
            # Prefer a paragraph/sentence end, but don't create extremely small fragments.
            partial=text[start:end]
            breaks=[m.end() for m in re.finditer(r'\n\n|(?<=[.!?])\s+',partial)]
            viable=[p for p in breaks if p>len(partial)*0.55]
            if viable:end=start+viable[-1]
            else:
                ws=text.rfind(' ',start,end)
                if ws>start+len(partial)*0.65:end=ws+1
        body=text[start:end].strip()
        if body:
            embedded=prefix+body
            if counter(embedded)>limit:raise DomainError('Fragmento fuera del presupuesto de tokens.')
            spans.append({'text':body,'embedding_text':embedded,'char_start':start,'char_end':end,'token_count':counter(embedded)})
        if end>=len(text):break
        new_start=end
        if overlap:
            lo=start+1;hi=end
            while lo<hi:
                mid=(lo+hi)//2
                if counter(text[mid:end])<=overlap:hi=mid
                else:lo=mid+1
            new_start=lo
            ws=text.find(' ',new_start,end)
            if ws>=0:new_start=ws+1
        start=max(start+1,new_start)
    return spans


def chunks_for_record(version_id,record,counter,limit,overlap):
    items=pack_record(record,counter,limit,overlap)
    result=[]
    for i,item in enumerate(items):
        digest=hashlib.sha256(item['embedding_text'].encode()).hexdigest()
        id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'gianna:{version_id}:{record["id"]}:{i}:{digest}'))
        result.append({'id':id,'record_id':record['id'],'position':i,'title':record['title'],'topic':record['topic'],
            'audience':'public','evidence_type':record['evidence_type'],'cutoff_date':record.get('cutoff_date'),
            'source_refs':record.get('source_refs',[]),'zones':record.get('zones',[]),'embedding_hash':digest,**item})
    return result
