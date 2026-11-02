"""Publish a small credential-free status document on a separate public branch."""
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
BRANCH='scout-status'

def git(*args,data=None):
    # mktree paths must be LF-terminated, including on Windows. Text-mode stdin
    # translates to CRLF and would create a filename with a trailing CR.
    raw=subprocess.check_output(['git',*args],cwd=ROOT,input=data.encode('utf-8') if data is not None else None)
    return raw.decode('utf-8').strip()

def status_record(phase,env,snapshot):
    reason=env.get('SEARCH_REASON','')
    if phase=='finished':
        phase='failed' if env.get('SEARCH_OUTCOME')!='success' else ('completed' if env.get('SEARCH_COLLECTED')=='true' else 'skipped')
    repo=env.get('GITHUB_REPOSITORY','umarliaquat/job-scout')
    record=dict(schema=1,phase=phase,updated_at=datetime.now(timezone.utc).isoformat(),
                reason=reason if reason in ('requested','cooldown','daily_limit','already_today') else '',
                last_collection=snapshot.get('last_run',{}).get('finished'),
                next_allowed=env.get('SEARCH_NEXT_ALLOWED') or None,
                run_url=f'https://github.com/{repo}/actions/runs/{env["GITHUB_RUN_ID"]}' if env.get('GITHUB_RUN_ID') else None)
    return record

def publish(record):
    # Git plumbing leaves the collector's main checkout and staged files intact.
    refs=git('ls-remote','origin','refs/heads/'+BRANCH)
    parent=[]
    if refs:
        git('fetch','--no-tags','origin',BRANCH)
        parent=['-p',git('rev-parse','FETCH_HEAD')]
    blob=git('hash-object','-w','--stdin',data=json.dumps(record,separators=(',',':'))+'\n')
    tree=git('mktree',data=f'100644 blob {blob}\tsearch-status.json\n')
    commit=git('-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit-tree',tree,*parent,data='Update public search status\n')
    git('push','origin',commit+':refs/heads/'+BRANCH)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['running','publishing','finished','completed']);phase=parser.parse_args().phase
    snapshot=json.loads((ROOT/'docs/jobs.json').read_text('utf-8'))
    publish(status_record(phase,os.environ,snapshot))
