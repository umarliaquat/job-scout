"""Job Scout: local, dependency-free job discovery and evidence collection.

Run: python scout.py serve | scan | export
Only public read-only sources. No LLM, account, API key, application submission.
"""
from __future__ import annotations
import argparse
import concurrent.futures as futures
import csv
import hashlib
import html
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
UTC = timezone.utc
AGENT = 'PersonalJobScout/1.0 (personal read-only job research)'
MAX_BYTES = 5_000_000
class SourceNeedsReview(ValueError):
    """Readable page, but automated vacancy coverage cannot be established."""
    def __init__(self, message, jobs=None):
        super().__init__(message)
        self.jobs = jobs or []

class SourceNoMatches(ValueError):
    """Employer data was read successfully and contains no matching remote roles."""
STATE = {'running': False, 'message': 'Ready to scan', 'last_result': None}
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(32)
ROBOTS = {}
FETCH_LOCKS = {}
HIMALAYAS_LOCK = threading.Lock()
HIMALAYAS_LAST_REQUEST = 0.0


def now():
    return datetime.now(UTC).isoformat()


def plain(value):
    decoded=html.unescape(html.unescape(str(value or '')))
    return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',decoded)).strip()


def date(value):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            n = float(value)
            return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, UTC).isoformat()
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)).isoformat()
    except (ValueError, OverflowError, OSError):
        for fmt in ('%b %d, %Y','%B %d, %Y','%d %B %Y'):
            try:
                return datetime.strptime(str(value),fmt).replace(tzinfo=UTC).isoformat()
            except ValueError:
                pass
        return None


def age_days(value):
    parsed = date(value)
    return (datetime.now(UTC) - datetime.fromisoformat(parsed)).days if parsed else None


def public_url(url):
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Only public HTTP(S) URLs are allowed')
    if p.port not in (None, 80, 443):
        raise ValueError('Unsupported remote port')
    for addr in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80)):
        if not ipaddress.ip_address(addr[4][0]).is_global:
            raise ValueError('Private or reserved network destination blocked')
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, public_url(newurl))


def fetch(url, cache_hours=0):
    with FETCH_LOCKS.setdefault(url, threading.Lock()):
        return _fetch(url, cache_hours)


def _fetch(url, cache_hours=0):
    public_url(url)
    DATA.joinpath('cache').mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    cached = DATA / 'cache' / (key + '.json')
    if cached.exists() and time.time() - cached.stat().st_mtime < cache_hours * 3600:
        record = json.loads(cached.read_text('utf-8'))
        return record['text'], record['url'], True
    req = Request(url, headers={'User-Agent': AGENT, 'Accept': 'application/json,text/html,application/rss+xml;q=0.9,*/*;q=0.8'})
    with build_opener(SafeRedirect()).open(req, timeout=15) as response:
        # Large employer boards legitimately exceed the ordinary HTML-page limit.
        limit = 15_000_000 if urlparse(url).hostname == 'api.ashbyhq.com' else MAX_BYTES
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError(f'Page exceeds {limit // 1_000_000} MB limit')
        text = content.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        final = response.url
    if cache_hours:
        tmp = cached.with_suffix('.tmp')
        tmp.write_text(json.dumps({'text': text, 'url': final}), 'utf-8')
        tmp.replace(cached)
    return text, final, False


def json_fetch(url, hours):
    text, _, cached = fetch(url, hours)
    return json.loads(text), cached


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DATA / 'scout.sqlite3', timeout=30, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, state TEXT DEFAULT 'new', notes TEXT DEFAULT '');
      CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started TEXT, finished TEXT, summary TEXT);
      CREATE TABLE IF NOT EXISTS sources(name TEXT PRIMARY KEY, checked TEXT, status TEXT, detail TEXT);
    ''')
    return db


def config():
    cfg = json.loads((ROOT / 'sources.json').read_text('utf-8'))
    extra = DATA / 'employers.json'
    if extra.exists():
        cfg['boards'] += json.loads(extra.read_text('utf-8'))
    for board in cfg['boards']:
        if board['kind']=='page':
            adapter=board_from_url(board.get('url',''),board['company'],board.get('website',''))
            if adapter: board.update(adapter)
    cfg['boards'] = list({b['kind'] + ':' + b.get('slug', b.get('url','')):b for b in cfg['boards']}.values())
    return cfg


def role(title):
    t = title.lower()
    if re.search(r'product manager|account executive|recruiter|sales engineer', t):
        return None
    if re.search(r'mechanical|electrical|hardware|cad\b|civil|industrial designer|silicon|physical design|overhead line|\bohl\b|structural|piping|hvac', t):
        return None
    if re.search(r'design engineer|ux engineer|ui engineer|creative (?:developer|technologist)', t):
        return 'Design engineering'
    if re.search(r'product design|ux\s*\(ui\)\s*design|ux.?ui|ui.?ux|ux design|ui design|user experience|interaction design', t):
        return 'Product design'
    if re.search(r'product engineer|product builder', t):
        return 'Product engineering'
    if re.search(r'front.?end|full.?stack|web (?:developer|engineer)', t):
        return 'Frontend / full stack'
    if re.search(r'(?:website|web|digital|creative production|multi.skilled) designer',t):
        return 'Web / visual design'
    return None


def geography(location, description):
    # Restrictive statements beat broad marketing language. Never infer eligibility from a timezone.
    loc = plain(location)
    text = loc + '. ' + plain(description)
    def context(match):
        return text[max(0,match.start()-60):min(len(text),match.end()+220)].strip()
    restricted = re.search(r'must (?:reside|live|be (?:based|located|resident))|authorized to work|authorised to work|residen(?:cy|ts) (?:in|of)|(?:US|USA|United States|UK|EU|Europe)[ -]only|remote within|U\.?S\.?[ -]based', text, re.I)
    if restricted:
        return 'Restricted / review', context(restricted)
    if re.search(r'\bpakistan\b', loc, re.I):
        return 'Pakistan listed', loc
    # A named location list must not be overridden by an unrelated worldwide marketing claim.
    if loc and re.search(r'\b(?:US|USA|UK|EU|Europe|United States|Canada|Germany|France|Americas|America|Australia|India)\b', loc, re.I) and not re.search(r'worldwide|global|anywhere', loc, re.I):
        return 'Worth a chance', 'Advertised location: ' + loc + '. Pakistan is not explicitly listed; ask about flexibility.'
    worldwide = None
    for candidate in re.finditer(r'we hire (?:globally|worldwide)|hiring (?:globally|worldwide)|work from anywhere|remote[ :–-]+global|globally remote|open (?:to applicants )?worldwide', text, re.I):
        tail=text[candidate.end():candidate.end()+90]
        if not re.search(r'\b(?:for|up to)\s+\d+|\b(?:weeks?|days?)/(?:year|month)',tail,re.I):
            worldwide=candidate
            break
    if re.search(r'^(?:anywhere|worldwide|global|anywhere in (?:the )?world|remote[ :–-]+global|global[ :–-]+remote)$', loc.strip(), re.I):
        return 'Worldwide advertised', loc
    if worldwide:
        return 'Worldwide advertised', context(worldwide)
    location_clause=re.search(r'\b(?:location\b|based in\b|remote within\b|remote in\b|country requirements|residency)[^.!?]{0,200}',plain(description),re.I)
    evidence=location_clause.group(0) if location_clause else loc or 'No applicant-country information supplied; ask the employer.'
    return 'Worth a chance', evidence


def make_job(company, title, location, description, url, source, **extra):
    title, company = plain(title), plain(company).strip()
    category = role(title)
    if not category or not url or not company:
        return None
    desc = plain(description)
    workplace = extra.get('workplace', '')
    location = str(location or '')
    workplace = str(workplace or '')
    remote = bool(re.search(r'\bremote\b|worldwide|work from anywhere', location + ' ' + workplace, re.I))
    if workplace.lower() in ('onsite', 'on-site', 'hybrid'):
        return None
    if not remote and not re.search(r'fully remote|100% remote|remote.first|remote role|remote position|role is remote', desc, re.I):
        return None
    geo, evidence = geography(location, desc)
    # Company + role + location joins duplicate syndications while retaining every source URL.
    identity = '|'.join(re.sub(r'[^a-z0-9]', '', s.lower()) for s in (company, title, location))
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:20], company=company,
                title=title, category=category, location=plain(location), description=desc[:18000],
                url=url, source=source, sources=[{'name': source, 'url': url}],
                eligibility=geo, eligibility_evidence=evidence, published=None,
                date_basis='Unknown', modified=None, salary='', company_url='',
                credibility='Not independently checked', verification='Not checked',
                verification_evidence='Application destination has not been checked.', checked_at=None,
                application_url='', direct=False, **{k:v for k,v in extra.items() if k != 'workplace'})


def board_jobs(board, hours):
    kind, slug = board['kind'], board['slug']
    if kind == 'page':
        return career_page_jobs(board, hours)
    if kind == 'workable':
        return workable_jobs(board, hours)
    if kind == 'ashby':
        endpoint = f'https://api.ashbyhq.com/posting-api/job-board/{slug}'
        data, cached = json_fetch(endpoint, hours)
        if not isinstance(data.get('jobs'), list):
            raise ValueError('Invalid Ashby board response')
        items = data['jobs']
    elif kind == 'greenhouse':
        endpoint = f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'
        data, cached = json_fetch(endpoint, hours)
        items = data['jobs']
    elif kind == 'lever':
        endpoint = f'https://api.lever.co/v0/postings/{slug}?mode=json'
        items, cached = json_fetch(endpoint, hours)
        if not isinstance(items, list):
            raise ValueError('Invalid Lever board response')
    else:
        raise ValueError('Unsupported board type')
    jobs = []
    for item in items:
        if kind == 'ashby':
            if item.get('isListed') is False:
                continue
            title = item.get('title', '')
            location = item.get('location') or '; '.join(x.get('location','') for x in item.get('secondaryLocations', []))
            description = item.get('descriptionHtml') or item.get('descriptionPlain', '')
            url = item.get('jobUrl', '')
            published = item.get('publishedAt')
            basis = 'Last published by employer'
            apply = item.get('applyUrl', '')
            workplace = 'remote' if item.get('isRemote') else item.get('workplaceType', '')
        elif kind == 'greenhouse':
            title = item.get('title', '')
            location = item.get('location', {}).get('name', '')
            description = item.get('content', '')
            url = item.get('absolute_url', '')
            published = item.get('first_published')
            basis = 'Employer publication' if published else 'Unknown (modification is not publication)'
            apply, workplace = '', ''
        else:
            title = item.get('text', '')
            location = item.get('categories', {}).get('location', '')
            description = (item.get('descriptionPlain') or item.get('description', '')) + ' ' + ' '.join(plain(x.get('content')) for x in item.get('lists', []))
            url = item.get('hostedUrl', '')
            published = item.get('createdAt')
            basis = 'Employer creation date' if published else 'Unknown'
            apply = item.get('applyUrl', '')
            workplace = item.get('workplaceType', '')
        j = make_job(board['company'], title, location, description, url, kind.title() + ': ' + board['company'], workplace=workplace)
        if j:
            if kind == 'ashby' and item.get('compensation'):
                j['salary'] = plain(item['compensation'].get('compensationTierSummary', ''))
            j.update(published=date(published), date_basis=basis, modified=date(item.get('updated_at')),
                     company_url=board.get('website', ''), application_url=apply, direct=True,
                     credibility='Configured employer board; business identity still needs human review',
                     board_key=kind + ':' + slug, board_observed=now(), board_cached=cached)
            jobs.append(j)
    return jobs, cached


def workable_jobs(board, hours):
    """Public widget feed + public vacancy details, deduplicated by shortcode."""
    slug=board['slug']
    data,cached=json_fetch(f'https://apply.workable.com/api/v1/widget/accounts/{slug}',hours)
    grouped={}
    for item in data['jobs']:
        if not role(item.get('title','')) or not item.get('telecommuting'):
            continue
        key=item['shortcode']
        record=grouped.setdefault(key,dict(item,countries=set()))
        record['countries'].update(x['country'] for x in item.get('locations',[]) if x.get('country'))
        if item.get('country'): record['countries'].add(item['country'])
    jobs=[]
    for code,item in grouped.items():
        # An old listing is not made recent by re-reading the widget.
        published=date(item.get('published_on'))
        if published and age_days(published)>30:
            detail,hit=dict(item,state='published',published=item.get('published_on')),True
        else:
            detail,hit=json_fetch(f'https://apply.workable.com/api/v2/accounts/{slug}/jobs/{code}',hours)
        if detail.get('state')!='published' or detail.get('isInternal'):
            continue
        location='; '.join(sorted(item['countries'])) or 'Remote · country unconfirmed'
        description=' '.join(detail.get(k,'') or '' for k in ('description','requirements','benefits'))
        url=f'https://apply.workable.com/{slug}/j/{code}/'
        j=make_job(board['company'],detail['title'],location,description,url,'Workable: '+board['company'],workplace='remote')
        if j:
            j.update(published=date(detail.get('published')) or published,date_basis='Employer Workable publication',
                     company_url=board.get('website',''),application_url=url+'apply',direct=True,
                     board_key='workable:'+slug,board_observed=now(),board_cached=cached and hit,
                     research_notes=board.get('research_notes',''),ats_state='published')
            jobs.append(j)
    return jobs,cached


def himalayas_json(url, hours=24):
    """Keyless public API only, with a persistent daily cap and request pacing."""
    global HIMALAYAS_LAST_REQUEST
    if urlparse(url).hostname != 'himalayas.app' or not urlparse(url).path.startswith('/jobs/api'):
        raise ValueError('Only the free public Himalayas API is supported')
    with HIMALAYAS_LOCK:
        cache=DATA/'cache'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if cache.exists() and time.time()-cache.stat().st_mtime<hours*3600:
            record=json.loads(cache.read_text('utf-8'))
            return json.loads(record['text']),True
        DATA.mkdir(exist_ok=True)
        path=DATA/'himalayas-usage.json'
        today=datetime.now(UTC).date().isoformat()
        usage=json.loads(path.read_text('utf-8')) if path.exists() else {}
        if usage.get('date')!=today: usage=dict(date=today,requests=0)
        cap=min(100,max(1,int(config().get('himalayas_daily_request_cap',80))))
        if usage['requests']>=cap:
            raise ValueError(f'Himalayas free-only daily safety cap ({cap} requests) reached; try tomorrow')
        delay=1.1-(time.monotonic()-HIMALAYAS_LAST_REQUEST)
        if delay>0: time.sleep(delay)
        usage['requests']+=1
        path.write_text(json.dumps(usage),'utf-8')
        HIMALAYAS_LAST_REQUEST=time.monotonic()
        # Count failures too. No credentials, paid endpoint or automatic upgrade.
        return json_fetch(url,hours)


def himalayas_jobs(hours):
    cfg=config()
    jobs={};cached=True
    queries=cfg.get('himalayas_queries',['product designer','UX designer','UI designer','web designer','design engineer'])
    for query in queries:
        for scope in ({'country':'Pakistan'},{'worldwide':'true'}):
            for page in range(1,min(5,cfg.get('himalayas_pages_per_query',3))+1):
                params=dict(q=query,sort='recent',page=page,**scope)
                data,hit=himalayas_json('https://himalayas.app/jobs/api/search?'+urlencode(params),max(hours,24))
                cached=cached and hit
                items=data.get('jobs',[])
                if not items: break
                for item in items:
                    guid=item.get('guid','')
                    if guid in jobs: continue
                    expiry=date(item.get('expiryDate'))
                    if expiry and datetime.fromisoformat(expiry)<datetime.now(UTC): continue
                    countries=item.get('locationRestrictions') or []
                    location='; '.join(countries) if countries else 'Worldwide'
                    j=make_job(item.get('companyName'),item.get('title',''),location,item.get('description',''),guid,'Himalayas',workplace='remote')
                    if not j or j['category'] not in ('Product design','Design engineering','Web / visual design'): continue
                    j.update(application_url=item.get('applicationLink') or guid,
                             modified=date(item.get('pubDate')),published=None,date_basis='Unknown; Himalayas pubDate is an update date',
                             himalayas_guid=guid,himalayas_timezones=item.get('timezoneRestrictions') or [],
                             expires=expiry,company_profile_url='https://himalayas.app/companies/'+item.get('companySlug',''),
                             research_notes='Discovered through the free Himalayas API. Update time is not an original publication date. Check employer application evidence and country requirements.')
                    if item.get('minSalary') or item.get('maxSalary'):
                        j['salary']=f"{item.get('minSalary') or '?'}–{item.get('maxSalary') or '?'} {item.get('currency') or ''} / {item.get('salaryPeriod') or 'unspecified'}"
                    jobs[guid]=j
    return list(jobs.values()),cached


def arbeitnow_jobs(name,hours):
    cfg=config();jobs=[];cached=True;seen=set()
    host='www.arbeitnow.co.uk' if name=='arbeitnow_uk' else 'www.arbeitnow.com'
    label='Arbeitnow UK' if name=='arbeitnow_uk' else 'Arbeitnow Europe'
    cap=min(30,max(1,int(cfg.get('arbeitnow_max_pages',20))))
    for page in range(1,cap+1):
        if page>1: time.sleep(1.1)
        try:
            data,hit=json_fetch(f'https://{host}/api/job-board-api?'+urlencode({'page':page}),hours)
        except HTTPError as e:
            # Do not retry a provider throttle. Preserve readable earlier pages,
            # but report incomplete pagination rather than claiming full coverage.
            if jobs:
                raise SourceNeedsReview(f'Partial pagination: {len(jobs)} matching jobs on earlier pages; HTTP {e.code} stopped page {page}.',jobs) from e
            raise
        cached=cached and hit
        items=data.get('data',[])
        if not items: break
        for item in items:
            url=item.get('url','')
            if url in seen or not item.get('remote'): continue
            seen.add(url)
            j=make_job(item.get('company_name'),item.get('title'),item.get('location',''),item.get('description'),url,label,workplace='remote')
            if j:
                j.update(published=date(item.get('created_at')),date_basis='Job-board publication')
                jobs.append(j)
        dates=[age_days(date(x.get('created_at'))) for x in items]
        if dates and all(age is not None and age>cfg['max_age_days'] for age in dates): break
        if 'links' in data and not data['links'].get('next'): break
    return jobs,cached


def feed_jobs(name, hours):
    jobs = []
    if name=='himalayas': return himalayas_jobs(hours)
    if name in ('arbeitnow','arbeitnow_uk'): return arbeitnow_jobs(name,hours)
    if name == 'remotive':
        data, cached = json_fetch('https://remotive.com/api/remote-jobs', hours)
        for x in data['jobs']:
            j = make_job(x.get('company_name'), x.get('title'), x.get('candidate_required_location', ''), x.get('description'), x.get('url'), 'Remotive', workplace='remote')
            if j:
                j.update(published=date(x.get('publication_date')), date_basis='Job-board publication', salary=x.get('salary', ''))
                jobs.append(j)
    elif name == 'remoteok':
        data, cached = json_fetch('https://remoteok.com/api', hours)
        for x in data:
            if not x.get('position'):
                continue
            j = make_job(x.get('company'), x.get('position'), x.get('location', ''), x.get('description'), x.get('url'), 'Remote OK', workplace='remote')
            if j:
                salary = f"{x.get('salary_min')}–{x.get('salary_max')} (feed units; verify listing)" if x.get('salary_min') else ''
                j.update(published=date(x.get('date') or x.get('epoch')), date_basis='Job-board publication', salary=salary)
                jobs.append(j)
    elif name == 'wwr':
        text, _, cached = fetch('https://weworkremotely.com/remote-jobs.rss', hours)
        for x in ET.fromstring(text).findall('.//item'):
            title = x.findtext('title', '')
            company, sep, title = title.partition(': ')
            if not sep:
                continue
            from email.utils import parsedate_to_datetime
            try:
                published = parsedate_to_datetime(x.findtext('pubDate')).astimezone(UTC).isoformat()
            except (ValueError, TypeError):
                published = None
            j = make_job(company, title, x.findtext('region', ''), x.findtext('description'), x.findtext('link'), 'We Work Remotely', workplace='remote')
            if j:
                j.update(published=published, date_basis='Job-board publication')
                jobs.append(j)
    elif name == 'jobicy':
        cached = True
        params = {'count':200}
        for _ in range(5):
            data, hit = json_fetch('https://jobicy.com/api/jobs?' + urlencode(params), hours)
            cached = cached and hit
            if data.get('success') is False:
                raise ValueError(data.get('error','Jobicy feed failed'))
            for x in data['jobs']:
                j = make_job(x.get('companyName'), x.get('jobTitle'), x.get('jobGeo',''), x.get('jobDescription'), x.get('url'), 'Jobicy', workplace='remote')
                if j:
                    salary = f"{x.get('salaryMin','?')}–{x.get('salaryMax','?')} {x.get('salaryCurrency','')} / {x.get('salaryPeriod','unspecified period')}" if x.get('salaryMin') or x.get('salaryMax') else ''
                    j.update(published=date(x.get('pubDate')),date_basis='Job-board publication',salary=salary)
                    jobs.append(j)
            cursor = data.get('nextCursor')
            if not cursor:
                break
            params['cursor'] = cursor
    else:
        raise ValueError('Unknown feed')
    return jobs, cached


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.links, self.blocks = [], [], []
        self.script = None
        self.anchor = None
        self.skip = 0
        self.has_form = False
        self.in_form = 0
        self.form_fields = []
        self.forms = []
        self.heading = ''
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'h1':
            self.in_heading = True
        if tag == 'script':
            self.skip += 1
            if 'ld+json' in a.get('type', ''):
                self.script = ''
        if tag == 'style':
            self.skip += 1
        if tag == 'a':
            self.anchor = [a.get('href', ''), '']
        if tag == 'form':
            self.has_form = True
            self.in_form += 1
            self.forms.append({'identity':' '.join(str(v) for v in a.values()),'fields':[]})
        if self.in_form and tag in ('input','textarea'):
            self.form_fields.append((a.get('type','text'), a.get('name','') + ' ' + a.get('id','') + ' ' + a.get('autocomplete','')))
            if self.forms:
                self.forms[-1]['fields'].append(self.form_fields[-1])

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_heading = False
        if tag == 'form':
            self.in_form = max(0, self.in_form - 1)
        if tag == 'script' and self.script is not None:
            try:
                self.blocks.append(json.loads(self.script))
            except (ValueError, TypeError):
                pass
            self.script = None
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag == 'a' and self.anchor:
            self.links.append(tuple(self.anchor))
            self.anchor = None

    def handle_data(self, value):
        if self.script is not None:
            self.script += value
        if not self.skip:
            self.parts.append(value)
            if self.in_heading:
                self.heading += value
            if self.anchor:
                self.anchor[1] += value


def posting_blocks(value):
    if isinstance(value, list):
        for x in value:
            yield from posting_blocks(x)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
            yield value
        if '@graph' in value:
            yield from posting_blocks(value['@graph'])


def application_form(page):
    for form in page.forms:
        fields=form['fields']
        has_email=any(t=='email' or re.search('email',n,re.I) for t,n in fields)
        resume=any(re.search(r'resume|\bcv\b|curriculum',n,re.I) for t,n in fields)
        name=any(re.search(r'first.?name|last.?name|given.name|family.name',n,re.I) for t,n in fields)
        application=bool(re.search(r'application|candidate|job.apply',form['identity'],re.I))
        if has_email and (resume or application and name):
            return True
    return False


def board_from_url(url, company, website=''):
    p = urlparse(url)
    host = (p.hostname or '').lower()
    parts = [x for x in p.path.split('/') if x]
    if host == 'jobs.ashbyhq.com' and parts:
        return dict(company=company,kind='ashby',slug=parts[0],website=website)
    if host in ('jobs.lever.co','jobs.eu.lever.co') and parts:
        if host == 'jobs.eu.lever.co':
            return None  # EU instances must not be silently mapped to global.
        return dict(company=company,kind='lever',slug=parts[0],website=website)
    if host in ('boards.greenhouse.io','job-boards.greenhouse.io','job-boards.eu.greenhouse.io') and parts:
        return dict(company=company,kind='greenhouse',slug=parts[0],website=website)
    if host == 'apply.workable.com' and parts and parts[0] not in ('j','api'):
        return dict(company=company,kind='workable',slug=parts[0],website=website)
    return None


def add_employer(company, website, url):
    if not company.strip():
        raise ValueError('Company name is required')
    public_url(url)
    public_url(website)
    b = board_from_url(url, company.strip(), website)
    if not b:
        b = dict(company=company.strip(),kind='page',slug=hashlib.sha256(url.encode()).hexdigest()[:12],website=website,url=url)
    DATA.mkdir(exist_ok=True)
    path = DATA / 'employers.json'
    with LOCK:
        extra = json.loads(path.read_text('utf-8')) if path.exists() else []
        extra = list({(x['kind'],x['slug']):x for x in extra + [b]}.values())
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(extra,indent=2),'utf-8');tmp.replace(path)
    return b


def career_page_jobs(board, hours):
    url = board['url']
    if not permitted(url):
        raise ValueError('Robots policy does not permit checking this page')
    text, final, cached = fetch(url, hours)
    page = Page(); page.feed(text)
    linked_board = board_from_url(final, board['company'], board['website'])
    if linked_board:
        return board_jobs(linked_board,hours)
    # Some public career pages embed the ATS instead of linking individual roles.
    # Only follow exact employer-published ATS URLs, never guessed company slugs.
    ats_urls = [urljoin(final,h) for h,_ in page.links]
    ats_urls += re.findall(r'https://(?:jobs\.ashbyhq\.com|jobs\.lever\.co|apply\.workable\.com|(?:job-boards|boards)\.greenhouse\.io)/[^\s"<>\\]+',html.unescape(text))
    delegated = []
    for target in dict.fromkeys(ats_urls):
        candidate = board_from_url(target,board['company'],board['website'])
        if candidate and candidate not in delegated:
            delegated.append(candidate)
    if delegated:
        found=[];hits=True
        for candidate in delegated[:3]:
            records,hit=board_jobs(candidate,hours);found.extend(records);hits=hits and hit
        return list({j['id']:j for j in found}.values()),cached and hits
    candidates = [(final, page)]
    # Follow actual role links, never interpret a careers summary as an open vacancy.
    links = [(urljoin(final, href), label) for href,label in page.links if role(plain(label)) and href]
    for target, _ in list(dict(links).items())[:12]:
        if urlparse(target).scheme not in ('http','https') or target.split('#')[0] == final.split('#')[0]:
            continue
        try:
            if not permitted(target):
                continue
            body, dest, _ = fetch(target,hours)
            p = Page(); p.feed(body); candidates.append((dest,p))
        except Exception:
            continue
    jobs = []
    for target, p in candidates:
        page_jobs=[]
        for block in posting_blocks(p.blocks):
            loc = block.get('applicantLocationRequirements', [])
            if isinstance(loc, dict): loc = [loc]
            location = '; '.join(x.get('name','') for x in loc if isinstance(x,dict))
            rawloc = block.get('jobLocation') or []
            if isinstance(rawloc, dict): rawloc = [rawloc]
            if not location:
                location = '; '.join(plain(x.get('address',{}).get('addressCountry','')) for x in rawloc if isinstance(x,dict) and isinstance(x.get('address',{}),dict))
            if not location:
                location=board.get('location','')
            remote = 'remote' if block.get('jobLocationType') in ('TELECOMMUTE','Remote','REMOTE') else ''
            j = make_job(board['company'],block.get('title',''),location,block.get('description',''),block.get('url') or target,'Employer page: '+board['company'],workplace=remote)
            if j:
                j.update(published=date(block.get('datePosted')),date_basis='Employer JobPosting datePosted',company_url=board['website'],direct=True,board_key='page:'+board['slug'],board_observed=now(),board_cached=cached)
                page_jobs.append(j)
        # Dedicated role pages often have a heading and email/form instead of structured data.
        body=plain(' '.join(p.parts))
        if not page_jobs and role(plain(board.get('title') or p.heading)):
            emails=[h for h,label in p.links if h.startswith('mailto:') and re.search(r'apply|application|careers|hiring|jobs|\bhr\b',h+' '+label,re.I)]
            applying=bool(emails or application_form(p) or any(re.search(r'\bapply\b',label,re.I) for _,label in p.links) or re.search(r'\bapply now\b|\bhow to apply\b',body,re.I))
            evergreen=bool(re.search(r'evergreen|open applications year.round|not fixed openings|no active listing required|not always hiring',body,re.I))
            if applying and not evergreen:
                location=board.get('location','')
                if not location and re.search(r'\bremote\b',body[:400],re.I):
                    location='Remote · country unconfirmed'
                j=make_job(board['company'],board.get('title') or p.heading,location,body,target,'Employer page: '+board['company'])
                if j:
                    posted=re.search(r'\b(?:Posted|Published)(?:\s+on)?\s*:?\s*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',body,re.I)
                    value=date(posted.group(1)) if posted else None
                    j.update(published=value,date_basis='Visible employer posting date' if value else 'Unknown',company_url=board['website'],direct=True,board_key='page:'+board['slug'],board_observed=now(),board_cached=cached)
                    page_jobs.append(j)
        for j in page_jobs:
            if board.get('date_is_modified'):
                j.update(modified=j.get('published'),published=None,date_basis='Unknown; page only establishes an update date')
            note=board.get('research_notes_by_url',{}).get(j['url'],board.get('research_notes'))
            if note:
                j['research_notes']=note
            j['company_evidence']=board.get('company_evidence',[])
            jobs.append(j)
    if not jobs:
        body=plain(' '.join(page.parts))
        if list(posting_blocks(page.blocks)) or re.search(r'no (?:current |open |available )?(?:positions|vacancies|openings)|not currently hiring',body,re.I):
            raise SourceNoMatches('Readable employer vacancy data; no matching remote roles found.')
        raise SourceNeedsReview('Career page readable, but complete vacancy data is unavailable to this parser. Manual check required; not counted as successful coverage.')
    return jobs, cached


def permitted(url):
    p = urlparse(url)
    base = p.scheme + '://' + p.netloc
    if base not in ROBOTS:
        try:
            text, _, _ = fetch(base + '/robots.txt', 24)
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            ROBOTS[base] = parser
        except HTTPError as e:
            ROBOTS[base] = None if e.code == 404 else False
        except Exception:
            ROBOTS[base] = False
    parser = ROBOTS[base]
    return parser is None or parser is not False and parser.can_fetch(AGENT, url)


def verify(job):
    """A current aggregator record and an actual application path are separate evidence."""
    j=dict(job)
    if not j.get('himalayas_guid'):
        return _verify_application(j)
    try:
        p=urlparse(j['himalayas_guid'])
        if p.hostname!='himalayas.app' or not re.fullmatch(r'/companies/[^/]+/jobs/[^/]+/?',p.path):
            raise ValueError('Unrecognized Himalayas job identifier')
        data,cached=himalayas_json('https://himalayas.app/jobs/api'+p.path,1/6)
        item=data.get('job')
        if not item or item.get('guid')!=j['himalayas_guid']:
            raise ValueError('Himalayas status response did not match the requested vacancy')
        expiry=date(item.get('expiryDate'))
        if expiry and datetime.fromisoformat(expiry)<datetime.now(UTC):
            return dict(j,verification='Closed',checked_at=now(),verification_evidence='Himalayas listing expiry has passed.')
        j.update(aggregator_status='Listed on Himalayas',aggregator_checked_at=now())
        result=_verify_application(j)
        if result.get('application_url')!=j.get('application_url'):
            result['verified_destination']=result.get('application_url')
        # Preserve the provider's applicationLink exactly, including attribution.
        result['application_url']=j.get('application_url') or j['url']
        result['verification_evidence']+=' Himalayas status endpoint also lists this role; this does not establish employer eligibility.'
        return result
    except HTTPError as e:
        return dict(j,verification='Closed' if e.code==410 else 'Needs review',checked_at=now(),verification_evidence='Himalayas status returned HTTP '+str(e.code)+'.'+(' Listing is closed.' if e.code==410 else ' Application access needs a manual check.'))
    except Exception as e:
        return dict(j,verification='Needs review',checked_at=now(),verification_evidence='Himalayas status check could not be established: '+str(e)[:200])


def _verify_application(job):
    j = dict(job)
    j['checked_at'] = now()
    target = j.get('application_url') or j['url']
    try:
        if not permitted(target):
            j.update(verification='Needs review', verification_evidence='Automated access disallowed or robots policy unavailable. Open the listing manually.')
            return j
        text, final, cached = fetch(target, 12)
        page = Page()
        page.feed(text)
        body = plain(' '.join(page.parts))
        lower = body.lower()
        if any(s in lower for s in ('verify you are human', 'just a moment...', 'enable javascript and cookies', 'checking your browser')):
            j.update(verification='Needs review', verification_evidence='Access challenge; application availability could not be checked.')
            return j
        words = set(re.findall(r'[a-z]{3,}', j['title'].lower())) - {'senior','junior','remote','staff','lead','the','and'}
        matches = sum(w in lower for w in words)
        heading = plain(page.heading).lower()
        title_present = bool(words) and matches / len(words) >= .75
        if heading and role(heading):
            title_present = bool(words) and sum(w in heading for w in words) / len(words) >= .75
        # Only unequivocal vacancy-specific closure wording, not generic footer disclaimers.
        closed = re.search(r'(?:this (?:job|position|role|vacancy) (?:is |has been )?(?:no longer available|closed|filled)|(?:job|position) (?:is )?no longer (?:available|accepting applications)|no longer accepting applications for this (?:role|position))', lower)
        if closed:
            j.update(verification='Closed', verification_evidence=closed.group(0))
            return j
        for block in posting_blocks(page.blocks):
            block_title = plain(block.get('title', '')).lower()
            if not block_title or not all(w in block_title for w in words):
                continue
            expiry = date(block.get('validThrough'))
            if expiry and datetime.fromisoformat(expiry) < datetime.now(UTC):
                j.update(verification='Closed', verification_evidence='JobPosting validThrough has passed: ' + expiry)
                return j
            if not j.get('direct') and date(block.get('datePosted')) and not (j.get('himalayas_guid') and urlparse(final).hostname=='himalayas.app'):
                j.update(published=date(block['datePosted']), date_basis='Page JobPosting datePosted')
        email_links=[(h,label) for h,label in page.links if h.startswith('mailto:') and re.search(r'\bapply\b|application|careers|hiring|\bhr\b|\bjobs\b',label+' '+h,re.I)]
        if title_present and email_links:
            address=email_links[0][0][7:].split('?')[0]
            if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',address):
                j.update(verification='Email applications listed',application_email=address,application_url=final,
                         verification_evidence='Matching dedicated vacancy lists an email application route: '+address+'. Mailbox delivery and hiring activity have not been tested. No email was sent.')
                if cached:
                    j['verification_evidence']+=' Page cache is at most 12 hours old.'
                return j
        apply_links = [(urljoin(final, href), label) for href, label in page.links if re.search(r'\bapply\b|submit application', label, re.I) and href and not href.startswith(('#', 'javascript:', 'mailto:'))]
        valid_links = [x for x in apply_links if urlparse(x[0]).scheme in ('http','https')]
        specific = title_present and application_form(page)
        if specific:
            j.update(verification='Application form found', application_url=final,
                     verification_evidence='Matching role text and application form fields found. Submission has not been attempted.')
        elif title_present and valid_links:
            destination, _ = valid_links[0]
            j['application_url'] = destination
            # Follow destination. An Apply button alone is insufficient.
            if destination.split('#')[0] != final.split('#')[0] and permitted(destination):
                linked, resolved, _ = fetch(destination, 12)
                form = Page(); form.feed(linked)
                formtext = plain(' '.join(form.parts)).lower()
                linked_match = bool(words) and sum(w in formtext for w in words) / len(words) >= .75
                for block in posting_blocks(form.blocks):
                    title=plain(block.get('title','')).lower()
                    if not words or not all(w in title for w in words):
                        continue
                    expiry=date(block.get('validThrough'))
                    if expiry and datetime.fromisoformat(expiry)<datetime.now(UTC):
                        j.update(verification='Closed',verification_evidence='Application destination JobPosting validThrough has passed: '+expiry)
                        return j
                    if not j.get('direct') and date(block.get('datePosted')) and not (j.get('himalayas_guid') and urlparse(resolved).hostname=='himalayas.app'):
                        j['source_published']=j.get('published')
                        j.update(published=date(block['datePosted']),date_basis='Application-page JobPosting datePosted')
                if re.search(r'this (?:job|position|role) (?:is |has been )?(?:closed|filled|no longer available)', formtext):
                    j.update(verification='Closed', verification_evidence='Application destination says the vacancy is closed.')
                elif linked_match and application_form(form):
                    j.update(verification='Application form found', application_url=resolved, verification_evidence='Followed Apply link; matching role and application fields found. No submission attempted.')
                else:
                    j.update(verification='Needs review', verification_evidence='Apply destination reached, but a matching live form was not established (possibly JavaScript-rendered).')
            else:
                j.update(verification='Needs review', verification_evidence='Apply control found, but its destination could not be independently verified.')
        else:
            j.update(verification='Needs review', verification_evidence='Page responds, but a role-specific application form could not be established. A live page is not proof of an open job.')
        if j.get('direct') and j['verification'] == 'Needs review':
            is_page=j.get('board_key','').startswith('page:')
            j['verification'] = 'Employer page listed' if is_page else 'Employer board listed'
            j['verification_evidence'] += (' Employer vacancy page is listed; application availability remains unconfirmed.' if is_page else ' Role also appears in the employer public hiring feed; form availability remains unconfirmed.')
        if cached:
            j['verification_evidence'] += ' Page cache is at most 12 hours old.'
        return j
    except HTTPError as e:
        if e.code == 410:
            j.update(verification='Closed', verification_evidence='Application destination returned HTTP 410 Gone.')
        else:
            j.update(verification='Needs review', verification_evidence=f'HTTP {e.code}. A missing or blocked page does not establish closure.')
    except Exception as e:
        j.update(verification='Needs review', verification_evidence='Check failed: ' + str(e)[:220])
    return j


def employer_evidence(website, board_key):
    """Corroborate the board from the configured company site; never certify legitimacy."""
    result = dict(identity_status='Not corroborated', identity_evidence='No employer-site cross-link established. Business legitimacy needs human review.', identity_checked_at=now())
    if not website or not board_key:
        return result
    kind, slug = board_key.split(':',1)
    if kind == 'page':
        return result
    try:
        if not permitted(website):
            result['identity_evidence'] = 'Employer website could not be checked under its robots policy.'
            return result
        text, final, _ = fetch(website,24)
        p=Page();p.feed(text)
        candidates=[(final,p)]
        careers=[urljoin(final,h) for h,label in p.links if re.search(r'careers|join (?:us|the team)|open roles|jobs',label,re.I)]
        careers=list(dict.fromkeys(careers))[:2]
        def matching_link(page, base):
            for href,label in page.links:
                link=urljoin(base,href)
                b=board_from_url(link,'')
                if b and b['kind']==kind and b['slug']==slug:
                    return link
            return None
        for target in careers:
            # A direct hiring-board link is already the cross-reference we need.
            b=board_from_url(target,'')
            if b and b['kind']==kind and b['slug']==slug:
                return dict(result,identity_status='Employer site links board',identity_evidence=f'{final} links to {target}. This corroborates the board relationship, not the legitimacy of the business.')
            if urlparse(target).hostname != urlparse(final).hostname:
                continue
            if permitted(target):
                body, dest, _ = fetch(target,24)
                page=Page();page.feed(body);candidates.append((dest,page))
        for base,page in candidates:
            link=matching_link(page,base)
            if link:
                return dict(result,identity_status='Employer site links board',identity_evidence=f'{base} links to {link}. This corroborates the board relationship, not the legitimacy of the business.')
        result['identity_evidence']='Employer website reached, but no matching public hiring-board link was established. It may be rendered with JavaScript; review manually.'
    except Exception as e:
        result['identity_evidence']='Employer website check failed: '+str(e)[:200]
    return result


def score(j, days):
    j['eligibility'], j['eligibility_evidence'] = geography(j.get('location',''),j['title']+'. '+j.get('description',''))
    if j.get('himalayas_timezones') and 5 not in j['himalayas_timezones']:
        j.update(eligibility='Worth a chance',eligibility_evidence='Himalayas hiring-location UTC offsets omit Pakistan (UTC+5). Willingness to work other hours does not establish residency eligibility.')
    age = age_days(j.get('published'))
    j['age_days'] = age
    j['freshness'] = 'Unknown date' if age is None else 'Future date / review' if age < 0 else 'Recent' if age <= days else 'Older'
    points = {'Product design':35,'Design engineering':38,'Product engineering':30,'Frontend / full stack':20,'Web / visual design':24}[j['category']]
    reasons = [j['category'] + ' title match']
    if j['freshness'] == 'Recent':
        points += max(0, 25 - max(age, 0) // 2); reasons.append('Dated within ' + str(days) + ' days')
    if j.get('direct'):
        points += 12; reasons.append('Employer hiring-system source')
    if j.get('eligibility') in ('Pakistan listed', 'Worldwide advertised'):
        points += 12; reasons.append(j['eligibility'])
    if j.get('verification') == 'Application form found':
        points += 15; reasons.append('Application form found')
    if re.search(r'founding|small team|bootstrapp|seed.stage|early.stage', j.get('description',''), re.I):
        points += 5; reasons.append('Listing describes a small or early-stage team (self-reported)')
    if j.get('verification') == 'Closed':
        points -= 100
    j.update(score=points, match_reasons=reasons)
    return j


def scan():
    with LOCK:
        if STATE['running']:
            return None
        STATE.update(running=True, message='Reading public feeds and employer boards…')
    started = now()
    DATA.mkdir(exist_ok=True)
    lease = DATA / 'scan.lock'
    try:
        if lease.exists() and time.time() - lease.stat().st_mtime > 7200:
            lease.unlink()
        with lease.open('x') as f:
            f.write(started)
    except FileExistsError:
        STATE.update(running=False,message='Another scan is running. Wait for it to finish.')
        return None
    try:
        cfg = config()
        tasks = [(name, lambda n=name: feed_jobs(n, cfg['cache_hours'])) for name in cfg['feeds']]
        tasks += [(b['kind'] + ':' + b['slug'], lambda b=b: board_jobs(b, cfg['cache_hours'])) for b in cfg['boards']]
        all_jobs, logs, successful_boards = [], [], set()
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            work = {pool.submit(fn): name for name, fn in tasks}
            for future in futures.as_completed(work):
                name = work[future]
                try:
                    jobs, cached = future.result()
                    all_jobs.extend(jobs)
                    logs.append((name, now(), 'cached' if cached else 'ok', f'{len(jobs)} relevant remote roles'))
                    if ':' in name and not cached:
                        successful_boards.add(name)
                except SourceNoMatches as e:
                    logs.append((name, now(), 'no_matches', str(e)))
                except SourceNeedsReview as e:
                    all_jobs.extend(e.jobs)
                    logs.append((name, now(), 'manual', str(e)))
                except Exception as e:
                    logs.append((name, now(), 'error', str(e)[:300]))
                STATE['message'] = f'Read {len(logs)}/{len(tasks)} sources · {len(all_jobs)} role matches'
        unique = {}
        for j in all_jobs:
            if any(b.lower() in j['company'].lower().replace(' ', '') for b in cfg['blocked_companies']):
                continue
            existing = unique.get(j['id'])
            if existing:
                refs = existing['sources'] + j['sources']
                if j.get('direct') and not existing.get('direct'):
                    unique[j['id']] = j
                unique[j['id']]['sources'] = list({(x['name'],x['url']):x for x in refs}.values())
            else:
                unique[j['id']] = j
        jobs = sorted([score(j, cfg['max_age_days']) for j in unique.values()], key=lambda j:j['score'], reverse=True)
        eligible = [j for j in jobs if j['freshness'] != 'Older']
        # Rotate limited checks so lower-ranked leads are not starved on every daily scan.
        with connect() as db:
            previous = {r['id']:json.loads(r['payload']).get('checked_at') or '' for r in db.execute('SELECT id,payload FROM jobs')}
        eligible.sort(key=lambda j:(j['category'] not in ('Product design','Design engineering','Web / visual design'),j['eligibility'] not in ('Pakistan listed','Worldwide advertised'),previous.get(j['id'],''), -j['score']))
        to_check = eligible[:cfg['verify_limit']]
        checked = {}
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            for i, j in enumerate(pool.map(verify, to_check), 1):
                checked[j['id']] = j
                STATE['message'] = f'Checking application evidence · {i}/{len(to_check)}'
        identities={}
        companies={(j.get('company_url',''),j.get('board_key','')) for j in checked.values() if j.get('company_url') and j.get('board_key')}
        STATE['message']='Cross-checking employer websites and hiring-board links…'
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            work={pool.submit(employer_evidence,*pair):pair for pair in companies}
            for future in futures.as_completed(work):
                identities[work[future]]=future.result()
        for j in checked.values():
            j.update(identities.get((j.get('company_url',''),j.get('board_key','')),{}))
        with connect() as db:
            seen = set()
            for j in jobs:
                seen.add(j['id'])
                j = score(checked.get(j['id'], j), cfg['max_age_days'])
                old = db.execute('SELECT payload FROM jobs WHERE id=?', (j['id'],)).fetchone()
                if old and j['verification'] == 'Not checked':
                    previous = json.loads(old['payload'])
                    for key in ('verification','verification_evidence','checked_at','application_url'):
                        j[key] = previous.get(key, j[key])
                    if j.get('checked_at') and (datetime.now(UTC)-datetime.fromisoformat(j['checked_at'])).total_seconds() > 86400:
                        j.update(verification='Not checked', verification_evidence='Previous application check is older than 24 hours; recheck required.')
                db.execute('INSERT INTO jobs(id,payload,first_seen,last_seen) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen', (j['id'],json.dumps(j),started,started))
            # Only an authoritative, freshly fetched, successful board snapshot can mark a missing job unlisted.
            for row in db.execute('SELECT id,payload FROM jobs').fetchall():
                j = json.loads(row['payload'])
                if row['id'] not in seen and j.get('board_key') in successful_boards:
                    j.update(verification='No longer listed', verification_evidence='Absent from a successful fresh employer-board snapshot. Check manually before assuming filled.', checked_at=now())
                    db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(j),row['id']))
            db.executemany('INSERT OR REPLACE INTO sources VALUES(?,?,?,?)', logs)
            result = dict(collected=len(all_jobs), unique=len(jobs), checked=len(checked), sources=len(logs), source_errors=sum(x[2]=='error' for x in logs), finished=now())
            db.execute('INSERT INTO runs(started,finished,summary) VALUES(?,?,?)', (started,now(),json.dumps(result)))
        # Expand employer coverage from observed ATS application destinations. No credibility claim.
        known = {(b['kind'],b['slug']) for b in cfg['boards']}
        for j in checked.values():
            b = board_from_url(j.get('application_url',''),j['company'],j.get('company_url',''))
            if b and (b['kind'],b['slug']) not in known and len(known) < 150:
                try:
                    add_employer(j['company'],j.get('company_url') or j['url'],j['application_url'])
                    known.add((b['kind'],b['slug']))
                except Exception:
                    pass
        STATE.update(last_result=result, message=f"Scan complete · {len(jobs)} leads · {len(checked)} application checks")
        return result
    except Exception as e:
        STATE['message'] = 'Scan failed: ' + str(e)
        raise
    finally:
        STATE['running'] = False
        lease.unlink(missing_ok=True)


def opportunity(j):
    """Prioritize application effort without pretending to predict employer responses."""
    current = j.get('freshness') == 'Recent'
    available = j.get('verification') in ('Application form found','Application steps found','Email applications listed')
    portable = j.get('eligibility') in ('Pakistan listed','Worldwide advertised')
    core = j.get('category') in ('Product design','Design engineering','Product engineering')
    onsite=bool(re.search(r'\b(?:location\s+on[ -]site|on[ -]site in|fully on[ -]site)\b',j.get('description',''),re.I))
    concerns = []
    if j.get('eligibility') == 'Restricted / review':
        concerns.append('Location requirement: '+j.get('eligibility_evidence',j.get('location',''))[:210].rstrip('. ')+'. An exception may be needed.')
    elif not portable:
        detail=j.get('eligibility_evidence') or j.get('location') or 'No country information supplied'
        if len(j.get('location',''))>180:
            detail='Employer country list omits Pakistan; worldwide wording elsewhere needs clarification'
        concerns.append('Location to confirm: '+detail[:210].rstrip('. ')+'. Pakistan eligibility is not established.')
    if not available:
        concerns.append('A current application path has not been established.')
    elif j.get('verification') == 'Employer board listed':
        concerns.append('Listed by the employer, but the application form still needs a manual check.')
    if j.get('identity_status') != 'Employer site links board':
        concerns.append('Employer identity has not been independently corroborated.')
    if not core:
        concerns.append('Broader web / visual design scope; check portfolio requirements.' if j.get('category')=='Web / visual design' else 'Broader engineering role; design ownership is not established by the title.')
    signals=[]
    if core:
        signals.append(j['category']+' role')
    if j.get('direct'):
        signals.append('Published hiring-board listing')
    if portable:
        signals.append(j['eligibility'])
    small=re.search(r'founding|small team|bootstrapp|seed.stage|early.stage',j.get('description',''),re.I)
    if small:
        signals.append('Small / early team mentioned in the listing')
    if j.get('verification') == 'Application form found':
        signals.append('Application form found')
    if j.get('verification') == 'Email applications listed':
        signals.append('Direct email application route')
    if onsite:
        tier='archive'
        catch='Description specifies on-site work; this conflicts with the source remote flag.'
    elif j.get('verification') in ('Closed','No longer listed') or j.get('freshness') in ('Older','Future date / review'):
        tier='archive'
        catch='Listing is closed, older than 30 days, or has a future publication date.'
    elif not current:
        tier='review'
        catch='Publication date is unknown. Do not treat this as a recent opening; confirm timing with the employer.'
    elif not available:
        tier='review'
        catch='Check the application destination before preparing an application.'
    elif re.search(r'\bwerkstudent|\bworking[ -]student',j.get('title',''),re.I):
        tier='review'
        catch='Working-student role: enrollment, country and language eligibility need confirmation before treating this as an applicable lead.'
    elif core and portable:
        tier='promising'
        catch=concerns[0] if concerns else 'Review the role against your experience before applying.'
    else:
        tier='stretch'
        catch=concerns[0] if concerns else 'A broader role match; inspect the actual responsibilities.'
    j.update(priority=tier, opportunity_signals=signals, concerns=concerns, main_catch=catch,
             priority_note='Rules based on role, dates, application evidence and location. Local resume evidence adjusts ordering; no response prediction.')
    # Region barriers must outweigh a generic role match. These are sorting points, never probabilities.
    j['attention_rank']=j.get('score',0)+(15 if small else 0)+(15 if core else -15)+(20 if portable else -25)-(25 if j.get('eligibility')=='Restricted / review' else 0)
    return j


def profile_match(j, profile):
    """Transparent local keyword evidence, not an LLM judgement or a probability."""
    if not profile:
        return j
    text=(j['title']+' '+j.get('description','')).lower()
    matches=[]
    for group in profile.get('evidence_groups',[]):
        if any(re.search(r'\b'+re.escape(term.lower())+r'\b',text) for term in group['terms']):
            matches.append(group['label'])
    gaps=[]
    language=re.search(r'english\s+(?:at\s+[\w–—+ -]+\s+)?and\s+(russian|german|french|spanish)|(?:fluent|fluency)\s+in\s+(russian|german|french|spanish)',text)
    if language:
        required=next(x for x in language.groups() if x)
        gaps.append(required.capitalize()+' language proficiency is requested; your resume does not establish it. Confirm this prerequisite before applying.')
    if j['category'] in ('Design engineering','Product engineering','Frontend / full stack') and re.search(r'react|typescript|next\.js|node\.js',text):
        gaps.append('Resume demonstrates AI-assisted shipping, but does not establish production React/TypeScript depth. Show working code for this role.')
    years=re.findall(r'(\d+)\+?\s*(?:years|yrs)(?:\s+of)?\s+(?:professional|relevant|hands.on|product|design|experience)',text)
    if years and max(map(int,years))>profile.get('years_experience',5):
        gaps.append('Advertised experience exceeds the five years stated in your resume.')
    label='Design + code proof needed' if gaps and j['category']!='Product design' else 'Relevant resume evidence' if len(matches)>=2 else 'Partial resume overlap'
    j.update(profile_match=label,fit_evidence=matches[:5],fit_gaps=gaps)
    j['attention_rank']+=min(len(matches),5)*4-len(gaps)*8
    j['opportunity_signals']=(['Resume: '+', '.join(matches[:3])] if matches else [])+j['opportunity_signals']
    if gaps:
        j['concerns']+=gaps
        if language and j['priority'] in ('promising','stretch'):
            j['priority']='stretch'
            j['main_catch']=gaps[0]
        if j['priority']=='promising':
            j['main_catch']=gaps[0]
            if years and max(map(int,years))>=profile.get('years_experience',5)+2:
                j['priority']='stretch'
    return j


def snapshot():
    cfg=config()
    profile_path=DATA/'profile.json'
    profile=json.loads(profile_path.read_text('utf-8')) if profile_path.exists() else None
    observed_path=DATA/'manual-checks.json'
    manual=json.loads(observed_path.read_text('utf-8')) if observed_path.exists() else {}
    with connect() as db:
        jobs = []
        for row in db.execute('SELECT * FROM jobs'):
            raw=json.loads(row['payload'])
            raw['description']=plain(raw.get('description',''))
            observation=manual.get(raw['url']) or manual.get(raw['url'].split('?')[0])
            if observation and raw.get('verification') not in ('Closed','No longer listed'):
                if (datetime.now(UTC)-datetime.fromisoformat(observation['checked_at'])).total_seconds()<86400:
                    raw.update(observation)
            j = score(raw, cfg['max_age_days'])
            if not role(j['title']):
                continue
            j.update(first_seen=row['first_seen'], last_seen=row['last_seen'], state=row['state'], notes=row['notes'])
            # Stale evidence may stay visible but never retains a fresh-check label.
            if j.get('checked_at') and (datetime.now(UTC)-datetime.fromisoformat(j['checked_at'])).total_seconds() > 86400 and j['verification'] not in ('Closed','No longer listed'):
                j.update(verification='Needs recheck', verification_evidence='Application evidence is older than 24 hours. ' + j['verification_evidence'])
            jobs.append(profile_match(opportunity(j),profile))
        sources = [dict(x) for x in db.execute('SELECT * FROM sources ORDER BY name')]
        last = db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    active_sources = set(cfg['feeds']) | {b['kind']+':'+b['slug'] for b in cfg['boards']}
    sources = [s for s in sources if s['name'] in active_sources]
    observed={s['name'] for s in sources}
    for b in cfg['boards']:
        name=b['kind']+':'+b['slug']
        if name not in observed:
            sources.append(dict(name=name,checked=None,status='pending',detail='Added employer; waiting for the next scan'))
    for name in cfg['feeds']:
        if name not in observed:
            sources.append(dict(name=name,checked=None,status='pending',detail='Added public feed; waiting for the next scan'))
    return dict(jobs=sorted(jobs,key=lambda j:j['attention_rank'],reverse=True), sources=sources, scan=dict(STATE), last_run=dict(last) if last else None, token=TOKEN,profile_loaded=bool(profile))


def csv_export():
    out = io.StringIO(newline='')
    fields = ['company','title','category','location','eligibility','published','date_basis','freshness','verification','checked_at','url','application_url','source','state','notes']
    writer = csv.DictWriter(out,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    for j in snapshot()['jobs']:
        # Neutralize spreadsheet formula injection from third-party listing content.
        writer.writerow({k: ("'"+str(j.get(k,'')) if str(j.get(k,'')).startswith(('=','+','-','@','\t','\r')) else j.get(k,'')) for k in fields})
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, code=200, content='application/json; charset=utf-8'):
        raw = data if isinstance(data,bytes) else (json.dumps(data) if content.startswith('application/json') else data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Browser navigation can cancel an in-flight local response.

    def allowed(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.allowed():
            return self.reply({'error':'Local access only'},403)
        path = urlparse(self.path).path
        if path == '/api/jobs':
            return self.reply(snapshot())
        if path == '/api/export':
            return self.reply(csv_export(),content='text/csv; charset=utf-8')
        if path=='/fonts/InterTight-Variable.ttf':
            return self.reply((ROOT/'web/fonts/InterTight-Variable.ttf').read_bytes(),content='font/ttf')
        files = {'/privacy.html':('privacy.html','text/html'), '/':('index.html','text/html'), '/app.js':('app.js','text/javascript'), '/reading.js':('reading.js','text/javascript'), '/account.js':('account.js','text/javascript'), '/account-config.js':('account-config.js','text/javascript'), '/vendor/supabase-2.118.0.js':('vendor/supabase-2.118.0.js','text/javascript'), '/details.js':('details.js','text/javascript'), '/style.css':('style.css','text/css'), '/layout.css':('layout.css','text/css'), '/chips.css':('chips.css','text/css'), '/finish.css':('finish.css','text/css')}
        if path in files:
            filename, content = files[path]
            return self.reply((ROOT/'web'/filename).read_text('utf-8'),content=content+'; charset=utf-8')
        self.reply({'error':'Not found'},404)

    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Scout-Token') != TOKEN:
            return self.reply({'error':'Refresh the local page and retry.'},403)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length < 0 or length > 32000:
                return self.reply({'error':'Request too large'},413)
            body = json.loads(self.rfile.read(length) or '{}')
            if self.path == '/api/scan':
                if STATE['running']:
                    return self.reply({'message':'A scan is already running'},409)
                def run():
                    try: scan()
                    except Exception: pass
                threading.Thread(target=run,daemon=True).start()
                return self.reply({'message':'Scan started'},202)
            if self.path == '/api/job':
                if body.get('state') not in ('new','saved','applied','dismissed'):
                    return self.reply({'error':'Invalid state'},400)
                with connect() as db:
                    db.execute('UPDATE jobs SET state=?,notes=? WHERE id=?',(body['state'],str(body.get('notes',''))[:10000],body['id']))
                return self.reply({'ok':True})
            if self.path == '/api/source':
                board = add_employer(str(body.get('company',''))[:120], str(body['website']), str(body['url']))
                return self.reply({'ok':True,'board':board})
            self.reply({'error':'Not found'},404)
        except (ValueError, KeyError, OSError) as e:
            self.reply({'error':str(e)},400)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',nargs='?',default='serve',choices=['serve','scan','export'])
    p.add_argument('--port',type=int,default=8765)
    args = p.parse_args()
    connect().close()
    if args.command == 'scan':
        print(json.dumps(scan(),indent=2))
    elif args.command == 'export':
        path = DATA/'jobs.csv'; path.write_text(csv_export(),'utf-8-sig'); print(path)
    else:
        server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
        print(f'Job Scout: http://127.0.0.1:{args.port}',flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
