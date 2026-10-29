"""Hidden stock-command routing. Runs inside the existing Iris bot process."""
from concurrent.futures import ThreadPoolExecutor
import re
import threading

import requests
from . import stock_quotes
from .portfolio import PortfolioService

SERVICE = stock_quotes.StockService()
PORTFOLIO = PortfolioService(quote_loader=SERVICE.details, symbol_names=SERVICE.names_for_ticker,
                             ticker_lookup=SERVICE.ticker_for_name)
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='stock-reply')
PENDING = threading.BoundedSemaphore(8)
INVESTMENT_HELP = (
    "[주갤봇 사용법]" + "\u200b" * 4000 + "\n\n"
    "💡 명령어 앞에 느낌표(!)를 붙여주세요.\n"
    "💡 국내·미국 종목명, 티커, 등록된 별명으로 검색할 수 있어요.\n"
    "💡 보유 · 평가 및 실현 · 손익 종목은 정달봄의 실제 거래 기록입니다.\n\n"
    "━━━━ 주가 · 시세 ━━━━\n"
    "!주가 [종목명/티커]\n"
    "예: !주가 넵튠 / !주가 삼전 / !주가 NVDA\n\n"
    "━━━━ 보유 · 평가 ━━━━\n"
    "!보유 — 보유 종목 목록\n"
    "!보유 [종목명/티커] — 평균 매입가·수익률·현재가\n\n"
    "━━━━ 실현 · 손익 ━━━━\n"
    "!실현 — 실현 종목 목록\n"
    "!실현 [종목명/티커] — 실현 수익률\n\n"
    "━━━━━━━━━━━━━━\n"
    "💡 자산 정보는 Domino의 최근 갱신 자료를 기준으로 표시합니다."
)


def handle(message, chat_id, reply_url):
    """Route investment commands without registering them in the main help list."""
    match = re.fullmatch(r'!주가(?:\s+(.*))?', message)
    investment_help = message.strip() == '!주갤'
    private = re.fullmatch(r'!(보유|실현)(?:\s+(.*))?', message)
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
