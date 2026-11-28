import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import kakao_media_guard as media

ROOM = '니나브귀여워'
ROOM_ID = '18335522977842954'


def node(text='', rid='', desc='', box='[10,10][100,40]', cls='android.widget.TextView',click=False,pkg=media.PACKAGE,children=''):
    e=ET.Element('node',{'text':text,'resource-id':rid,'content-desc':desc,'bounds':box,'class':cls,
                         'clickable':str(click).lower(),'package':pkg,'enabled':'true'})
    if children:
        e.extend(ET.fromstring('<group>'+children+'</group>'))
    return ET.tostring(e,encoding='unicode')


def screen(content='', room=ROOM):
    title=node(room,'com.kakao.talk:id/title',box='[800,70][1100,125]')
    return media.Screen('<hierarchy>'+node(rid='com.kakao.talk:id/root',box='[0,0][1600,900]',children=title+content)+'</hierarchy>')


def dialog(text,positive='확인',message_id='android:id/message',pkg=media.PACKAGE):
    children=node(text,message_id,box='[520,420][1040,480]',pkg=pkg)
    children+=node('삭제','android:id/button2',box='[870,510][940,560]',click=True,pkg=pkg)
    children+=node(positive,'android:id/button1',box='[990,510][1060,560]',click=True,pkg=pkg)
    return node(rid='android:id/parentPanel',box='[510,410][1080,580]',children=children,pkg=pkg)


def failed_photo(y=780,media_id='com.kakao.talk:id/photo_thumbnail'):
    children=node(rid=media_id,box=f'[1180,{y-100}][1580,{y+25}]',cls='android.widget.ImageView')
    children+=node(rid='com.kakao.talk:id/resend',desc='다시 보내기',box=f'[1110,{y}][1150,{y+35}]',cls='android.widget.ImageButton',click=True)
    children+=node(rid='com.kakao.talk:id/delete',desc='삭제',box=f'[1150,{y}][1180,{y+35}]',cls='android.widget.ImageButton',click=True)
    return node(rid='com.kakao.talk:id/message_row',box=f'[1100,{y-100}][1590,{y+40}]',children=children)


class MediaGuardTests(unittest.TestCase):
    def test_exact_update_then_retry_then_confirmation_only_once(self):
        repair=media.Repair(ROOM,True)
        tap=Mock()
        update=screen(dialog('최신버전으로 업데이트해 주세요.'))
        retry=screen(failed_photo())
        confirmation=screen(dialog('재전송하시겠습니까?','재전송'))
        repair.step(update,tap)
        repair.step(update,tap)
        self.assertEqual(tap.call_count,1)
        self.assertEqual(tap.call_args.args[0].get('text'),'확인')
        repair.step(retry,tap)
        self.assertEqual(tap.call_count,2)
        self.assertTrue(repair.retried)
        self.assertFalse(repair.confirmed)
        repair.step(confirmation,tap)
        self.assertEqual(tap.call_count,3)
        self.assertEqual(tap.call_args.args[0].get('text'),'재전송')
        repair.step(confirmation,tap)
        repair.step(retry,tap)
        self.assertEqual(tap.call_count,3)
        self.assertTrue(repair.confirmed)
        self.assertNotIn('삭제',[c.args[0].get('text') for c in tap.call_args_list])

    def test_observed_custom_dialog_message_and_idless_positive_button(self):
        def custom(text,positive):
            content=node(text,media.PACKAGE+':id/txt_message',box='[551,399][1049,455]')
            content+=node('삭제',box='[870,464][940,536]',cls='android.widget.Button',click=True)
            content+=node(positive,box='[980,464][1073,536]',cls='android.widget.Button',click=True)
            return screen(node(rid='dialog',box='[510,380][1090,580]',children=content))
        update=custom('최신버전으로 업데이트해 주세요.','확인')
        self.assertEqual(update.update_button().get('bounds'),'[980,464][1073,536]')
        confirm=custom('재전송하시겠습니까?','재전송')
        self.assertEqual(confirm.resend_confirmation_button().get('text'),'재전송')
        self.assertIsNone(custom('다른 작업을 진행할까요?','확인').update_button())
        r=media.Repair(ROOM,True)
        tap=Mock()
        for current in (update,screen(failed_photo()),confirm):r.step(current,tap)
        self.assertEqual([c.args[0].get('text') for c in tap.call_args_list],['확인','','재전송'])
        self.assertTrue(r.confirmed)

    def test_normal_photo_without_update_dialog_never_taps(self):
        tap=Mock();r=media.Repair(ROOM,True)
        r.step(screen(failed_photo()),tap)
        r.step(screen(dialog('재전송하시겠습니까?','재전송')),tap)
        tap.assert_not_called()

    def test_other_dialog_or_other_app_or_chat_quote_is_not_update(self):
        for text,rid,pkg in [('로그아웃하시겠습니까?','android:id/message',media.PACKAGE),
                             ('최신버전으로 업데이트해 주세요.','com.kakao.talk:id/message',media.PACKAGE),
                             ('최신버전으로 업데이트해 주세요.','android:id/message','other.app')]:
            with self.subTest(text=text,rid=rid,pkg=pkg):
                self.assertIsNone(screen(dialog(text,message_id=rid,pkg=pkg)).update_button())

    def test_wrong_room_old_failures_or_multiple_retry_buttons_are_not_retried(self):
        for baseline_safe,current in [(False,screen(failed_photo())),
                                      (True,screen(failed_photo(),room='다른 방')),
                                      (True,screen(failed_photo(500)+failed_photo(780)))]:
            tap=Mock();r=media.Repair(ROOM,baseline_safe,dismissed=True)
            r.step(current,tap)
            tap.assert_not_called()
        # The room's name in the left-hand chat list does not identify the open room.
        left=node(ROOM,'com.kakao.talk:id/name',box='[100,100][400,150]')
        self.assertFalse(screen(left,room='다른 방').room_visible(ROOM))

    def test_text_retry_and_cancel_are_not_photo_retry(self):
        self.assertEqual(screen(failed_photo(media_id='com.kakao.talk:id/message_text')).retries(),[])
        buttons=screen(failed_photo()).retries()
        self.assertEqual(len(buttons),1)
        self.assertEqual(buttons[0].get('resource-id'),'com.kakao.talk:id/resend')

    def test_actual_kakao_image_id_is_supported_without_matching_small_icons(self):
        self.assertEqual(len(screen(failed_photo(media_id='com.kakao.talk:id/image')).retries()),1)
        icon=ET.fromstring(node(rid='com.kakao.talk:id/image',cls='android.widget.ImageView',box='[10,10][30,30]'))
        self.assertFalse(media.is_media_node(icon))

    def test_diagnostic_reports_state_without_leaking_chat_text(self):
        from scripts.verify_kakao_media_ui import inspect_screen
        private=node('비공개 대화 내용','com.kakao.talk:id/private',desc='private-photo-url',click=True)
        report=inspect_screen(screen(private))
        self.assertIn('두 팝업 문구가 없는 화면',report)
        self.assertNotIn('비공개 대화 내용',report)
        self.assertNotIn('private-photo-url',report)
        report=inspect_screen(screen(dialog('최신버전으로 업데이트해 주세요.')))
        self.assertIn('화면 상태: 업데이트 안내',report)
        self.assertIn('Update dialog identified: True',report)

    def test_unrecognized_retry_confirmation_is_not_clicked(self):
        tap=Mock();r=media.Repair(ROOM,True,dismissed=True,retried=True)
        for current in (screen(dialog('삭제하시겠습니까?','삭제')),
                        screen(dialog('최신버전으로 업데이트해 주세요.'))):
            r.step(current,tap)
        tap.assert_not_called()

    def test_missing_adb_keeps_single_existing_http_post(self):
        post=Mock(return_value=Mock())
        with patch.object(media.Adb,'discover',return_value=None):
            result=media.post_image(post,'http://local/reply',room_name=ROOM,json={'type':'image','room':ROOM_ID},timeout=20)
        self.assertIs(result,post.return_value)
        post.assert_called_once_with('http://local/reply',json={'type':'image','room':ROOM_ID},timeout=20)

    def test_private_or_unregistered_room_does_not_start_ui_checks(self):
        post=Mock()
        with patch.object(media.Adb,'discover') as discover:
            media.post_image(post,'http://local/reply',json={'type':'image','room':'private-room'})
        discover.assert_not_called()
        post.assert_called_once()

    def test_guard_starts_before_post_and_finishes_even_on_http_failure(self):
        events=[];guard=Mock()
        guard.thread.start.side_effect=lambda:events.append('start')
        guard.finish.side_effect=lambda:events.append('finish')
        def post(*args,**kwargs):
            events.append('post');raise ValueError('test failure')
        with patch.object(media.Adb,'discover',return_value=Mock()),patch.object(media,'Guard',return_value=guard):
            with self.assertRaises(ValueError):
                media.post_image(post,'http://local/reply',room_name=ROOM,json={'type':'image','room':ROOM_ID})
        self.assertEqual(events,['start','post','finish'])

    def test_ui_progress_extends_window_through_resend_confirmation(self):
        clock=[0]
        pages=iter([screen(dialog('최신버전으로 업데이트해 주세요.')),
                    screen(failed_photo()),screen(failed_photo()),
                    screen(dialog('재전송하시겠습니까?','재전송'))])
        def read():
            clock[0]+=4
            return next(pages)
        guard=media.Guard.__new__(media.Guard)
        guard.adb=Mock()
        guard.adb.screen.side_effect=read
        guard.done=Mock();guard.done.is_set.return_value=True
        guard.cancel=Mock();guard.cancel.is_set.return_value=False
        guard.repair=media.Repair(ROOM,True)
        guard.error=None
        with patch.object(media.time,'monotonic',side_effect=lambda:clock[0]):
            guard.run()
        self.assertTrue(guard.repair.confirmed)
        self.assertEqual(guard.adb.tap.call_count,3)
        self.assertGreaterEqual(clock[0],16)

    def test_multiple_devices_selects_iris_forward_not_first_device(self):
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/'adb.exe';executable.touch()
            devices=Mock(stdout=b'List of devices attached\nemulator-5554\tdevice\n172.30.1.84:5555\tdevice\n')
            forwards=Mock(stdout=b'172.30.1.84:5555 tcp:3000 tcp:3000\n')
            size=Mock(stdout=b'Physical size: 1600x900\n')
            with patch.dict(media.os.environ,{'IRIS_ADB_PATH':str(executable),'IRIS_ADB_SERIAL':'',
                                              'IRIS_ADB_PORT':'5038','KAKAO_MEDIA_UI_AUTO':'1'}), \
                    patch.object(media.subprocess,'run',side_effect=[devices,forwards,size]) as run:
                adb=media.Adb.discover()
            self.assertEqual(adb.prefix[-1],'172.30.1.84:5555')
            self.assertIn('172.30.1.84:5555',run.call_args.args[0])
            self.assertNotIn('emulator-5554',run.call_args.args[0])

    def test_no_or_ambiguous_device_never_runs_ui_input(self):
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/'adb.exe';executable.touch()
            for outputs in ([Mock(stdout=b'List of devices attached\n')],
                            [Mock(stdout=b'one\tdevice\ntwo\tdevice\n'),Mock(stdout=b'')]):
                with self.subTest(outputs=len(outputs)),patch.dict(media.os.environ,
                        {'IRIS_ADB_PATH':str(executable),'IRIS_ADB_SERIAL':'','KAKAO_MEDIA_UI_AUTO':'1'}), \
                        patch.object(media.subprocess,'run',side_effect=outputs) as run:
                    with self.assertRaises(ValueError):media.Adb.discover()
                    self.assertTrue(all('input' not in call.args[0] for call in run.call_args_list))

    def test_preparation_failure_does_not_resubmit_or_block_the_api(self):
        post=Mock();adb=Mock()
        with patch.object(media.Adb,'discover',return_value=adb),patch.object(media,'Guard',side_effect=ValueError('bad dump')):
            media.post_image(post,'http://local/reply',json={'type':'image','room':ROOM_ID})
        post.assert_called_once()
        adb.cleanup.assert_called_once()
