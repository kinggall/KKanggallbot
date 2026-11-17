"""PC public ranking check: no Kakao messages, account or portfolio reads.

python -m stockbot.verify_market_caps
"""
from .market_caps import MARKETS
from .stock_commands import CAPS


def main():
    failed = 0
    for market in MARKETS:
        snapshot = CAPS.load(market)
        if snapshot is None:
            print(market[1] + ': FAILED (KIS public ranking unavailable)')
            failed += 1
        else:
            print(f'{market[1]}: OK · {len(snapshot.rows)}개 · {snapshot.retrieved_at.isoformat()}')
    print(CAPS.reply())
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
