"""Offline full-cache audit and shareable HTML/manifest export. Never fetches."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import guide_lookup
import quests

LABELS = {'ready':'연결 정상', 'text_only':'본문 공략 연결',
          'ready_images':'사진 공략 연결(편성 설명은 이미지 참조)', 'ready_text':'사진 없는 편성·경로 공략',
          'no_match':'검색 첫 페이지 일치 없음', 'missing':'수집 기록 없음',
          'incomplete':'수집 미완료/파일 누락', 'review':'연결 검토 필요',
          'partial':'일부 해역 연결 누락', 'metadata_only':'구조 확인·사진 검증 제외'}


def collection_scope(catalog):
    return sorted([row for row in catalog.items.values()
                   if not row.get('unavailable') and (row['category']=='sortie' or row.get('source_row'))
                   and row['frequency'] in {'onetime','daily','weekly','monthly','quarterly','annual'}],
                  key=lambda row: quests.natural_code(row['wiki_id']))


def check(row, cache, metadata_only=False):
    code = row['wiki_id']
    folder = cache / re.sub(r'[^A-Za-z0-9_-]', '_', code)
    result = {'code':code,'title':row['name_ko'],'status':'missing','reason':'manifest.json 없음',
              'maps':[], 'image_count':0, 'detail_checks':0}
    def outcome(status, reason):
        result.update(status=status, reason=reason)
        return result
    try:
        if not (folder/'manifest.json').is_file():
            return result
        record = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if not guide_lookup.record_matches(record, row):
            return outcome('review','임무 번호 또는 일본어 제목 불일치')
        status = record.get('status')
        if status == 'no_match_on_first_page':
            return outcome('no_match','첫 검색 페이지에 제목 일치 후보 없음. 공략 부재 확정 아님')
        if status == 'review_required':
            return outcome('review',record.get('review_reason','복수 후보 또는 본문 구조 검토 필요'))
        if status != 'downloaded' or record.get('schema_version') != 2:
            return outcome('incomplete',f'수집 상태: {status}, schema: {record.get("schema_version")}')
        if not (folder/'article.html').is_file():
            return outcome('incomplete','article.html 없음')
        html = (folder/'article.html').read_text(encoding='utf-8')
        if not guide_lookup.article_matches(html, record, row):
            return outcome('review','본문 H1 제목 또는 원문 URL 불일치')
        # An overview and every displayed map's detailed lookup go through
        # the same renderer used by the bot, never a separate approximation.
        diagnostics = {}
        text, images = guide_lookup.build_preview(code, cache_root=cache,
            verify_images=not metadata_only, diagnostics=diagnostics)
        result['maps'] = diagnostics.get('observed_maps', [])
        result['image_count'] = len(images)
        if record.get('text_only'):
            if row['category']=='sortie' and guide_lookup.sortie_maps(row['requirements']):
                return outcome('review','출격 임무가 본문 전용으로 수집됨')
            return outcome('text_only','제목·출처 확인, 편성 사진 없는 본문 공략')
        if diagnostics.get('unexpected_maps'):
            return outcome('review','임무 조건에 없는 해역: '+'/'.join(diagnostics['unexpected_maps']))
        if not images and not diagnostics.get('rendered_maps'):
            return outcome('incomplete' if '수집이 아직 완료' in text else 'review', text.split('\n\n')[-1])
        if not metadata_only:
            for image in record.get('images', []):
                path = (folder/image['file']).resolve()
                if path.parent != folder.resolve() or not path.is_file() or path.stat().st_size == 0:
                    return outcome('incomplete','사진 파일 누락/빈 파일/잘못된 경로')
                if image.get('bytes') is not None and image['bytes'] != path.stat().st_size:
                    return outcome('incomplete','사진 크기가 수집 기록과 다름: '+path.name)
        lowercase, lower_images = guide_lookup.build_preview(code.lower(), cache_root=cache,
            verify_images=not metadata_only)
        if (lowercase, lower_images) != (text, images):
            return outcome('review','대소문자 조회 결과 불일치')
        for area in result['maps']:
            detail_diagnostics = {}
            detail, detail_images = guide_lookup.build_preview(code+' '+area.replace('-',''),
                cache_root=cache, verify_images=not metadata_only, diagnostics=detail_diagnostics)
            if area not in detail_diagnostics.get('rendered_maps', []) or area not in detail:
                return outcome('review','해역 상세 조회 실패: '+area)
            result['detail_checks'] += 1
        if diagnostics.get('missing_maps'):
            return outcome('partial','임무 조건 중 연결 누락: '+'/'.join(diagnostics['missing_maps']))
        ready_status = 'ready_images' if diagnostics.get('image_only_maps') else 'ready' if images else 'ready_text'
        return outcome('metadata_only' if metadata_only else ready_status,
                       '번호·제목·해역·전체/상세 조회 확인' + (' (사진 실재 검증 제외)' if metadata_only else '·사진 파일 확인'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return outcome('incomplete',type(error).__name__+': '+str(error))


def markdown(report):
    lines = ['# 공략 연결 전수 점검', '', '검증 시각(UTC): '+report['checked_at'], '',
             '인터넷 요청 없이 로컬 자료만 검사했습니다. 사진·본문 내용의 게임상 정확성이나 번역 완전성을 보증하는 검사는 아닙니다.', '',
             '사진 검증: '+('제외 (HTML/메타데이터 검토용)' if report['metadata_only'] else 'PC 파일 존재·크기 검사 포함'), '',
             f'대상 {len(report["quests"])}개 / 해역 상세 조회 {sum(r["detail_checks"] for r in report["quests"])}건', '']
    counts = Counter(r['status'] for r in report['quests'])
    lines.extend(f'- {label}: {counts[status]}개' for status,label in LABELS.items())
    lines.extend(['', '## 공략 미연결 번호 및 사유', '',
                  '첫 페이지 검색 실패는 사이트 전체에 공략이 없다는 뜻이 아닙니다.', ''])
    missing = [r for r in report['quests'] if r['status'] not in {'ready','ready_images','ready_text','text_only','metadata_only'}]
    for row in missing:
        lines.append(f'- **{row["code"]}** {row["title"]} — {LABELS[row["status"]]}: {row["reason"]}'.replace('\n',' '))
    if not missing:
        lines.append('해당 없음')
    lines.extend(['', '## 전체 검사 기록', '', '| 임무 | 상태 | 연결 해역 | 사진 | 사유 |',
                  '| --- | --- | --- | ---: | --- |'])
    for row in report['quests']:
        values = [row['code'],LABELS[row['status']],'/'.join(row['maps']),str(row['image_count']),row['reason']]
        lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in values)+' |')
    return '\n'.join(lines)+'\n'


def export_metadata(cache, destination):
    """Keep folder identity; omit images, HARs, cookies and request headers."""
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(cache.glob('*/*')):
            if (path.name in {'manifest.json','article.html'} and path.is_file()
                    and path.resolve().is_relative_to(cache.resolve())):
                archive.write(path, path.relative_to(cache).as_posix())


def run_audit(cache, output, metadata_only=False, export=False):
    catalog = quests.catalog()
    rows = []
    targets = collection_scope(catalog)
    for index, row in enumerate(targets,1):
        result = check(row,cache,metadata_only)
        rows.append(result)
        print(f'[{index}/{len(targets)}] {result["code"]}: {LABELS[result["status"]]}',flush=True)
    report = {'checked_at':datetime.now(timezone.utc).isoformat(),
              'metadata_only':metadata_only,'quests':rows}
    output.mkdir(parents=True,exist_ok=True)
    (output/'GUIDE_AUDIT.md').write_text(markdown(report),encoding='utf-8')
    (output/'guide_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if export:
        export_metadata(cache,output/'guide_metadata.zip')
    print('Report: '+str(output/'GUIDE_AUDIT.md'),flush=True)
    print(json.dumps(dict(Counter(row['status'] for row in rows)),ensure_ascii=False),flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=ROOT/'guide_cache/zekamashi')
    parser.add_argument('--output',type=Path,default=ROOT/'guide_cache/guide_audit')
    parser.add_argument('--metadata-only',action='store_true',help='Skip image existence checks; never labels records ready')
    parser.add_argument('--export',action='store_true',help='Also package manifest.json/article.html for review')
    args = parser.parse_args()
    if not args.cache.is_dir():
        parser.error('수집 폴더가 없습니다: '+str(args.cache))
    run_audit(args.cache,args.output,args.metadata_only,args.export)


if __name__=='__main__':
    main()
