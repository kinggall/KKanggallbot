"""Exact initial aliases for public Kancolle help commands only."""
import re

ALIASES = {
    '!ㄱㅈ': '!공지', '!ㅌㅎㄱㄹ': '!통합공략', '!ㅂㅂㅋ': '!반복퀘',
    '!ㅁㅌ': '!멘테', '!ㅇㅂㅌ': '!이벤트', '!ㅅㄱㅇㅁ': '!신규임무',
    '!ㅇㅁ': '!임무', '!ㄱㄹ': '!공략', '!ㄷㄹ': '!드랍', '!ㅎㅈㄷㄹ': '!한정드랍',
    '!ㅋㅁㅅ': '!칸무스', '!ㅅㄹ': '!슬롯', '!ㅊㄱㅈㅂ': '!초기장비', '!ㄱㅎㅊ': '!경험치',
    '!ㅋㅈ': '!퀴즈', '!ㅈㄷ': '!정답', '!ㅋㅈㅈㅅ': '!퀴즈점수',
    '!ㅈㅂ': '!장비', '!ㄱㅂ': '!개발', '!ㄹㅅㅍ': '!레시피', '!ㄱㅅ': '!개수',
    '!ㅍㅌ': '!피트', '!ㅇㅈ': '!원정', '!ㅈㄱ': '!전과',
}


def expand(message):
    match = re.fullmatch(r'(\S+)(?:\s+(.*))?', message, re.S)
    if not match or match[1] not in ALIASES:
        return message
    return ALIASES[match[1]] + (' ' + match[2] if match[2] is not None else '')
