"""Build a public static site. Explicit allowlist: never copy private workspace files."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
import shutil
import scout

PUBLIC_FIELDS='id company title category location description url source sources eligibility eligibility_evidence published date_basis modified salary company_url credibility verification verification_evidence checked_at application_url board_key direct first_seen last_seen age_days freshness score match_reasons identity_status identity_evidence identity_checked_at research_notes application_email'.split()

def validate_account_config(value):
    key=value.get('publishableKey','')
    if key:
        if key.startswith('sb_publishable_'):
            if not re.fullmatch(r'sb_publishable_[A-Za-z0-9_-]+',key): raise ValueError('Invalid publishable key')
        else:
            try:
                payload=key.split('.')[1]
                role=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))['role']
            except Exception:
                raise ValueError('Only a Supabase publishable key or legacy anon key may be published') from None
            if role!='anon': raise ValueError('Secret and service-role keys must never be published')
    if value.get('enabled'):
        if not key or not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co',value.get('url','')): raise ValueError('Use the Free project HTTPS URL and publishable key')
        if value.get('provider') not in ('google','github'): raise ValueError('Unsupported authentication provider')
    return value

def read_account_config():
    text=(scout.ROOT/'web/account-config.js').read_text('utf-8')
    match=re.search(r'window\.SCOUT_ACCOUNT_CONFIG\s*=\s*(\{.*?\});',text,re.S)
    if not match: raise ValueError('Account configuration must be a plain JSON object')
    return validate_account_config(json.loads(match.group(1)))

def version_assets(html, output):
    """Each HTML release points to immutable CSS/JS, preventing mixed cached releases.

    Keep earlier files so an already-open page can finish loading its own release.
    """
    def replace(match):
        name = match.group(2)
        source = output / name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        version = source.stem + '.' + digest + source.suffix
        shutil.copyfile(source, output / version)
        return match.group(1) + './' + version + '"'
    return re.sub(r'((?:src|href)=")\./([a-z-]+\.(?:css|js))"', replace, html)

def source_detail(source):
    detail=source.get('detail','')
    if source['status']=='manual':
        return 'Partial results; later pages could not be fetched.' if detail.startswith('Partial pagination') else 'Page readable; vacancy coverage requires a manual check.'
    if source['status']!='error':
        return detail
    if '429' in detail or 'daily safety cap' in detail:
        return 'Rate limit reached; no paid fallback or access bypass. Retry on a later collection.'
    if '404' in detail:
        return 'Configured hiring endpoint was not found. Employer link needs review.'
    if '502' in detail or '503' in detail or '504' in detail:
        return 'Provider temporarily unavailable. Retried at the next collection.'
    if 'exceeds' in detail:
        return 'Response exceeds the bounded download limit.'
    return 'Could not establish readable vacancy data; check the source manually.'

def collection_report(jobs, previous):
    if not previous or not previous.get('jobs'):
        return dict(comparison_available=False)
    known={j['id'] for j in previous['jobs']}
    added=[j for j in jobs if j['id'] not in known]
    design=[j for j in added if j['category'] in ('Product design','Design engineering','Web / visual design')]
    counts=dict(older_or_closed=0,undated=0,application_unverified=0,other_review=0)
    for j in design:
        if j['priority'] in ('promising','stretch'): continue
        if j['priority']=='archive': counts['older_or_closed']+=1
        elif j.get('freshness')!='Recent': counts['undated']+=1
        elif j.get('verification') not in ('Application form found','Application steps found','Email applications listed'): counts['application_unverified']+=1
        else: counts['other_review']+=1
    return dict(comparison_available=True,previous_collection=previous.get('last_run',{}).get('finished'),added_total=len(added),added_design=len(design),qualified_design=sum(j['priority'] in ('promising','stretch') for j in design),excluded=counts)

def public_snapshot(snapshot,previous=None):
    jobs=[]
    for raw in snapshot['jobs']:
        j={key:raw[key] for key in PUBLIC_FIELDS if key in raw}
        j.update(state='new',notes='')
        # Recompute without private profile, personalized fit, notes or user actions.
        j=scout.opportunity(scout.score(j,30))
        jobs.append(j)
    return dict(jobs=sorted(jobs,key=lambda j:j['attention_rank'],reverse=True),
                sources=[dict(name=s['name'],status=s['status'],checked=s['checked'],detail=source_detail(s)) for s in snapshot['sources']],
                collection_report=collection_report(jobs,previous),
                scan=dict(running=False,message='Published snapshot'),last_run={'finished':snapshot['last_run']['finished']} if snapshot.get('last_run') else None,
                profile_loaded=False,public=True)

def build(output):
    read_account_config()
    output=Path(output).resolve()
    output.relative_to(scout.ROOT.resolve())
    output.mkdir(parents=True,exist_ok=True)
    try:
        previous=json.loads((output/'jobs.json').read_text('utf-8'))
    except (OSError,ValueError):
        previous=None
    for name in ('style.css','layout.css','chips.css','finish.css','app.js','details.js','reading.js','public.js','account-config.js','account.js'):
        shutil.copyfile(scout.ROOT/'web'/name,output/name)
    shutil.copytree(scout.ROOT/'web/fonts',output/'fonts',dirs_exist_ok=True)
    shutil.copyfile(scout.ROOT/'web/privacy.html',output/'privacy.html')
    (output/'vendor').mkdir(exist_ok=True)
    for name in ('supabase-2.118.0.js','supabase-LICENSE.txt','supabase-source.json'):
        shutil.copyfile(scout.ROOT/'web/vendor'/name,output/'vendor'/name)
    html=(scout.ROOT/'web/index.html').read_text('utf-8')
    html=html.replace('<script src="./details.js"','<script src="./public.js" defer></script><script src="./details.js"')
    html=html.replace('href="/api/export"','href="#export"').replace('href="/"','href="./"')
    html=version_assets(html,output)
    (output/'index.html').write_text(html,'utf-8')
    (output/'.nojekyll').write_text('','utf-8')
    data=public_snapshot(scout.snapshot(),previous)
    (output/'jobs.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),'utf-8')
    print(f'Built {len(data["jobs"])} public listings in {output}; private profile and tracking omitted.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='site-preview');args=parser.parse_args();build(args.output)
