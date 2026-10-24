#!/usr/bin/env python3
"""Reproducible public-source world data builder. Python standard library only.

Generated place assets are intentionally excluded from source control. A public,
versioned release archive is the durable build input; a cache is only an optimization.
"""
from __future__ import annotations
import argparse, bisect, datetime as dt, gzip, hashlib, io, json, os, re, shutil, sqlite3, struct, subprocess, sys, tarfile, tempfile, time, unicodedata, urllib.parse, urllib.request, zipfile
from collections import Counter
from pathlib import Path

SCHEMA = 1
SHARD_LIMIT = 524288
MAX_ASSET_FILES = 19000
MAX_PLACE_ROWS = 7000000
MAX_LINE_BYTES = 131072
MAX_OUTPUT_BYTES = 3 * 1024**3
PLACE_CODES = {'PPL','PPLA','PPLA2','PPLA3','PPLA4','PPLA5','PPLC','PPLCD','PPLF','PPLG','PPLL','PPLR','PPLS','PPLX','STLMT'}
EXCLUDED_CODES = ['PPLCH','PPLH','PPLQ','PPLW']
ZONE_FILES = ['africa','antarctica','asia','australasia','europe','northamerica','southamerica','etcetera','backward']
ATTRIBUTION = 'GeoNames, licensed under CC BY 4.0. Filtered fields and populated-place classes; search keys normalized and data partitioned by Contifield.'
SCOPE = 'All accepted current populated-place records in the pinned GeoNames extract, without a population threshold. This includes source-listed villages and populated localities, but does not guarantee every real settlement, correct boundaries, current habitation, complete alternate names, or official timetables. Historical, abandoned and destroyed place classes are excluded. Source primary and ASCII names are searchable.'

def compact(value): return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=False)
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=(compact(value)+'\n').encode();path.write_bytes(raw)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def read_lock(path):
    value=json.loads(Path(path).read_text())
    if value.get('schemaVersion')!=1 or not re.fullmatch(r'[a-z0-9-]{8,80}',value.get('datasetId','')):raise ValueError('Invalid source lock')
    return value

def download_source(source, cache, mirror=None):
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    path=cache/source['fileName']
    if path.exists() and path.stat().st_size==source['bytes'] and digest(path)==source['sha256']:return path
    urls=([mirror] if mirror else [])+[source['url']]
    errors=[]
    for url in urls:
        started=time.monotonic();size=0;sha=hashlib.sha256();part=path.with_suffix(path.suffix+'.partial')
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Contifield-World-Data/1.0'})
            with urllib.request.urlopen(request,timeout=30) as response:
                host=urllib.parse.urlparse(response.url).hostname or ''
                if response.status!=200 or not (host in {'download.geonames.org','data.iana.org','github.com'} or host.endswith('.githubusercontent.com')):raise ValueError('Unexpected source host/status')
                length=response.headers.get('Content-Length')
                if length and int(length)!=source['bytes']:raise ValueError('Source size differs from pinned edition')
                with part.open('wb') as f:
                    while True:
                        b=response.read(1024*1024)
                        if not b:break
                        size+=len(b)
                        if size>source['bytes'] or time.monotonic()-started>600:raise ValueError('Source exceeded size/time bound')
                        sha.update(b);f.write(b)
            if size!=source['bytes'] or sha.hexdigest()!=source['sha256']:raise ValueError('Source checksum differs from pinned edition')
            part.replace(path);return path
        except Exception as error:
            part.unlink(missing_ok=True);errors.append(f'{url}: {error}')
            # An upstream denial is not a cue to circumvent access controls.
            if isinstance(error,urllib.error.HTTPError) and error.code==403:break
    raise RuntimeError('Pinned input unavailable. Keep the deployed edition; do not substitute latest data. '+ '; '.join(errors))

def source_files(lock, cache, download=False, mirror_base=None):
    files={}
    for key in ['tzdata','tzcode','countryInfo','admin1','geonames']:
        row=lock[key];path=Path(cache)/row['fileName']
        if download:path=download_source(row,cache,f"{mirror_base}/{row['fileName']}" if mirror_base else None)
        if not path.exists() or path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:raise ValueError(f'Unverified or missing {key} input: {path}')
        files[key]=path
    return files

def extract_sources(archives, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for archive in archives:
        with tarfile.open(archive,'r:gz') as tar:
            for member in tar.getmembers():
                # IANA source distributions have ordinary top-level files only.
                if not member.isfile() or '/' in member.name or member.name.startswith('.') or member.size>2*1024*1024:raise ValueError('Unsafe IANA archive member')
                body=tar.extractfile(member).read()
                if len(body)!=member.size:raise ValueError('Incomplete IANA member')
                (output/member.name).write_bytes(body)

def tzif_transitions(path, start, end):
    raw=Path(path).read_bytes()
    def header(pos):
        if raw[pos:pos+4]!=b'TZif':raise ValueError('Invalid TZif')
        return raw[pos+4:pos+5],struct.unpack_from('>6I',raw,pos+20)
    def blocksize(c,n):
        utc,std,leaps,times,types,chars=c
        return times*n+times+types*6+chars+leaps*(n+4)+std+utc
    version,c=header(0);pos=44;n=4
    if version in [b'2',b'3',b'4']:
        pos+=blocksize(c,4);_,c=header(pos);pos+=44;n=8
    utc,std,leaps,count,types,chars=c
    if count>10000 or types>256 or leaps:raise ValueError('Unexpected timezone table bounds/leap mode')
    times=list(struct.unpack_from('>'+('q' if n==8 else 'i')*count,raw,pos)) if count else [];pos+=n*count
    indexes=raw[pos:pos+count];pos+=count
    offsets=[struct.unpack_from('>iBB',raw,pos+6*i)[0] for i in range(types)]
    if any(abs(offset)>86400 for offset in offsets):raise ValueError('Invalid timezone offset')
    prior=bisect.bisect_right(times,start)-1
    active=offsets[indexes[prior]] if prior>=0 else offsets[0]
    output=[[start,active]]
    for instant,index in zip(times,indexes):
        if start<instant<end and offsets[index]!=output[-1][1]:output.append([instant,offsets[index]])
    return output

def build_timezones(lock, files, output_dir):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='contifield-tz-') as temp:
        source=Path(temp)/'source';compiled=Path(temp)/'zoneinfo'
        extract_sources([files['tzcode'],files['tzdata']],source)
        if (source/'version').read_text().strip()!=lock['timezoneVersion']:raise ValueError('IANA version mismatch')
        subprocess.run(['make','-s','zic'],cwd=source,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
        start=int(dt.datetime.fromisoformat(lock['timezoneGuardStart'].replace('Z','+00:00')).timestamp())
        end=int(dt.datetime.fromisoformat(lock['timezoneGuardEndExclusive'].replace('Z','+00:00')).timestamp())
        subprocess.run([str(source/'zic'),'-b','fat','-r',f'@{start}/@{end}','-d',str(compiled),*[str(source/name) for name in ZONE_FILES]],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        zone_names=set();links={}
        for name in ZONE_FILES:
            for line in (source/name).read_text().splitlines():
                fields=line.split('#',1)[0].split()
                if fields and fields[0]=='Zone':zone_names.add(fields[1])
                elif fields and fields[0]=='Link':links[fields[2]]=fields[1]
        def canonical(name):
            seen=set()
            while name in links:
                if name in seen:raise ValueError('Timezone alias cycle')
                seen.add(name);name=links[name]
            if name not in zone_names:raise ValueError('Unknown timezone link target')
            return name
        zones={name:tzif_transitions(compiled/name,start,end) for name in sorted(zone_names)}
        aliases={name:canonical(name) for name in sorted(links)}
        data={'schemaVersion':1,'version':lock['timezoneVersion'],'sourceURL':lock['tzdata']['url'],'sourceSha256':lock['tzdata']['sha256'],'compilerSourceURL':lock['tzcode']['url'],'compilerSourceSha256':lock['tzcode']['sha256'],'license':'Public domain (IANA tz data)','supportedLocalYears':lock['supportedLocalYears'],'startUtcSeconds':start,'endUtcSecondsExclusive':end,'zones':zones,'aliases':aliases}
        write_json(output_dir/'world-timezones.generated.json',data)
        iso_codes={line.split('\t')[0] for line in (source/'iso3166.tab').read_text().splitlines() if line and not line.startswith('#')}
        countries=[]
        for line in files['countryInfo'].read_text().splitlines():
            if not line or line.startswith('#'):continue
            fields=line.split('\t')
            if len(fields)<17:raise ValueError('Country record shape changed')
            code=fields[0]
            if code in {'AN','CS'}:continue
            if code not in iso_codes and code!='XK':raise ValueError('Unknown current country classification')
            countries.append({'code':code,'name':fields[4],'kind':'supplemental' if code=='XK' else 'iso3166','continent':fields[8],'geonamesId':int(fields[16])})
        if len(countries)!=250 or {r['code'] for r in countries}!=iso_codes|{'XK'}:raise ValueError('Country universe is not verified 249 ISO codes plus supplemental XK')
        countries.sort(key=lambda r:r['code']);write_json(output_dir/'world-countries.generated.json',countries)
        return data,countries

def search_key(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.category(c).startswith('M')).lower().split())

def parse_place_line(line, countries, timezone_ids):
    if len(line)>MAX_LINE_BYTES:raise ValueError('Source line exceeded bound')
    fields=line.decode('utf-8',errors='strict').rstrip('\r\n').split('\t')
    if len(fields)!=19:raise ValueError('GeoNames record does not have 19 columns')
    if fields[6]!='P':return None,'not-populated-place'
    if fields[7] not in PLACE_CODES:return None,'excluded-feature:'+fields[7]
    if fields[8] not in countries:return None,'unmapped-country:'+fields[8]
    try:
        ident=int(fields[0]);lat=float(fields[4]);lon=float(fields[5])
        if not 0<ident<2**53 or not -90<=lat<=90 or not -180<=lon<=180:raise ValueError()
        if not fields[1] or len(fields[1])>200 or len(fields[2])>200:raise ValueError()
        if any(ord(c)<32 or ord(c)==127 for c in fields[1]+fields[2]):raise ValueError()
        # Some provider administrative identifiers are Unicode names (for example
        # North Korean county names), not ISO/FIPS ASCII codes. Preserve them.
        if any(len(fields[i])>80 or any(ord(c)<32 or ord(c)==127 for c in fields[i]) for i in [10,11]):raise ValueError()
        if fields[18]:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',fields[18]):raise ValueError()
            dt.date.fromisoformat(fields[18])
    except (ValueError,OverflowError):return None,'invalid-place-fields'
    place={'id':ident,'name':fields[1],'asciiName':fields[2] or fields[1],'country':fields[8],'admin1':fields[10],'admin2':fields[11],'latitude':lat,'longitude':lon,'timeZone':fields[17] if fields[17] in timezone_ids else None,'featureCode':fields[7],'modifiedDate':fields[18]}
    return place,None

def build_places(lock, files, timezone_data, countries, output_dir, shard_limit=SHARD_LIMIT):
    started=time.monotonic();output_dir=Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):raise ValueError('Place output must be empty; do not mix data editions')
    output_dir.mkdir(parents=True,exist_ok=True)
    dataset=lock['datasetId'];country_map={r['code']:r for r in countries};zone_ids=set(timezone_data['zones'])|set(timezone_data['aliases'])
    region_names={}
    for line in files['admin1'].read_text().splitlines():
        fields=line.split('\t')
        if len(fields)>=2:region_names[fields[0]]=fields[1]
    counts=Counter();ignored=Counter();missing_zones=0;source_rows=0;accepted=0;insert=[]
    with tempfile.TemporaryDirectory(prefix='contifield-place-db-') as temp:
        db=sqlite3.connect(str(Path(temp)/'places.sqlite'))
        db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF');db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-65536')
        db.execute('CREATE TABLE places (id INTEGER PRIMARY KEY,country TEXT NOT NULL,region TEXT NOT NULL,key1 TEXT NOT NULL,key2 TEXT NOT NULL,payload TEXT NOT NULL)')
        with zipfile.ZipFile(files['geonames']) as archive:
            members=archive.infolist()
            if len(members)!=1 or members[0].filename!=lock['geonames']['member'] or members[0].file_size>4*1024**3:raise ValueError('Unexpected or oversized GeoNames ZIP layout')
            with archive.open(members[0]) as stream:
                while True:
                    line=stream.readline(MAX_LINE_BYTES+1)
                    if not line:break
                    source_rows+=1;place,reason=parse_place_line(line,country_map,zone_ids)
                    if not place:ignored[reason]+=1;continue
                    counts[(place['country'],place['admin1'])]+=1
                    accepted+=1
                    if accepted>MAX_PLACE_ROWS:raise ValueError('Place record bound exceeded')
                    if place['timeZone'] is None:missing_zones+=1
                    key1=search_key(place['name']);key2=search_key(place['asciiName'])
                    if not key1:raise ValueError('Empty normalized place name')
                    insert.append((place['id'],place['country'],place['admin1'],key1,key2,compact(place)))
                    if len(insert)>=5000:
                        db.executemany('INSERT INTO places VALUES (?,?,?,?,?,?)',insert);db.commit();insert=[]
                    if source_rows%1000000==0:print(compact({'phase':'read','sourceRows':source_rows,'accepted':accepted,'seconds':round(time.monotonic()-started,1)}),flush=True)
        if insert:db.executemany('INSERT INTO places VALUES (?,?,?,?,?,?)',insert);db.commit()
        # Disk-backed indexes keep the full catalog out of memory and permit a bounded merge scan.
        db.execute('CREATE INDEX name1 ON places(country,region,key1,id)');db.execute('CREATE INDEX name2 ON places(country,region,key2,id)');db.commit()
        manifest_countries=[];asset_count=0;total_bytes=0;search_entries=0
        for code,country in sorted(country_map.items()):
            regions=[]
            for (cc,region),count in sorted(counts.items()):
                if cc!=code:continue
                region_id=hashlib.sha256((code+'\t'+region).encode()).hexdigest()[:12]
                prefix=compact({'schemaVersion':1,'datasetId':dataset,'country':code,'region':region})[:-1]+',"entries":['
                prefix_bytes=prefix.encode();parts=[];size=len(prefix_bytes)+3;first=None;last=None;shards=[];index=0
                def flush():
                    nonlocal parts,size,first,last,index,asset_count,total_bytes,search_entries
                    if not parts:return
                    raw=prefix_bytes+b','.join(parts)+b']}\n'
                    if len(raw)>shard_limit:raise ValueError('Generated shard exceeds bound')
                    relative=f'{dataset}/countries/{code.lower()}/{region_id}/{index:04d}.json';path=output_dir/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                    shards.append({'path':'/assets/world-places/'+relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'count':len(parts),'firstKey':first,'lastKey':last})
                    asset_count+=1;total_bytes+=len(raw);search_entries+=len(parts)
                    if asset_count>MAX_ASSET_FILES or total_bytes>MAX_OUTPUT_BYTES:raise ValueError('Generated asset budget exceeded')
                    parts=[];size=len(prefix_bytes)+3;first=None;last=None;index+=1
                cursor=db.execute('SELECT key1 AS key,id,payload FROM places WHERE country=? AND region=? UNION ALL SELECT key2 AS key,id,payload FROM places WHERE country=? AND region=? AND key2<>key1 ORDER BY key,id',(code,region,code,region))
                for key,ident,payload in cursor:
                    entry=('{"key":'+compact(key)+',"place":'+payload+'}').encode()
                    if len(entry)+len(prefix_bytes)+3>shard_limit:raise ValueError('Single place entry exceeds shard bound')
                    if parts and size+1+len(entry)>shard_limit:flush()
                    if first is None:first=key
                    last=key;size+=len(entry)+(1 if parts else 0);parts.append(entry)
                flush()
                name=region_names.get(code+'.'+region) or ('Unspecified source region' if region in {'','00'} else 'Source region '+region)
                regions.append({'code':region,'name':name,'count':count,'shards':shards})
            country_manifest={'schemaVersion':1,'datasetId':dataset,'code':code,'name':country['name'],'count':sum(r['count'] for r in regions),'regions':regions}
            relative=f'{dataset}/countries/{code.lower()}/manifest.json';meta=write_json(output_dir/relative,country_manifest);asset_count+=1;total_bytes+=meta['bytes']
            manifest_countries.append({'code':code,'name':country['name'],'count':country_manifest['count'],'manifestPath':'/assets/world-places/'+relative,'manifestBytes':meta['bytes'],'manifestSha256':meta['sha256']})
        db.close()
    invalid=sum(v for k,v in ignored.items() if k.startswith(('invalid-','unmapped-country:')))
    manifest={'schemaVersion':1,'datasetId':dataset,'sourceDate':lock['sourceDate'],'sourceURL':lock['geonames']['url'],'sourceSha256':lock['geonames']['sha256'],'sourceBytes':lock['geonames']['bytes'],'license':'CC BY 4.0','licenseURL':'https://creativecommons.org/licenses/by/4.0/','attribution':ATTRIBUTION,'timezoneVersion':lock['timezoneVersion'],'recordCount':sum(counts.values()),'countries':manifest_countries,'excludedFeatureCodes':EXCLUDED_CODES,'missingTimeZoneCount':missing_zones,'invalidRecordCount':invalid,'scope':SCOPE}
    meta=write_json(output_dir/'manifest.json',manifest);asset_count+=1;total_bytes+=meta['bytes']
    if asset_count>MAX_ASSET_FILES or total_bytes>MAX_OUTPUT_BYTES:raise ValueError('Generated asset budget exceeded')
    receipt={'datasetId':dataset,'sourceRows':source_rows,'recordCount':manifest['recordCount'],'countries':len(manifest_countries),'countriesWithPlaces':sum(c['count']>0 for c in manifest_countries),'emptyCountryCodes':[c['code'] for c in manifest_countries if not c['count']],'regions':len(counts),'searchEntries':search_entries,'assetFiles':asset_count,'assetBytes':total_bytes,'largestShardBytes':shard_limit,'missingTimeZoneCount':missing_zones,'ignoredRows':dict(sorted(ignored.items())),'manifestSha256':meta['sha256'],'durationSeconds':round(time.monotonic()-started,3)}
    return manifest,receipt

def create_archive(directory, target, epoch, base_output):
    directory=Path(directory);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    base_output=Path(base_output)
    generated=[]
    for name in ['world-countries.generated.json','world-timezones.generated.json']:
        path=base_output/name
        if not path.is_file() or path.is_symlink() or path.stat().st_size>2*1024*1024:raise ValueError('Invalid generated base metadata')
        generated.append({'fileName':name,'bytes':path.stat().st_size,'sha256':digest(path)})
    manifest=json.loads((directory/'manifest.json').read_text())
    bundle={'schemaVersion':1,'datasetId':manifest['datasetId'],'placeManifestSha256':digest(directory/'manifest.json'),'generatedFiles':generated}
    bundle_bytes=(compact(bundle)+'\n').encode()
    with target.open('wb') as output:
        with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=epoch,compresslevel=5) as gz:
            with tarfile.open(fileobj=gz,mode='w|') as tar:
                def add(name,body):
                    info=tarfile.TarInfo(name);info.size=len(body);info.mtime=epoch;info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644;tar.addfile(info,io.BytesIO(body))
                add('bundle-manifest.json',bundle_bytes)
                for item in generated:add('generated/'+item['fileName'],(base_output/item['fileName']).read_bytes())
                for path in sorted(directory.rglob('*')):
                    if not path.is_file() or path.is_symlink():continue
                    relative=path.relative_to(directory).as_posix();info=tarfile.TarInfo('world-places/'+relative);info.size=path.stat().st_size;info.mtime=epoch;info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644
                    with path.open('rb') as f:tar.addfile(info,f)
    if target.stat().st_size>=2*1024**3:raise ValueError('Archive exceeds GitHub release asset bound')
    return {'fileName':target.name,'bytes':target.stat().st_size,'sha256':digest(target),'manifestSha256':bundle['placeManifestSha256'],'bundleManifestSha256':hashlib.sha256(bundle_bytes).hexdigest(),'generatedFiles':generated}

def verify_assets(directory, lock, expected_manifest_sha):
    directory=Path(directory);main=directory/'manifest.json'
    if digest(main)!=expected_manifest_sha:raise ValueError('Installed manifest checksum mismatch')
    manifest=json.loads(main.read_text())
    if manifest.get('datasetId')!=lock['datasetId'] or manifest.get('sourceSha256')!=lock['geonames']['sha256']:raise ValueError('Installed data edition mismatch')
    files={'manifest.json'};count=0;total=main.stat().st_size
    def path_for(url):
        prefix='/assets/world-places/'
        if not isinstance(url,str) or not url.startswith(prefix):raise ValueError('Invalid asset URL')
        relative=url[len(prefix):];parts=Path(relative).parts
        if not relative or relative.startswith('/') or any(p in {'..','.'} for p in parts):raise ValueError('Unsafe asset URL')
        path=directory/relative
        if path.is_symlink() or not path.is_file():raise ValueError('Missing or unsafe generated asset')
        return relative,path
    for country in manifest['countries']:
        relative,path=path_for(country['manifestPath']);files.add(relative)
        if path.stat().st_size!=country['manifestBytes'] or digest(path)!=country['manifestSha256']:raise ValueError('Country manifest integrity mismatch')
        total+=path.stat().st_size;data=json.loads(path.read_text())
        if data['code']!=country['code'] or data['count']!=country['count'] or data['datasetId']!=lock['datasetId']:raise ValueError('Country manifest identity mismatch')
        count+=data['count']
        if sum(region['count'] for region in data['regions'])!=data['count']:raise ValueError('Region inventory mismatch')
        for region in data['regions']:
            for shard in region['shards']:
                relative,path=path_for(shard['path'])
                if relative in files:raise ValueError('Duplicate generated asset path')
                files.add(relative)
                if shard['bytes']>SHARD_LIMIT or path.stat().st_size!=shard['bytes'] or digest(path)!=shard['sha256']:raise ValueError('Place shard integrity mismatch')
                total+=path.stat().st_size
    if count!=manifest['recordCount']:raise ValueError('Global place inventory mismatch')
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual!=files or len(files)>MAX_ASSET_FILES or total>MAX_OUTPUT_BYTES:raise ValueError('Unexpected generated asset inventory')
    return {'files':len(files),'bytes':total,'recordCount':count}

def install_archive(lock, cache, target, base_output):
    spec=lock.get('archive')
    if not spec:raise ValueError('No publicly versioned archive has been pinned. Data build/publication must complete before deployment.')
    generated=spec.get('generatedFiles',[]);allowed_names={'world-countries.generated.json','world-timezones.generated.json'}
    if {item.get('fileName') for item in generated}!=allowed_names or len(generated)!=2:raise ValueError('Missing pinned base metadata hashes')
    archive=download_source(spec,cache)
    target=Path(target);base_output=Path(base_output)
    if target.exists():
        existing=target/'manifest.json'
        if existing.exists() and digest(existing)==spec['manifestSha256']:
            valid=all((base_output/item['fileName']).is_file() and (base_output/item['fileName']).stat().st_size==item['bytes'] and digest(base_output/item['fileName'])==item['sha256'] for item in generated)
            if valid:return {'status':'verified-existing','datasetId':lock['datasetId'],**verify_assets(target,lock,spec['manifestSha256'])}
        if not existing.exists() or json.loads(existing.read_text()).get('schemaVersion')!=1:raise ValueError('Refuse to replace an unrelated output directory')
    temp=target.with_name(target.name+'.building');temp.mkdir(parents=True,exist_ok=False);count=0;total=0
    try:
        with tarfile.open(archive,'r:gz') as tar:
            for member in tar:
                parts=Path(member.name).parts
                allowed=member.name=='bundle-manifest.json' or len(parts)>=2 and parts[0]=='world-places' or len(parts)==2 and parts[0]=='generated' and parts[1] in allowed_names
                if not member.isfile() or not allowed or any(p in {'..','.'} for p in parts) or member.name.startswith('/') or member.size>2*1024*1024:raise ValueError('Unsafe archive asset')
                count+=1;total+=member.size
                if count>MAX_ASSET_FILES+3 or total>MAX_OUTPUT_BYTES+4*1024*1024:raise ValueError('Archive asset budget exceeded')
                destination=temp.joinpath(*parts);destination.parent.mkdir(parents=True,exist_ok=True)
                if destination.exists():raise ValueError('Duplicate archive member')
                with tar.extractfile(member) as source,destination.open('wb') as out:shutil.copyfileobj(source,out,1024*1024)
        if digest(temp/'bundle-manifest.json')!=spec.get('bundleManifestSha256'):raise ValueError('Bundle manifest integrity mismatch')
        for item in generated:
            path=temp/'generated'/item['fileName']
            if path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise ValueError('Generated base metadata integrity mismatch')
        verified=verify_assets(temp/'world-places',lock,spec['manifestSha256'])
        target.parent.mkdir(parents=True,exist_ok=True)
        previous=target.with_name(target.name+'.previous')
        if previous.exists():raise ValueError('Previous generated directory needs review before replacement')
        if target.exists():target.replace(previous)
        try:(temp/'world-places').replace(target)
        except Exception:
            if previous.exists():previous.replace(target)
            raise
        if previous.exists():shutil.rmtree(previous)
        base_output.mkdir(parents=True,exist_ok=True)
        for item in generated:(temp/'generated'/item['fileName']).replace(base_output/item['fileName'])
        shutil.rmtree(temp)
        return {'status':'installed','datasetId':lock['datasetId'],**verified}
    except Exception:
        shutil.rmtree(temp,ignore_errors=True);raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock',default='data/world-sources.lock.json');parser.add_argument('--source-dir',default='/tmp/contifield-world-data-source');parser.add_argument('--download',action='store_true');parser.add_argument('--mirror-base');parser.add_argument('--base-output',default='src/data');parser.add_argument('--places-output');parser.add_argument('--archive-output');parser.add_argument('--receipt-output');parser.add_argument('--install-output')
    args=parser.parse_args();lock=read_lock(args.lock)
    if args.install_output:
        print(compact(install_archive(lock,args.source_dir,args.install_output,args.base_output)));return
    files=source_files(lock,args.source_dir,args.download,args.mirror_base)
    timezone_data,countries=build_timezones(lock,files,args.base_output)
    receipt={'schemaVersion':1,'datasetId':lock['datasetId'],'timezoneVersion':lock['timezoneVersion'],'canonicalZones':len(timezone_data['zones']),'aliases':len(timezone_data['aliases']),'countryCount':len(countries)}
    if args.places_output:
        manifest,places_receipt=build_places(lock,files,timezone_data,countries,args.places_output);receipt['places']=places_receipt
        if args.archive_output:
            epoch=int(dt.datetime.fromisoformat(lock['sourceDate']).replace(tzinfo=dt.timezone.utc).timestamp());receipt['archive']=create_archive(args.places_output,args.archive_output,epoch,args.base_output)
    if args.receipt_output:write_json(args.receipt_output,receipt)
    print(compact(receipt),flush=True)

if __name__=='__main__':main()
