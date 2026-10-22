"""Slow, resumable general-area guide collection. No per-command network calls."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import requests
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import map_guides
from scripts.collect_zekamashi import BASE,Fetcher,image_source_url,image_identity,write_json


def reparse(areas,output):
    """Rebuild manifests from saved HTML without making network requests.

    Keep unused image files intact. If parsing finds an uncollected image,
    keep the old data and mark it pending for a normal resumed collection.
    """
    pending=[]
    for area in areas:
        folder=output/area;manifest=folder/'manifest.json';article=folder/'article.html'
        if not manifest.exists() or not article.exists():continue
        old=json.loads(manifest.read_text(encoding='utf-8'))
        if old.get('status')!='downloaded':continue
        record=map_guides.extract(article.read_text(encoding='utf-8'),area,old['url'])
        images={image_identity(e['url']):e for e in old.get('images',[])}
        used={};missing=[]
        for route in record['routes']:
            for variant in route['variants']:
                for key in ['images','airbase_images']:
                    local=[]
                    for url in variant[key]:
                        entry=images.get(image_identity(url))
                        if not entry or not (folder/entry['file']).is_file():
                            missing.append(url);continue
                        local.append(entry['file']);used[entry['file']]=entry
                    variant[key]=local
        if missing:
            pending.append(area)
            old.update(status='needs_collection',reason='New parser found additional images')
            write_json(manifest,old)
            print(f'{area}: needs {len(set(missing))} additional images; marked pending',flush=True)
            continue
        record.update(status='downloaded',collected_at=old.get('collected_at'),images=list(used.values()))
        write_json(manifest,record)
        print(f'{area}: reparsed saved HTML; {len(record["routes"])} routes',flush=True)
    return pending


def collect(areas,output,interval=10):
    if interval<10:raise ValueError('Use at least 10 seconds between requests')
    f=Fetcher(interval);robots=f.get(BASE+'robots.txt')
    f.robots=RobotFileParser();f.robots.parse(robots.text.splitlines())
    f.interval=max(interval,f.robots.crawl_delay(f.session.headers['User-Agent']) or 0)
    for area in areas:
        folder=output/area;folder.mkdir(parents=True,exist_ok=True)
        manifest=folder/'manifest.json'
        old=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
        if old.get('status')=='downloaded' and all((folder/n).is_file() for r in old['routes'] for v in r['variants'] for n in [*v['images'],*v.get('airbase_images',[])]):
            print(area+': already collected',flush=True);continue
        article=folder/'article.html';url=BASE+'kancolle-kouryaku/'+area+'/'
        if article.exists():html=article.read_text(encoding='utf-8')
        else:
            try:response=f.get(url)
            except RuntimeError as error:
                write_json(manifest,{'schema':1,'area':area,'url':url,
                                    'status':'http_error','reason':str(error)})
                raise
            except requests.HTTPError as error:
                if error.response is not None and error.response.status_code==404:
                    write_json(manifest,{'schema':1,'area':area,'url':url,'status':'not_found'})
                    print(area+': no article at the expected URL',flush=True)
                    continue
                raise
            if urlparse(response.url).hostname!='zekamashi.net':raise ValueError('Unexpected article destination')
            html=response.text;article.write_text(html,encoding='utf-8')
        try:record=map_guides.extract(html,area,url)
        except ValueError as error:
            write_json(manifest,{'schema':1,'area':area,'url':url,'status':'review_required','reason':str(error)})
            print(area+': '+str(error),flush=True);continue
        record.update(status='in_progress',collected_at=datetime.now(timezone.utc).isoformat(),images=[])
        write_json(manifest,record)
        for route in record['routes']:
            for variant in route['variants']:
                for key in ['images','airbase_images']:
                    local=[]
                    for source in variant[key]:
                        source=image_source_url(source)
                        suffix=Path(urlparse(source).path).suffix or '.jpg'
                        name=hashlib.sha256(source.encode()).hexdigest()[:20]+suffix
                        image=folder/name
                        if not image.exists():
                            response=f.get(source)
                            if not response.headers.get('Content-Type','').startswith('image/'):
                                raise ValueError('Expected image content')
                            temporary=image.with_suffix('.part');temporary.write_bytes(response.content);temporary.replace(image)
                        local.append(name)
                        entry={'file':name,'url':source,'bytes':image.stat().st_size}
                        if entry not in record['images']:record['images'].append(entry)
                    variant[key]=local
        record['status']='downloaded';write_json(manifest,record)
        print(f'{area}: {len(record["routes"])} routes, {len(record["images"])} images',flush=True)


def audit(output):
    report=[]
    for area in map_guides.AREAS:
        path=output/area/'manifest.json'
        if not path.exists():report.append({'area':area,'status':'not_collected'});continue
        record=json.loads(path.read_text(encoding='utf-8'))
        row={'area':area,'status':record.get('status'),'route_count':len(record.get('routes',[]))}
        if row['status']=='downloaded':
            row['warnings']=[]
            for route in record['routes']:
                for variant in route['variants']:
                    if not variant.get('summary'):
                        row['warnings'].append('Fleet summary unconfirmed: '+variant['source_heading'])
                    if not variant.get('images'):
                        row['warnings'].append('No fleet image: '+variant['source_heading'])
            overview,images=map_guides.preview(area,cache_root=output)
            if not images and '편성' not in overview and '【' not in overview:row['status']='review_required'
            tree=map_guides.gauge_routes(record) if area in map_guides.MULTI_GAUGES else {}
            queries=[area+' 루트'+str(r['number']) for r in record['routes']] if len(record['routes'])>1 else [area+' 상세']
            if tree:
                queries=[area.replace('-','')+str(gauge)+' 루트'+str(r['number'])
                         for gauge,routes in tree.items() for r in routes]
            for query in queries:
                text,pictures=map_guides.preview(query,cache_root=output)
                if '해당 루트가 없습니다' in text or '완료되지 않았습니다' in text or not pictures:
                    row['status']='review_required'
            row['overview_images']=len(images)
        report.append(row)
    write_json(output/'AUDIT.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'maps':report})
    print('Offline map audit: '+str(output/'AUDIT.json'),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--maps',nargs='+',default=list(map_guides.AREAS))
    p.add_argument('--output',type=Path,default=ROOT/'guide_cache/zekamashi_maps')
    p.add_argument('--interval',type=float,default=10)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--audit-only',action='store_true')
    p.add_argument('--reparse-only',action='store_true',help='Rebuild saved manifests offline; keep image files')
    args=p.parse_args();areas=[map_guides.parse_area(s) for s in args.maps]
    if not all(areas):p.error('Unknown map')
    areas=list(dict.fromkeys(areas))
    if args.dry_run:
        print('\n'.join(BASE+'kancolle-kouryaku/'+s+'/' for s in areas));return
    if args.audit_only:audit(args.output);return
    if args.reparse_only:
        pending=reparse(areas,args.output)
        audit(args.output)
        if pending:raise ValueError('Additional images require collection: '+', '.join(pending))
        return
    collect(areas,args.output,args.interval)
    audit(args.output)


if __name__=='__main__':
    try:main()
    except (requests.RequestException,RuntimeError,ValueError,OSError) as error:
        raise SystemExit(str(error))
