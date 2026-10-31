"""Build a public static site. Explicit allowlist: never copy private workspace files."""
import argparse
import json
from pathlib import Path
import shutil
import scout

PUBLIC_FIELDS='id company title category location description url source sources eligibility eligibility_evidence published date_basis modified salary company_url credibility verification verification_evidence checked_at application_url board_key direct first_seen last_seen age_days freshness score match_reasons identity_status identity_evidence identity_checked_at research_notes application_email'.split()

def public_snapshot(snapshot):
    jobs=[]
    for raw in snapshot['jobs']:
        j={key:raw[key] for key in PUBLIC_FIELDS if key in raw}
        j.update(state='new',notes='')
        # Recompute without private profile, personalized fit, notes or user actions.
        j=scout.opportunity(scout.score(j,30))
        jobs.append(j)
    return dict(jobs=sorted(jobs,key=lambda j:j['attention_rank'],reverse=True),
                sources=[dict(name=s['name'],status=s['status'],checked=s['checked'],detail='Could not establish readable vacancy data; check the source manually.' if s['status']=='error' else s['detail']) for s in snapshot['sources']],
                scan=dict(running=False,message='Published snapshot'),last_run={'finished':snapshot['last_run']['finished']} if snapshot.get('last_run') else None,
                profile_loaded=False,public=True)

def build(output):
    output=Path(output).resolve()
    output.relative_to(scout.ROOT.resolve())
    output.mkdir(parents=True,exist_ok=True)
    for name in ('style.css','layout.css','chips.css','finish.css','app.js','details.js','reading.js','public.js'):
        shutil.copyfile(scout.ROOT/'web'/name,output/name)
    shutil.copytree(scout.ROOT/'web/fonts',output/'fonts',dirs_exist_ok=True)
    html=(scout.ROOT/'web/index.html').read_text('utf-8')
    html=html.replace('<script src="./details.js"','<script src="./public.js" defer></script><script src="./details.js"')
    html=html.replace('href="/api/export"','href="#export"').replace('href="/"','href="./"')
    (output/'index.html').write_text(html,'utf-8')
    (output/'.nojekyll').write_text('','utf-8')
    data=public_snapshot(scout.snapshot())
    (output/'jobs.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),'utf-8')
    print(f'Built {len(data["jobs"])} public listings in {output}; private profile and tracking omitted.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='site-preview');args=parser.parse_args();build(args.output)
