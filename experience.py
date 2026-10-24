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
    return f'사용법: !경험치 [현재레벨] [목표레벨] [판당경험치(선택)]\n예: !경험치 1 99 / !경험치 80 99 1500\n입력 범위: Lv1~{maximum}'

def reply(query):
    table=levels();maximum=max(table);help_text=usage(maximum)
    parts=query.split()
    if len(parts) not in (2,3) or any(not re.fullmatch(r'[0-9]{1,3}',part) for part in parts[:2]):
        return help_text
    per_run=None
    if len(parts)==3:
        if not re.fullmatch(r'[0-9]{1,18}',parts[2]) or int(parts[2])<=0:
            return '판당 경험치는 1 이상의 정수로 입력해주세요.\n'+help_text
        per_run=int(parts[2])
    current,target=map(int,parts[:2])
    if current not in table or target not in table:return help_text
    if target<current:return '목표 레벨은 현재 레벨 이상으로 입력해주세요.\n'+help_text
    needed=table[target]-table[current]
    text=f'Lv{current} → Lv{target}\n· 필요 경험치: {needed:,}'
    if per_run is not None:
        runs=(needed+per_run-1)//per_run
        text+=f'\n· 판당 경험치: {per_run:,}\n· 필요 횟수: {runs:,}회'
    text+='\n※ 현재 레벨에 막 도달한 시점 기준입니다.'
    if per_run is not None:text+='\n※ 판당 경험치는 해당 함선의 실제 획득량 기준입니다.'
    if current<100<=target:text+='\n※ Lv100 이상은 결혼(가)이 필요합니다.'
    return text
