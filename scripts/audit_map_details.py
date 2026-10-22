"""Offline audit and complete Korean preview report for all 37 map guides."""
import json
from pathlib import Path
import re
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import map_guides
from map_guide_details import air_entries,detail_lines,reference_rows,route_nodes


def audit(root=ROOT):
    root=Path(root);cache=root/'guide_cache/zekamashi_maps'
    reviewed=json.loads((root/'data/map_guide_reviewed.json').read_text(encoding='utf-8'))['maps']
    reference=reference_rows(root/'guide_cache/map_reference/integrated_first_sheet.csv')
    failures=[];conflicts=[];maps=[];markdown=['# 일반해역 상세 공략 — 전체 출력 검토본',
        '제공: 제카마시 우선, 통합공략 첫 시트로 호환되는 누락값만 보완. 균형 100 미만은 생략합니다.',
        '제공 문턱값은 적 강편성·기항대 및 도중 격추 전 기준입니다. 편성의 실제 목표 제공과 구별합니다.',
        '6-4의 25%/75% 적 편성 차이는 사용자 확인을 반영했습니다.']
    query_count=0
    for area in map_guides.AREAS:
        record=json.loads((cache/area/'manifest.json').read_text(encoding='utf-8'))
        overview,pictures=map_guides.preview(area,root)
        if any(line.startswith('· ') for line in overview.splitlines()):failures.append(area+': verbose overview')
        if not pictures:failures.append(area+': missing overview pictures')
        if map_guides.preview(area,root)!=map_guides.preview(area.replace('-',''),root):failures.append(area+': compact lookup mismatch')
        query_count+=2
        markdown.extend(['',f'## {area} 전체 조회','```text','!공략 '+area,overview,'```'])
        variants=0;detail_queries=[]
        for route in record['routes']:
            query=area+' 루트'+str(route['number']) if len(record['routes'])>1 else area+' 상세'
            text,images=map_guides.preview(query,root);query_count+=1;detail_queries.append(query)
            if not images or any(not p.is_file() for p in images):failures.append(query+': missing detail pictures')
            if re.search('[\u3040-\u30ff\u4e00-\u9fff]',text):failures.append(query+': Japanese in output')
            if '재검토 중' in text:failures.append(query+': stale reviewed source')
            markdown.extend(['',f'### !공략 {query}','```text',text,'```',f'연결 이미지: {len(images)}장'])
            for variant in route['variants']:
                variants+=1;lines=detail_lines(area,variant,root)
                if len(lines)>5:failures.append(query+': more than 5 detail lines')
                if len(reviewed[area].get('variant_notes',{}).get(variant['source_heading'],reviewed[area].get('notes',[])))<2:
                    failures.append(query+': missing reviewed Korean notes')
                nodes=route_nodes(variant['summary']) or set(reviewed[area].get('random_nodes',[]))
                entries=air_entries(area,variant,reviewed[area],reference)
                for entry in entries:
                    if entry['node'] not in nodes:failures.append(query+': off-route air value')
                    if entry.get('superiority',0)>entry.get('supremacy',float('inf')):
                        failures.append(query+': supremacy below superiority')
                    if entry.get('conflicts'):
                        item={'area':area,'node':entry['node'],'fields':entry['conflicts'],
                              'primary':{k:entry[k] for k in ('superiority','supremacy','parity') if k in entry},
                              'reason':'6-4: 적 편성 확률 차이(사용자 확인)' if area=='6-4' else '제카마시 값 우선; 충돌하는 시트 값은 병합하지 않음'}
                        if item not in conflicts:conflicts.append(item)
        maps.append({'area':area,'routes':len(record['routes']),'variants':variants,'detail_queries':detail_queries})
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'maps':maps,
            'query_count':query_count,'conflicts':conflicts,'failures':failures}
    (cache/'DETAIL_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (cache/'DETAIL_REVIEW.md').write_text('\n\n'.join(markdown)+'\n',encoding='utf-8')
    print(f'Audited {len(maps)} maps, {sum(m["variants"] for m in maps)} fleets, {query_count} queries; failures: {len(failures)}')
    print('Reference differences:',json.dumps(conflicts,ensure_ascii=False))
    if failures:raise SystemExit('\n'.join(failures))
    return report


if __name__=='__main__':audit()
