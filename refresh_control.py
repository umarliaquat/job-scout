"""Free Actions refresh guards. Persist only a public API usage counter, never user data."""
import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PK = timezone(timedelta(hours=5))

def refreshed_today(snapshot, current=None):
    current = current or datetime.now(timezone.utc)
    try:
        finished = datetime.fromisoformat(snapshot['last_run']['finished'])
        return (finished.utcoffset() is not None and finished <= current
                and finished.astimezone(PK).date() == current.astimezone(PK).date())
    except (KeyError, TypeError, ValueError):
        return False

def usage_record(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid public usage counter')
    datetime.strptime(value['date'], '%Y-%m-%d')
    count = value['requests']
    if type(count) is not int or not 0 <= count <= 100:
        raise ValueError('Invalid request count')
    return dict(date=value['date'], requests=count)

def validate(snapshot):
    if not refreshed_today(snapshot) or len(snapshot['jobs']) < 5:
        raise ValueError('No healthy completed collection today; retaining previous publication')
    sources = [s for s in snapshot['sources'] if s['status'] != 'pending']
    good = sum(s['status'] in ('ok', 'cached', 'no_matches') for s in sources)
    if not sources or good < max(1, len(sources) / 2):
        raise ValueError('Most sources failed; retaining previous publication')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['plan', 'restore', 'persist', 'validate'])
    action = parser.parse_args().action
    saved = ROOT / '.refresh-state/himalayas-usage.json'
    runtime = ROOT / 'data/himalayas-usage.json'
    if action == 'plan':
        try:
            snapshot = json.loads((ROOT / 'docs/jobs.json').read_text('utf-8'))
        except (OSError, ValueError):
            snapshot = {}
        value = 'false' if refreshed_today(snapshot) and os.environ.get('FORCE_COLLECTION')!='true' else 'true'
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write('collect=' + value + '\n')
        print('Collect today: ' + value)
    elif action == 'validate':
        import scout
        validate(scout.snapshot())
    else:
        source, destination = (saved, runtime) if action == 'restore' else (runtime, saved)
        if source.exists():
            record = usage_record(json.loads(source.read_text('utf-8')))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(record) + '\n', 'utf-8')
        if action=='restore':
            # Ephemeral runners must not erase existing public jobs when a source
            # temporarily fails. Seed only the sanitized public collection.
            import scout
            try:
                previous=json.loads((ROOT/'docs/jobs.json').read_text('utf-8'))
            except (OSError,ValueError):
                previous={}
            with scout.connect() as db:
                for j in previous.get('jobs',[]):
                    db.execute('INSERT OR IGNORE INTO jobs(id,payload,first_seen,last_seen) VALUES(?,?,?,?)',
                               (j['id'],json.dumps(j),j.get('first_seen') or scout.now(),j.get('last_seen') or scout.now()))
            # Earlier deployments did not persist their counter. On a same-day
            # recovery reserve the full cap rather than assuming zero use.
            finished=previous.get('last_run',{}).get('finished')
            if not runtime.exists() and finished and datetime.fromisoformat(finished).astimezone(timezone.utc).date()==datetime.now(timezone.utc).date():
                runtime.parent.mkdir(parents=True,exist_ok=True)
                runtime.write_text(json.dumps(dict(date=datetime.now(timezone.utc).date().isoformat(),requests=80))+'\n','utf-8')

if __name__ == '__main__':
    main()
