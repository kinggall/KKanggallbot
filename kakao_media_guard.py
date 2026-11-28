"""Bounded ADB repair of KakaoTalk's specific update dialog during image sends."""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET

LOG = logging.getLogger(__name__)
PACKAGE = 'com.kakao.talk'
UPDATE_TEXT = '최신버전으로업데이트해주세요.'
RESEND_TEXT = '재전송하시겠습니까?'
RETRY_LABELS = {'재전송', '다시 보내기', '다시보내기', '재전송 버튼', '다시 보내기 버튼', 'Resend', 'Retry'}
RETRY_IDS = {'resend', 'resend_button', 'resend_message', 'btn_resend'}
MEDIA_IDS = ('photo', 'thumbnail', 'thumb', 'album', 'chat_image', 'media', 'attachment')
GROUP_ROOMS = {
    '18182686594126049': '칸코레 진수부에 어서오세요',
    '18250420501835535': '왕갤의 둥지',
    '18335522977842954': '니나브귀여워',
}
IMAGE_LOCK = threading.Lock()


def compact(text):
    return re.sub(r'\s+', '', text or '')


def bounds(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
    if not match:
        return None
    x1,y1,x2,y2 = map(int, match.groups())
    return (x1,y1,x2,y2) if x2>x1 and y2>y1 else None


def available(node):
    return node.get('package') == PACKAGE and node.get('enabled', 'true') == 'true' and bounds(node) is not None


def is_media_node(node):
    if node.get('package')!=PACKAGE:
        return False
    rid = node.get('resource-id','').split('/')[-1].lower()
    if rid=='image':
        rect = bounds(node)
        return bool(rect and node.get('class')=='android.widget.ImageView'
                    and rect[2]-rect[0]>=100 and rect[3]-rect[1]>=60)
    return any(token in rid for token in MEDIA_IDS)


class Screen:
    def __init__(self, xml):
        start = xml.find('<hierarchy')
        end = xml.rfind('</hierarchy>')
        if start<0 or end<0 or len(xml)>2*1024*1024:
            raise ValueError('Invalid UI dump')
        self.root = ET.fromstring(xml[start:end+len('</hierarchy>')])
        self.parents = {child:parent for parent in self.root.iter() for child in parent}

    def dialog_button(self, message, positive):
        messages = [n for n in self.root.iter('node') if available(n)
                    and compact(n.get('text')) == message
                    and n.get('resource-id') == 'android:id/message']
        buttons = [n for n in self.root.iter('node') if available(n)
                   and n.get('text') == positive and n.get('resource-id') == 'android:id/button1']
        if len(messages)!=1 or len(buttons)!=1:
            return None
        # A message quoted in chat must not be mistaken for a dialog.
        parent = self.parents.get(messages[0])
        for _ in range(4):
            if parent is None:
                break
            if buttons[0] in set(parent.iter()) and len(list(parent.iter()))<=30:
                return buttons[0]
            parent = self.parents.get(parent)
        return None

    def update_button(self):
        return self.dialog_button(UPDATE_TEXT, '확인')

    def resend_confirmation_button(self):
        return self.dialog_button(RESEND_TEXT, '재전송')

    def room_visible(self, room_name):
        # Scope is the user's verified 1600x900 LDPlayer tablet split view.
        if not room_name or room_name.isdecimal():
            return False
        for node in self.root.iter('node'):
            if not available(node):
                continue
            rect = bounds(node)
            if rect[0]<550 or rect[3]>240:
                continue
            label = node.get('text', '')
            if compact(label)==compact(room_name) or re.fullmatch(re.escape(compact(room_name))+r'\d+명?',compact(label)):
                return True
        return False

    def retries(self):
        found = []
        for node in self.root.iter('node'):
            if not available(node) or node.get('clickable')!='true':
                continue
            rid = node.get('resource-id', '').split('/')[-1]
            labels = {node.get('text',''), node.get('content-desc','')}
            if rid not in RETRY_IDS and not labels.intersection(RETRY_LABELS):
                continue
            # Require a photo attachment in the same small message subtree.
            parent = self.parents.get(node)
            for _ in range(4):
                if parent is None:
                    break
                children = list(parent.iter('node'))
                if len(children)>60:
                    break
                if any(c is not node and is_media_node(c) for c in children):
                    found.append(node)
                    break
                parent = self.parents.get(parent)
        return found


def identity(node):
    return node.get('resource-id'), node.get('content-desc'), node.get('bounds')


class Adb:
    def __init__(self, executable, port, serial):
        self.prefix = [str(executable), '-P', str(port), '-s', serial]
        self.path = '/sdcard/kkanggallbot-media-'+uuid.uuid4().hex+'.xml'

    @classmethod
    def discover(cls):
        if os.environ.get('KAKAO_MEDIA_UI_AUTO', '1')=='0':
            return None
        path = Path(os.environ.get('IRIS_ADB_PATH', r'C:\LDPlayer\LDPlayer9\adb.exe'))
        if not path.is_file():
            return None
        port = int(os.environ.get('IRIS_ADB_PORT', '5038'))
        result = subprocess.run([str(path),'-P',str(port),'devices'],capture_output=True,check=True,timeout=8)
        serials = [line.split()[0] for line in result.stdout.decode('utf-8',errors='replace').splitlines()
                   if len(line.split())==2 and line.split()[1]=='device']
        serial = os.environ.get('IRIS_ADB_SERIAL','')
        if not serial:
            if not serials:
                raise ValueError('연결된 ADB 기기가 없습니다. adb.exe -P 5038 devices로 연결을 확인해 주세요.')
            if len(serials)==1:
                serial = serials[0]
            else:
                forwards = subprocess.run([str(path),'-P',str(port),'forward','--list'],
                                          capture_output=True,check=True,timeout=8)
                targets = {parts[0] for line in forwards.stdout.decode('utf-8',errors='replace').splitlines()
                           if len(parts := line.split())==3 and parts[0] in serials
                           and parts[1:]==['tcp:3000','tcp:3000']}
                if len(targets)!=1:
                    raise ValueError('Iris 3000번 포트 연결 기기를 정하지 못했습니다. IRIS_ADB_SERIAL을 지정해 주세요.')
                serial = targets.pop()
        if serial not in serials:
            raise ValueError('Selected LDPlayer is not connected')
        adb = cls(path,port,serial)
        size = adb.run('shell','wm','size').decode('utf-8',errors='replace')
        effective = re.findall(r'(?:Physical|Override) size:\s*(\d+x\d+)',size)
        if not effective or effective[-1]!='1600x900':
            raise ValueError('Expected the verified 1600x900 LDPlayer; refusing another device')
        return adb

    def run(self, *args):
        result = subprocess.run(self.prefix+list(args),capture_output=True,check=True,timeout=8)
        return result.stdout

    def screen(self):
        self.run('shell','uiautomator','dump','--compressed',self.path)
        return Screen(self.run('exec-out','cat',self.path).decode('utf-8'))

    def tap(self,node):
        x1,y1,x2,y2 = bounds(node)
        if not (0<=x1<x2<=1600 and 0<=y1<y2<=900):
            raise ValueError('Button is outside the verified display')
        self.run('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))

    def cleanup(self):
        try:
            self.run('shell','rm','-f',self.path)
        except (OSError,subprocess.SubprocessError):
            pass


@dataclass
class Repair:
    room_name: str
    baseline_safe: bool
    dismissed: bool = False
    retried: bool = False
    confirmed: bool = False

    def step(self, screen, tap):
        if self.confirmed:
            return
        if self.retried:
            button = screen.resend_confirmation_button()
            if button is not None:
                tap(button)
                self.confirmed = True
                LOG.warning('[사진 자동 처리] 재전송 확인창의 재전송 클릭')
            return
        button = screen.update_button()
        if button is not None:
            if not self.dismissed:
                tap(button)
                self.dismissed = True
                LOG.warning('[사진 자동 처리] 업데이트 안내 확인 클릭')
            return
        if not self.dismissed or not self.baseline_safe or not screen.room_visible(self.room_name):
            return
        candidates = screen.retries()
        if len(candidates)!=1:
            return
        tap(candidates[0])
        self.retried = True
        LOG.warning('[사진 자동 처리] 사진 재전송 1회 클릭')


class Guard:
    def __init__(self,adb,room_name):
        self.adb,self.room_name = adb,room_name
        self.done = threading.Event()
        self.cancel = threading.Event()
        self.error = None
        baseline = adb.screen()
        self.repair = Repair(room_name, baseline.room_visible(room_name) and not baseline.retries())
        self.thread = threading.Thread(target=self.run,name='kakao-photo-dialog',daemon=True)

    def run(self):
        deadline = time.monotonic()+85
        tail = None
        try:
            while not self.cancel.is_set() and time.monotonic()<deadline:
                if self.done.is_set():
                    tail = tail or time.monotonic()+6
                    if time.monotonic()>=tail:
                        break
                before = (self.repair.dismissed,self.repair.retried,self.repair.confirmed)
                self.repair.step(self.adb.screen(),self.adb.tap)
                after = (self.repair.dismissed,self.repair.retried,self.repair.confirmed)
                if before!=after and self.done.is_set():
                    tail = time.monotonic()+6
                if self.repair.confirmed:
                    break
                self.cancel.wait(.3)
        except (ValueError,ET.ParseError,OSError,subprocess.SubprocessError) as error:
            self.error = type(error).__name__
            LOG.warning('[사진 자동 처리] 화면 확인 실패: %s',self.error)

    def finish(self):
        self.done.set()
        self.thread.join(timeout=30)
        self.cancel.set()
        self.thread.join(timeout=10)
        if not self.thread.is_alive():
            self.adb.cleanup()
        if self.repair.dismissed and not self.repair.confirmed:
            LOG.warning('[사진 자동 처리] 확인은 눌렀으나 재전송 확인 단계까지 완료하지 못함. verify_kakao_media_ui.py로 점검')


def post_image(post, url, *, room_name='', **kwargs):
    """Post exactly once to Iris; only retry via the visible Kakao UI, never the API."""
    guard = None
    adb = None
    with IMAGE_LOCK:
        room = str(kwargs.get('json', {}).get('room', ''))
        if room not in GROUP_ROOMS:
            return post(url, **kwargs)
        if not room_name or str(room_name).isdecimal():
            room_name = GROUP_ROOMS[room]
        try:
            adb = Adb.discover()
            if adb is not None:
                guard = Guard(adb,str(room_name))
                guard.thread.start()
        except (ValueError,ET.ParseError,OSError,subprocess.SubprocessError) as error:
            LOG.warning('[사진 자동 처리] ADB 준비 실패: %s',type(error).__name__)
            if adb is not None:
                adb.cleanup()
            guard = None
        try:
            return post(url,**kwargs)
        finally:
            if guard is not None:
                guard.finish()
