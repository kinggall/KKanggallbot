"""Hidden stock-command routing. Runs inside the existing Iris bot process."""
from concurrent.futures import ThreadPoolExecutor
import re
import threading

import requests
import stock_quotes

SERVICE = stock_quotes.StockService()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='stock-reply')
PENDING = threading.BoundedSemaphore(8)


def handle(message, chat_id, reply_url):
    """Return (JSON body, HTTP status) for !주가 only; do not register any help entry."""
    match = re.fullmatch(r'!주가(?:\s+(.*))?', message)
    if not match:
        return None
    if chat_id is None or str(chat_id) == '':
        return {'ok': False, 'error': 'chat_id missing'}, 400
    if not PENDING.acquire(blocking=False):
        try:
            requests.post(reply_url, json={'type': 'text', 'room': str(chat_id),
                          'data': '주가 요청이 많습니다. 잠시 후 다시 시도해 주세요.'}, timeout=3).raise_for_status()
        except requests.RequestException:
            pass
        return {'ok': True, 'stock_queue_busy': True}, 200

    def send():
        try:
            text = SERVICE.reply(match.group(1) or '')
            requests.post(reply_url, json={'type': 'text', 'room': str(chat_id), 'data': text}, timeout=10).raise_for_status()
            print('[주가 답변] 전송 완료')
        except Exception as error:
            print('[주가 답변 실패] ' + type(error).__name__)
        finally:
            PENDING.release()

    try:
        EXECUTOR.submit(send)
    except Exception:
        PENDING.release()
        return {'ok': False, 'error': 'stock_worker_unavailable'}, 503
    return {'ok': True}, 200
