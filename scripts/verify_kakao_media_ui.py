"""Read only: list control IDs needed to inspect Kakao's photo update dialog."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kakao_media_guard import Adb,PACKAGE,RETRY_LABELS,compact,UPDATE_TEXT,RESEND_TEXT,bounds


def main():
    adb = Adb.discover()
    if adb is None:
        raise SystemExit('LDPlayer ADB not found. Set IRIS_ADB_PATH if installed elsewhere.')
    try:
        screen = adb.screen()
        print('Update dialog identified:',screen.update_button() is not None)
        print('Resend confirmation identified:',screen.resend_confirmation_button() is not None)
        print('Photo retry buttons identified:',len(screen.retries()))
        print('Controls (message contents omitted):')
        for node in screen.root.iter('node'):
            if node.get('package')!=PACKAGE:
                continue
            if node.get('clickable')!='true' and not node.get('class','').endswith(('ImageView','ImageButton')) and compact(node.get('text')) not in (UPDATE_TEXT,RESEND_TEXT):
                continue
            label = node.get('text','')
            desc = node.get('content-desc','')
            safe_label = label if label=='확인' or label in RETRY_LABELS or compact(label) in (UPDATE_TEXT,RESEND_TEXT) else ''
            safe_desc = desc if desc in RETRY_LABELS else ''
            print(node.get('resource-id','-'),node.get('class','-'),bounds(node),
                  'text='+safe_label,'description='+safe_desc)
    finally:
        adb.cleanup()


if __name__=='__main__':
    main()
