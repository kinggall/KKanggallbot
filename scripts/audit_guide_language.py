"""Offline scan of rendered sortie guide strings; does not inspect image pixels."""
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import guide_lookup
import quests
from scripts.verify_guides import collection_scope

def audit():
    rows=[];checked=0
    for quest in collection_scope(quests.catalog()):
        if quest['category']!='sortie':continue
        code=quest['wiki_id'];checked+=1
        text,images=guide_lookup.build_preview(code)
        lines=text.splitlines()[1:]
        problems=[line for line in lines if re.search(r'[\u3040-\u30fa\u30fc-\u30ff\u4e00-\u9fff]|Fletcher|Johnston',line)]
        incomplete=[line for line in lines if '이미지 참조' in line or '요약 미확인' in line]
        if problems or incomplete:rows.append({'code':code,'japanese_lines':problems,'image_only_lines':incomplete})
    output=ROOT/'guide_cache/guide_audit/GUIDE_LANGUAGE_REVIEW.md'
    lines=['# 공략 문자열 추가 검토','',f'출격 임무 {checked}개 개요 검사. 사진 속 문자·전체 편성의 시각적 검증은 포함하지 않습니다.',
           '제목의 일본어 장식문구는 검사 대상에서 제외합니다. 이미지 참조는 번역 오류와 구분합니다.','']
    for row in rows:
        lines.extend(['## '+row['code'],'',*('- 일본어 잔존: '+x for x in row['japanese_lines']),*('- 사진 대조 필요: '+x for x in row['image_only_lines']),''])
    output.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'checked':checked,'japanese':[{ 'code':r['code'],'lines':r['japanese_lines']} for r in rows if r['japanese_lines']], 'image_only_codes':[r['code'] for r in rows if r['image_only_lines']]},ensure_ascii=False))
if __name__=='__main__':audit()
