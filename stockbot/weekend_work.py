"""Read the Domino overview's total investment profit, not position P/L."""
from html.parser import HTMLParser
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import os
from pathlib import Path
import re

from .stock_quotes import number

OVERVIEW_FILE_ID = '1bx29Lu-OXGs9cdQMmVrlsox9y4q9_eFU'


class OverviewText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def overview_profit(html):
    parser = OverviewText()
    parser.feed(html)
    text = ' '.join(parser.parts).replace('\u2212', '-')
    matches = re.findall(r'총\s*투자\s*수익\s*([+-]?\s*\d[\d,]*(?:\.\d+)?)\s*원', text)
    values = {number(re.sub(r'\s+', '', value)) for value in matches}
    if len(values) != 1 or None in values:
        raise ValueError('Overview total investment profit missing or ambiguous')
    return values.pop()


def load_profit():
    from scripts.sync_drive_data import Drive, API
    token = os.environ.get('KAKAO_STOCK_DRIVE_TOKEN_FILE')
    default = Path(__file__).resolve().parents[1] / 'cloud' / 'token.json'
    if not token and default.is_file():
        token = str(default)
    drive = Drive(os.environ.get('GOOGLE_DRIVE_FOLDER_ID', ''), token)
    response = drive.call('GET', API + '/' + os.environ.get('KAKAO_STOCK_OVERVIEW_FILE_ID', OVERVIEW_FILE_ID),
                          params={'alt': 'media'})
    return overview_profit(response.content.decode('utf-8-sig'))


def render(profit):
    profit = number(profit)
    if profit is None:
        raise ValueError('Invalid investment profit')
    if profit > 0:
        return '✔️ 주말출근: 왜 함?'
    count = int((-profit / Decimal(150000)).to_integral_value(rounding=ROUND_CEILING))
    years = format((Decimal(count) / 20).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP), 'f')
    if '.' in years:
        years = years.rstrip('0').rstrip('.')
    return f'✔️ 주말출근: {years}년'


def reply(loader=load_profit):
    try:
        return render(loader())
    except Exception:
        return '총투자수익을 읽지 못했습니다. Domino overview·Drive 연결을 확인해 주세요.'
