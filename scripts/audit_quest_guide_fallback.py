"""Preserve the old review groups and audit quest-to-general-map navigation offline."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import guide_lookup
import quests
from scripts.verify_guides import collection_scope

GROUPS={1:'특정 함선＋개장형 명시',2:'특정 함선 지정, 개장형 명시 없음',
        3:'특정함 지정 없음＋고정 해역 있음',4:'특정함 지정 없음＋고정 해역 없음'}


def historical_groups(text):
    result={};group=None
    for line in text.splitlines():
        heading=re.match(r'^## (\d+)\.',line)
        if heading:group=int(heading[1])
        row=re.match(r'^\|\s*([A-Za-z]+\d+)\s*\|',line)
        if row and group in GROUPS:result[row[1].casefold()]=group
    return result


def audit(root=ROOT):
    root=Path(root);output=root/'guide_cache/guide_audit';output.mkdir(parents=True,exist_ok=True)
    historical=output/'GUIDE_MANUAL_REVIEW_20261022.md'
    if not historical.is_file():
        source=root.parent/'GUIDE_MANUAL_REVIEW.md'
        if not source.is_file():raise RuntimeError('Historical manual review file is missing')
        shutil.copy2(source,historical)
    original=historical.read_bytes();groups=historical_groups(original.decode('utf-8'))
    if Counter(groups.values())!=Counter({1:17,2:28,3:23,4:10}):
        raise RuntimeError('Historical classification changed; review before reclassifying')
    baseline_path=output/'pre_fallback_20261023/guide_audit.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
    previous={r['code']:r for r in baseline['quests']}
    # Compare against the renderer before this feature, not against this audit's
    # potentially newer HEAD. This code is read only from the local Git history.
    revision='3185555'
    source=subprocess.run(['git','show',revision+':guide_lookup.py'],cwd=root,
                          capture_output=True,text=True,check=True).stdout
    old=types.ModuleType('quest_guide_before_fallback');old.__file__=str(root/'guide_lookup.py')
    exec(compile(source,'guide_lookup_before_fallback.py','exec'),old.__dict__)
    catalog=quests.catalog();rows=[];failures=[];unchanged=0;comment_blocks=0
    for quest in collection_scope(catalog):
        code=quest['wiki_id'];prior=previous[code];diagnostics={}
        text,images=guide_lookup.build_preview(code,root,diagnostics=diagnostics)
        if quest['category']=='sortie':
            blocks=re.findall(r'\[임무·공략 메모\]\n((?:· [^\n]+(?:\n|$))+)',text)
            if not blocks:failures.append(code+': missing sortie comments')
            for block in blocks:
                comment_blocks+=1
                if not 2<=len(block.strip().splitlines())<=3:failures.append(code+': comment line count')
        maps=guide_lookup.sortie_maps(quest.get('requirements',{}))
        refs=diagnostics.get('fallback_maps',[])
        for area in refs:
            if area not in maps:failures.append(code+': reference outside quest maps')
            reply,pictures=guide_lookup.build_preview(area.replace('-',''),root)
            if not pictures:failures.append(code+': dead general-map reference '+area)
        core=text.split('\n\n[임무·공략 메모]',1)[0]
        if prior['status'] in {'ready','ready_images','ready_text','text_only'}:
            if (core,images)!=old.build_preview(code,root):failures.append(code+': native guide changed')
            else:unchanged+=1
        elif prior['status']=='partial':
            old_text,old_images=old.build_preview(code,root)
            if code=='B101':
                if images or not diagnostics.get('commentary_only') or diagnostics.get('missing_maps'):
                    failures.append(code+': reviewed text-only guide was not connected')
            elif old_images!=images or not text.startswith(old_text.split('\n\n※',1)[0]):
                failures.append(code+': partial guide was replaced')
        if prior['status']=='no_match':
            if maps and refs!=maps:failures.append(code+': incomplete general-map navigation')
            if not maps and '고정된 대상 해역이 없는' not in text:failures.append(code+': no-map condition missing')
            if images:failures.append(code+': fallback unexpectedly sends a generic fleet as a quest fleet')
        if refs:
            lowercase=guide_lookup.build_preview(code.lower(),root)
            if lowercase!=(text,images):failures.append(code+': case-sensitive lookup')
        rows.append({'code':code,'title':quest['name_ko'],'prior_status':prior['status'],
                     'historical_group':groups.get(code.casefold()),'quest_maps':maps,
                     'general_maps':refs,'general_queries':diagnostics.get('fallback_queries',[]),
                     'reason':diagnostics.get('fallback_reason'), 'image_count':len(images),
                     'preview':text if refs or prior['status']=='no_match' else None})
    lines=['# 임무 공략 → 일반해역 연결 검토 — 2026-10-23','',
           '원본 분류는 GUIDE_MANUAL_REVIEW_20261022.md로 보존했습니다. 아래는 현재 저장 자료를 대조한 별도 결과입니다.',
           '78개는 사이트 전체의 공략 부재 확정이 아니라 첫 검색 페이지에서 일치 후보를 찾지 못한 기록입니다.',
           '일반 공략의 편성·장비가 임무 조건을 만족한다고 보장하지 않습니다. !임무 조건을 우선합니다.',
           f'기존 정상/본문 공략 {unchanged}개는 변경 전 렌더러({revision})의 본문·사진 목록을 유지하고 메모만 추가했습니다.',
           '보류 자료를 정상 공략으로 바꾸거나 원문을 재수집하지 않았습니다.','']
    for group,label in GROUPS.items():
        items=[r for r in rows if r['historical_group']==group]
        lines.extend([f'## {group}. {label} — {len(items)}개','',
                      '| 번호 | 제목 | 참고해역 | 안내 명령 |','|---|---|---|---|'])
        for row in items:
            refs=' / '.join(row['general_maps']) or '고정 해역 없음'
            commands=' / '.join('!공략 '+q for q in row['general_queries']) or '!임무 '+row['code']
            lines.append('| '+' | '.join([row['code'],row['title'].replace('|','/'),refs,commands])+' |')
        lines.append('')
    for label,status in [('검토 보류 유지','review'),('해역 누락 2개 — 요청대로 처리 완료','partial')]:
        lines.extend(['## '+label,'','| 번호 | 기존 사유 | 일반해역 참고 |','|---|---|---|'])
        for row in rows:
            if row['prior_status']==status:
                reason=previous[row['code']]['reason'].replace('|','/').replace('\n',' ')
                if row['code']=='B101':reason='사진 없이 4-5/6-2 코멘트 공략으로 처리. 원문의 1기 수치·사진은 전송하지 않음'
                if row['code']=='B103':reason='2-3 공략 유지, 5-1은 !공략 51로 안내'
                lines.append('| '+' | '.join([row['code'],reason,' / '.join(row['general_maps'])])+' |')
        lines.append('')
    lines.extend(['## 코멘트 추가 확인 후보','',
                  '- B59: 원문에 옛 2-5 야전 루트와 장비 오류 설명이 있어 현행 사진·경로 추가 확인이 필요합니다.',
                  '- 위 후보는 기존 보류 7개와 구분합니다. 코멘트에서는 옛 경로·제공 수치를 현행으로 단정하지 않습니다.',''])
    lines.extend(['## 출력 예시',''])
    for code in ['B77','B1','B54','B101']:
        row=next(r for r in rows if r['code']==code)
        lines.extend(['### !공략 '+code,'','```text',row['preview'] or '', '```',''])
    report={'checked_at':datetime.now(timezone.utc).isoformat(),
            'historical_sha256':hashlib.sha256(original).hexdigest(),
            'historical_counts':dict(Counter(groups.values())),
            'baseline_revision':revision,'unchanged_native_guides':unchanged,
            'comment_blocks':comment_blocks,'handled_quest_codes':['B101','B103'],
            'quests':rows,'failures':failures}
    pending=[r for r in rows if r['prior_status']=='review']
    pending_lines=['# 남은 임무 공략 검토 목록','',
                   'B101은 사진 없는 코멘트 공략, B103의 5-1은 일반해역 참고로 처리했습니다. 아래 두 항목은 미처리 목록에서 제외합니다.','',
                   '## 기존 보류 7개','', '| 번호 | 제목 | 대상 해역 | 보류 사유 |','|---|---|---|---|']
    for row in pending:
        reason=('추출 해역 3-4와 임무 대상 6-3 불일치. 원문 또는 연결 파서 확인 필요'
                if row['code']=='B80' else '1기 전용 공략으로 현행 사진·편성 연결 보류')
        pending_lines.append('| '+' | '.join([row['code'],row['title'],' / '.join(row['quest_maps']),reason])+' |')
    pending_lines.extend(['','## 코멘트 읽으며 추가한 확인 후보','',
                          '- **B59**: 옛 2-5 야전 루트·옛 제공 수치와 장비 오류 설명이 있어, 사진·경로의 현행 적용 여부를 추가 확인해야 합니다.',
                          '- 코멘트에서는 옛 수치를 현재 값처럼 옮기지 않고 `!공략 25`의 현행 루트·제공을 참고하도록 했습니다.','',
                          '기존 분류 78개 및 일반해역 연결 결과: QUEST_GUIDE_FALLBACK_REVIEW.md',
                          '283개 출격 임무 코멘트 전체: QUEST_GUIDE_COMMENTS_REVIEW.md',''])
    (output/'QUEST_GUIDE_PENDING_REVIEW.md').write_text('\n'.join(pending_lines),encoding='utf-8')
    report['pending_review_codes']=[r['code'] for r in pending]
    report['additional_comment_review_codes']=['B59']
    (output/'QUEST_GUIDE_FALLBACK_REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'quest_guide_fallback_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Checked {len(rows)} quests; native unchanged {unchanged}; general navigation {sum(bool(r["general_maps"]) for r in rows)}; failures {len(failures)}')
    if failures:raise RuntimeError('\n'.join(failures))
    return report


if __name__=='__main__':audit()
