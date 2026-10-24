"""Offline quest rewards and boss-only regular-map ranking points."""
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
USAGE='사용법: !전과 [5/20/100/500/임무/해역]'

def rewards(value,optional=False):
    """Keep choice rewards distinct from guaranteed points."""
    found=[]
    if isinstance(value,dict):
        if value.get('category')=='senka':found.append((int(value['amount']),optional))
        for key,child in value.items():
            if isinstance(child,(dict,list)):found.extend(rewards(child,optional or key=='choices'))
    elif isinstance(value,list):
        for child in value:found.extend(rewards(child,optional))
    return found

def quest_reply():
    import quests
    groups=defaultdict(list)
    for row in quests.catalog().items.values():
        if row.get('unavailable'):continue
        points=rewards(row.get('rewards',{}))
        if points:groups[row['frequency']].append((row,points))
    lines=['전과 임무']
    for frequency in ['daily','weekly','monthly','quarterly','annual','onetime','special1','special2','unknown']:
        items=groups.get(frequency,[])
        if not items:continue
        lines.extend(['','['+quests.FREQUENCY.get(frequency,frequency)+']'])
        guaranteed=0
        for row,points in sorted(items,key=lambda p:quests.natural_code(p[0]['wiki_id'])):
            amounts=' / '.join(f'{amount:,}'+(' (선택)' if optional else '') for amount,optional in points)
            lines.append(f'· {row["name_ko"]} ({row["wiki_id"]}) - {amounts}')
            guaranteed+=sum(amount for amount,optional in points if not optional)
        if len(items)>1 and guaranteed:lines.append(f'확정 전과 합계: {guaranteed:,}')
    lines.extend(['','※ (선택)은 다른 보상 대신 전과를 선택할 때만 획득합니다.','상세: !임무 [번호] / 공략: !공략 [번호]'])
    return '\n'.join(lines)

def points(experience):
    return format(Decimal(experience)*Decimal(7)/Decimal(10000),'.4f').rstrip('0').rstrip('.') or '0'

def map_reply(root=ROOT):
    data=json.loads((Path(root)/'data/senka_boss.json').read_text(encoding='utf-8'))
    if data.get('schema')!=1:raise ValueError('Unknown boss points schema')
    lines=['해역별 보스 전과 (S/A)']
    for row in data['maps']:
        area=row['area'];experience=row['admiral_exp_s']
        if row['status']=='no_boss':
            lines.append(f'· {area} - 보스 전투 없음')
        elif experience is None:lines.append(f'· {area} - 미확인')
        else:
            a_exp=experience*4//5
            lines.append(f'· {area} - S {points(experience)} / A {points(a_exp)}')
    lines.extend(['','※ 보스 전투 1회 기준. 도중·EO 클리어 보너스·임무 전과는 제외합니다.'])
    return '\n'.join(lines)
