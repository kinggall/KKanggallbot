"""Read-only Domino snapshot. Private values stay in memory, never in Git/cache."""
import json
import os
from pathlib import Path
import threading
import time

from .stock_quotes import normalize, number

FILE_ID = '1xclx9sD8c1Bh4mnrleGaJDToAsZG5UU6'


def load_snapshot():
    from scripts.sync_drive_data import Drive, API
    token = os.environ.get('KAKAO_STOCK_DRIVE_TOKEN_FILE')
    default = Path(__file__).resolve().parents[1] / 'cloud' / 'token.json'
    if not token and default.is_file():
        token = str(default)
    drive = Drive(os.environ.get('GOOGLE_DRIVE_FOLDER_ID', ''), token)
    response = drive.call('GET', API + '/' + os.environ.get('KAKAO_STOCK_PORTFOLIO_FILE_ID', FILE_ID),
                          params={'alt': 'media'})
    # Drive serves this JSON as text/plain: requests.json() may guess Latin-1.
    return json.loads(response.content.decode('utf-8-sig'))


def display(value, suffix=''):
    parsed = number(value)
    if parsed is None:
        return '미확인'
    text = format(parsed, ',f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text + suffix


class PortfolioService:
    def __init__(self, loader=load_snapshot, monotonic=time.monotonic):
        self.loader, self.monotonic = loader, monotonic
        self.lock = threading.Lock()
        self.cached = None
        self.loaded_at = 0

    def snapshot(self):
        with self.lock:
            if self.cached is not None and self.monotonic() - self.loaded_at < 30:
                return self.cached
            data = self.loader()
            if (not isinstance(data, dict) or data.get('schema_version') != 1
                    or not isinstance(data.get('generated_at'), str)
                    or not data['generated_at']
                    or any(not isinstance(data.get(k), list) for k in ('holdings', 'realized'))
                    or any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
                           for k in ('holdings', 'realized') for row in data[k])):
                raise ValueError('Unsupported Domino schema')
            self.cached, self.loaded_at = data, self.monotonic()
            return data

    def reply(self, command, keyword=''):
        if command in ('평단', '수익률') and not keyword.strip():
            return f'사용법: !{command} 종목명 또는 미국 티커'
        try:
            data = self.snapshot()
            rows = data['realized' if command == '실현' else 'holdings']
            key = normalize(keyword)
            if key:
                exact = [r for r in rows if key in (normalize(r['name']), normalize(r.get('ticker', '')).split(':')[-1])]
                matches = exact or [r for r in rows if key in normalize(r['name'])]
                names = sorted({r['name'] for r in matches})
                if not matches:
                    return '해당 종목의 자산 자료가 없습니다.'
                if len(names) > 1:
                    return '정확한 종목명을 입력해 주세요.\n' + '\n'.join('· ' + n for n in names)
                rows = matches
            title = {'보유': '보유종목', '평단': '평균 매입가', '수익률': '보유 수익률', '실현': '실현 수익률'}[command]
            lines = [f'[{title}]']
            if not rows:
                lines.append('등록된 자료가 없습니다.')
            for row in rows:
                currency = row.get('currency', '')
                unit = '원' if currency == 'KRW' else ' USD' if currency == 'USD' else ' ' + currency
                account = ' [' + str(row['account']) + ']' if row.get('account') else ''
                label = row['name'] + account
                if command == '보유':
                    value = display(row.get('quantity'), '주')
                elif command == '평단':
                    value = display(row.get('average'), unit)
                    if row.get('average_at'):
                        value += ' (기준: ' + str(row['average_at']) + ')'
                elif command == '수익률':
                    value = display(row.get('return_pct'), '%')
                    value += ' / 평가손익 ' + display(row.get('unrealized_profit'), unit)
                    if row.get('quote_available') is False:
                        value += ' (시세 미수신)'
                elif not key:
                    value = '상세: !실현 ' + row['name']
                else:
                    period = row.get('period', {})
                    period = period.get('label', '') if isinstance(period, dict) else ''
                    value = display(row.get('return_pct'), '%') + ' / 실현손익 ' + display(row.get('realized_profit'), unit)
                    if period:
                        value += ' (' + str(period) + ')'
                    if row.get('display_source'):
                        value += ' · ' + str(row['display_source'])
                lines.append('· ' + label + ': ' + value)
            lines.extend(['', '자료 갱신: ' + data['generated_at']])
            if command in ('보유', '평단', '수익률'):
                stamp = data.get('holdings_collected_at')
                if stamp:
                    lines.append('보유 수집: ' + str(stamp))
            if command == '수익률' and data.get('quotes_read_at'):
                lines.append('시세 기준: ' + str(data['quotes_read_at']))
            return '\n'.join(lines)
        except Exception:
            # Never echo credentials, account identifiers, payload or provider errors.
            return 'Domino 자산 자료를 읽지 못했습니다. Drive 연결과 자료 갱신을 확인해 주세요.'
