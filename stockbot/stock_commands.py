"""Hidden stock-command routing. Runs inside the existing Iris bot process."""
from concurrent.futures import ThreadPoolExecutor
import re
import threading

import requests
from . import stock_quotes
from .portfolio import PortfolioService

SERVICE = stock_quotes.StockService()
PORTFOLIO = PortfolioService()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='stock-reply')
PENDING = threading.BoundedSemaphore(8)
INVESTMENT_HELP = (
    "[주갤봇 사용법]" + "\u200b" * 4000 + "\n\n"
    "💡 명령어 앞에 느낌표(!)를 붙여주세요.\n"
    "💡 국내 종목명·코드 / 미국 티커로 시세를 조회할 수 있어요.\n\n"
    "━━━━ 주가 · 시세 ━━━━\n"
    "!주가 [종목명/코드/미국 티커]\n"
    "예: !주가 두산에너빌리티 / !주가 DRAM\n\n"
    "━━━━ 보유 · 평가 ━━━━\n"
    "!보유 — 보유종목 목록\n"
    "!평단 [종목명/티커] — 평균 매입가\n"
    "!수익률 [종목명/티커] — 보유 수익률\n\n"
    "━━━━ 실현 · 손익 ━━━━\n"
    "!실현 — 실현 종목 목록\n"
    "!실현 [종목명] — 실현 수익률\n\n"
    "━━━━━━━━━━━━━━\n"
    "💡 자산 정보는 Domino의 최근 갱신 자료를 기준으로 표시합니다."
)


def handle(message, chat_id, reply_url):
    """Route investment commands without registering them in the main help list."""
    match = re.fullmatch(r'!주가(?:\s+(.*))?', message)
    investment_help = message.strip() in ('!투자', '!주갤')
    private = re.fullmatch(r'!(보유|평단|수익률|실현)(?:\s+(.*))?', message)
    if not match and not investment_help and not private:
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
            text = (INVESTMENT_HELP if investment_help else
                    PORTFOLIO.reply(private.group(1), private.group(2) or '') if private else
                    SERVICE.reply(match.group(1) or ''))
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
