"""Offline ship-level experience differences, based on EO's MIT-licensed table."""
import json
from functools import lru_cache
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent

@lru_cache(maxsize=1)
def levels():
    data=json.loads((ROOT/'data/ship_experience.json').read_text(encoding='utf-8'))
    rows=data['levels']
    if data.get('schema')!=1 or [r[0] for r in rows]!=list(range(1,len(rows)+1)):
        raise ValueError('Invalid ship experience table')
    if rows[0][1]!=0 or rows[-1][2]!=0:
        raise ValueError('Invalid experience table bounds')
    for current,following in zip(rows,rows[1:]):
        if current[2]<0 or following[1]-current[1]!=current[2]:
            raise ValueError('Inconsistent ship experience increments')
    return {level:total for level,total,_ in rows}

def usage(maximum):
    return f'사용법: !경험치 [현재레벨] [목표레벨]\n예: !경험치 1 99\n입력 범위: Lv1~{maximum}'

def reply(query):
    table=levels();maximum=max(table);help_text=usage(maximum)
    parts=query.split()
    if len(parts)!=2 or any(not re.fullmatch(r'[0-9]{1,3}',part) for part in parts):
        return help_text
    current,target=map(int,parts)
    if current not in table or target not in table:return help_text
    if target<current:return '목표 레벨은 현재 레벨 이상으로 입력해주세요.\n'+help_text
    text=f'Lv{current} → Lv{target}\n· 필요 경험치: {table[target]-table[current]:,}\n※ 현재 레벨에 막 도달한 시점 기준입니다.'
    if current<100<=target:text+='\n※ Lv100 이상은 결혼(가)이 필요합니다.'
    return text
