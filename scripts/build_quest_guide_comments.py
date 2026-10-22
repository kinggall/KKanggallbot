"""Build short, source-attributed sortie notes from saved HTML only."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import quests
from guide_lookup import record_matches,article_matches
from quest_guide_comments import source_facts,notes
from scripts.verify_guides import collection_scope


def build(root=ROOT):
    root=Path(root);catalog=quests.catalog();entries={}
    overrides=json.loads((root/'data/quest_guide_comment_overrides.json').read_text(encoding='utf-8'))
    targets=[q for q in collection_scope(catalog) if q['category']=='sortie']
    for quest in targets:
        code=quest['wiki_id'];folder=root/'guide_cache/zekamashi'/re.sub(r'[^A-Za-z0-9_-]','_',code)
        entry={'facts':[],'kind':'quest_conditions_only'}
        p=folder/'manifest.json';a=folder/'article.html'
        record=json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}
        if record.get('status')=='downloaded' and record_matches(record,quest) and a.is_file():
            html=a.read_text(encoding='utf-8')
            if article_matches(html,record,quest):
                entry.update(html_sha256=hashlib.sha256(html.replace('\r\n','\n').encode()).hexdigest(),
                             url=record['url'],facts=source_facts(html,quest),kind='source_terms_and_conditions')
                if code in overrides:
                    manual=overrides[code]
                    entry.update(facts=[dict(f,kind='reviewed_source_summary') for f in manual['facts']],
                                 text_only=manual.get('text_only',False),
                                 general_only_maps=manual.get('general_only_maps',[]),
                                 review_note=manual.get('review_note'),evidence=manual.get('evidence'),
                                 kind='reviewed_source_summary')
        entries[code]=entry
    output=root/'guide_cache/guide_audit';output.mkdir(parents=True,exist_ok=True)
    result={'created_at':datetime.now(timezone.utc).isoformat(),
            'policy':'명시된 전술 용어의 짧은 한국어 요약과 임무 조건. 장문 전체 자동 번역이나 사진 속 편성의 수동 검증을 뜻하지 않음.',
            'quests':entries}
    (output/'quest_guide_comments.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 출격 임무 코멘트 전체 검토본','',result['policy'],
           '전용 원문이 없는 임무에는 원문 코멘트를 만들어 넣지 않고 임무 조건을 요약합니다.',
           '부정·불필요·구편성 표현은 긍정 권장사항으로 번역하지 않습니다. 숫자·경로를 임의로 생성하지 않습니다.','']
    missing=[];untranslated=[]
    for quest in targets:
        code=quest['wiki_id'];entry=entries[code];korean=notes(quest,root)
        if not 2<=len(korean)<=3:missing.append(code)
        if any(re.search('[\u3040-\u30ff\u4e00-\u9fff]',line) for line in korean):untranslated.append(code)
        lines.extend(['## '+code+': '+quest['name_ko'],'', '자료 유형: '+entry['kind'],'',
                      *('· '+line for line in korean),''])
        if entry.get('review_note'):lines.extend(['추가 확인: '+entry['review_note'],''])
        if entry.get('url'):lines.extend(['원문: '+entry['url'],''])
        quotes=list(dict.fromkeys(f.get('quote','') for f in entry['facts'] if f.get('quote')))
        if quotes:
            lines.extend(['<details><summary>추출 근거 (장문 전체 번역 아님)</summary>','',
                          *(quote.replace('\n',' ') for quote in quotes[:3]),'','</details>',''])
    (output/'QUEST_GUIDE_COMMENTS_REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Built comments for {len(targets)} sortie quests; source-backed {sum(bool(e["facts"]) for e in entries.values())}; condition summaries {sum(not e["facts"] for e in entries.values())}; bad line counts {missing}')
    if missing or untranslated:raise RuntimeError('Missing/untranslated comments: '+str(missing+untranslated))
    return result


if __name__=='__main__':build()
