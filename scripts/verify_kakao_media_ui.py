"""Read only: list control IDs needed to inspect Kakao's photo update dialog."""
import argparse
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kakao_media_guard import Adb,PACKAGE,RETRY_LABELS,compact,UPDATE_TEXT,RESEND_TEXT,bounds,GROUP_ROOMS


def inspect_screen(screen):
    texts={compact(n.get('text')) for n in screen.root.iter('node') if n.get('package')==PACKAGE}
    current=('업데이트 안내' if UPDATE_TEXT in texts else
             '재전송 확인창' if RESEND_TEXT in texts else '두 팝업 문구가 없는 화면')
    report=['화면 상태: '+current,
            'Update dialog identified: '+str(screen.update_button() is not None),
            'Resend confirmation identified: '+str(screen.resend_confirmation_button() is not None),
            'Photo retry buttons identified: '+str(len(screen.retries())),
            '등록된 방 제목 확인: '+(' / '.join(n for n in GROUP_ROOMS.values() if screen.room_visible(n)) or '확인되지 않음'),
            'Controls (message contents omitted):']
    for node in screen.root.iter('node'):
        if node.get('package')!=PACKAGE:
            continue
        label=node.get('text','')
        desc=node.get('content-desc','')
        if (node.get('clickable')!='true'
                and not node.get('class','').endswith(('ImageView','ImageButton'))
                and compact(label) not in (UPDATE_TEXT,RESEND_TEXT)):
            continue
        safe_label=label if label=='확인' or label in RETRY_LABELS or compact(label) in (UPDATE_TEXT,RESEND_TEXT) else ''
        safe_desc=desc if desc in RETRY_LABELS else ''
        report.append(f"{node.get('resource-id','-')} {node.get('class','-')} {bounds(node)} text={safe_label} description={safe_desc}")
    return '\n'.join(report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',type=int,default=0,help='Observe UI transitions for up to 60 seconds; never click')
    args=parser.parse_args()
    if not 0<=args.watch<=60:
        parser.error('--watch must be between 0 and 60')
    adb=Adb.discover()
    if adb is None:
        raise SystemExit('LDPlayer ADB not found. Set IRIS_ADB_PATH if installed elsewhere.')
    print('읽기 전용 진단입니다. 자동 클릭·사진 전송은 하지 않습니다.',flush=True)
    if args.watch:
        print(f'{args.watch}초 동안 관찰합니다. 각 팝업·실패 사진 화면을 3초 이상 유지해 주세요.',flush=True)
    try:
        until=time.monotonic()+args.watch
        previous=None
        while True:
            report=inspect_screen(adb.screen())
            if report!=previous:
                print(report,flush=True)
                previous=report
            if not args.watch or time.monotonic()>=until:
                break
            time.sleep(.5)
    finally:
        adb.cleanup()


if __name__=='__main__':
    main()
