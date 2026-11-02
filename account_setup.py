"""Private localhost connection form. Accepts public project settings only.

The SQL is run by the owner in Supabase's SQL editor. Never accept database
passwords, account passwords, secret keys, or service-role credentials here.
"""
import html
import json
import secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import Request,build_opener,HTTPRedirectHandler
import publish

ROOT=Path(__file__).resolve().parent
PORT=8772
TOKEN=secrets.token_urlsafe(32)
MESSAGE='Create the Free project and run the SQL below before connecting.'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def request(config,path,method='GET',body=None):
    req=Request(config['url']+path,method=method,data=json.dumps(body).encode() if body is not None else None,
                headers={'apikey':config['publishableKey'],'Content-Type':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=20) as response:
        return json.loads(response.read(1_000_000))

def validate_project(config):
    publish.validate_account_config(config)
    health=request(config,'/rest/v1/rpc/scout_schema_health','POST',{})
    if health.get('version')!=1 or health.get('protected') is not True:
        raise ValueError('The account schema and row-level security are not ready. Run the complete SQL script first.')
    for table in ['scout_profiles','scout_activity']:
        try:
            request(config,'/rest/v1/'+table+'?select='+('id' if table=='scout_profiles' else 'user_id')+'&limit=1')
        except HTTPError as e:
            if e.code not in (401,403): raise ValueError('Private account tables could not be verified.') from None
        else:
            raise ValueError('Anonymous reads are allowed on an account table. Connection refused; run the supplied security policies.')
    settings=request(config,'/auth/v1/settings')
    if not settings.get('external',{}).get(config['provider']):
        raise ValueError('Enable the selected sign-in provider in Authentication settings before connecting.')
    if settings.get('disable_signup') is True:
        raise ValueError('New user signup is disabled. Enable it if your friends should create accounts.')
    return True

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def allowed(self): return self.headers.get('Host')==f'127.0.0.1:{PORT}'
    def page(self):
        sql=html.escape((ROOT/'supabase/migrations/001_accounts.sql').read_text('utf-8'))
        data=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Job Scout account setup</title>
<style>body{{font:16px/1.6 system-ui;color:#243c30;max-width:800px;margin:30px auto;padding:20px}}label{{display:block;margin:16px 0}}input:not([type=checkbox]),select,textarea{{width:100%;padding:10px;box-sizing:border-box}}textarea{{height:260px;font:12px/1.5 monospace}}button{{padding:12px 18px;background:#17654f;color:white;border:0;border-radius:6px}}aside{{background:#edf3ed;padding:14px}}small{{display:block}}</style>
<h1>Connect Job Scout accounts</h1><aside role="status">{html.escape(MESSAGE)}</aside>
<ol><li>In your Free Supabase project, open <b>SQL Editor → New query</b>. Copy the entire script below and click Run.</li>
<li>Open <b>Authentication → URL Configuration</b>. Set Site URL and an allowed Redirect URL to <code>https://umarliaquat.github.io/job-scout/</code>.</li>
<li>Enable GitHub or Google under Authentication sign-in providers. Configure its OAuth client there; never put the OAuth client secret in this form or the public app.</li>
<li>Under project API settings or the Connect dialog, copy your Project URL and <b>publishable key</b> (or legacy anon key). Do not use a secret/service-role key.</li></ol>
<details><summary>Database setup SQL</summary><textarea readonly aria-label="Database setup SQL">{sql}</textarea></details>
<form method="post" autocomplete="off"><input type="hidden" name="csrf" value="{TOKEN}"><label>Free project URL<input name="url" type="url" required placeholder="https://your-project.supabase.co"></label><label>Publishable key<input name="key" type="password" required autocomplete="off" placeholder="sb_publishable_…"></label><label>Enabled sign-in provider<select name="provider"><option value="github">GitHub</option><option value="google">Google</option></select></label><label><input name="free" type="checkbox" required> This project belongs to a Free organization. No billing or paid features are enabled.</label><button>Validate security and connect</button></form>
<p>This makes up to four small requests to your approved Free project. Remaining allowance is unknown. It checks the security flag, rejects anonymous access to private tables, and checks the selected sign-in provider. Only the public URL and publishable key are saved to the app configuration.</p></html>'''.encode()
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.allowed(): self.send_error(403);return
        self.page()
    def do_POST(self):
        global MESSAGE
        if not self.allowed() or self.headers.get('Origin') not in (None,f'http://127.0.0.1:{PORT}'):
            self.send_error(403);return
        size=int(self.headers.get('Content-Length','0'))
        if size>20000:self.send_error(413);return
        fields=parse_qs(self.rfile.read(size).decode())
        if not secrets.compare_digest(fields.get('csrf',[''])[0],TOKEN):self.send_error(403);return
        if fields.get('free')!=['on']:self.send_error(400);return
        config=dict(enabled=True,url=fields.get('url',[''])[0].strip().rstrip('/'),publishableKey=fields.get('key',[''])[0].strip(),provider=fields.get('provider',[''])[0])
        try:
            validate_project(config)
            (ROOT/'web/account-config.js').write_text("'use strict';\n// Public project settings only; private keys are forbidden.\nwindow.SCOUT_ACCOUNT_CONFIG="+json.dumps(config,separators=(',',':'))+';\n','utf-8')
            (ROOT/'data').mkdir(exist_ok=True)
            (ROOT/'data/account-connection-check.json').write_text(json.dumps(dict(checked=True,rls_health=True,anonymous_reads_denied=True,provider=config['provider'],billing_enabled=False)),encoding='utf-8')
            MESSAGE='Project security checks passed. The local app configuration is connected; sign-in and cloud isolation still need end-to-end verification before publication.'
        except ValueError as e:MESSAGE=str(e)
        except HTTPError as e:MESSAGE=f'Supabase returned HTTP {e.code}. Check the project URL, publishable key and SQL setup; no credentials were logged.'
        except Exception:MESSAGE='The project could not be reached. Check its status and configuration; no credentials were logged.'
        self.send_response(303);self.send_header('Location','/');self.end_headers()

if __name__=='__main__':
    print(f'Private account setup: http://127.0.0.1:{PORT}/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
