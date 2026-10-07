"""Enable the approved existing private HTTPS Serve route; never print identity."""
import json
import pathlib
import ssl
import subprocess
import urllib.request
import urllib.error

BASE = pathlib.Path(r'F:\NEXEN_GAME\NEXEN_Autonomy_v0.1')
DATA = BASE / 'data'
CONFIG = DATA / 'private-access.json'
TS = r'C:\Program Files\Tailscale\tailscale.exe'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def request(url, headers=None):
    try:
        with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=20) as reply:
            return reply.status, reply.read(32768)
    except urllib.error.HTTPError as error:
        return error.code, error.read(32768)


def serve_state():
    return json.loads(subprocess.run([TS, 'serve', 'status', '--json'], capture_output=True, text=True, check=True, timeout=15).stdout)


def save_config(conf):
    CONFIG.write_text(json.dumps(conf, indent=2), encoding='utf-8')


def main():
    conf = json.loads(CONFIG.read_text(encoding='utf-8'))
    before = serve_state()
    host_key = conf['allowed_host'] + ':443'
    handler = before.get('Web', {}).get(host_key, {}).get('Handlers', {}).get('/', {})
    if handler.get('Proxy') != 'http://127.0.0.1:8770' or any(before.get('AllowFunnel', {}).values()):
        raise RuntimeError('Existing Serve differs from the approved private legacy route')
    (DATA / 'private-access-serve-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    code, body = request('http://127.0.0.1:8788/healthz')
    if code != 200 or json.loads(body).get('status') != 'ok':
        raise RuntimeError('Local health check failed')
    if request('http://127.0.0.1:8788/api/hub')[0] != 401:
        raise RuntimeError('Local knowledge API is not password-locked')
    conf['enabled'] = True
    save_config(conf)
    changed = False
    try:
        headers = {'Host':conf['allowed_host'], 'Tailscale-User-Login':conf['allowed_tailscale_user_login']}
        code, body = request('http://127.0.0.1:8788/api/auth/session', headers)
        session = json.loads(body)
        if code != 200 or session.get('can_setup') is not False or session.get('transport') != 'private_https':
            raise RuntimeError('Private setup guard preflight failed')
        if request('http://127.0.0.1:8788/api/hub', headers)[0] != 401:
            raise RuntimeError('Private knowledge API preflight failed')
        result = subprocess.run([TS, 'serve', '--bg', '--https=443', '--yes', 'http://127.0.0.1:8788'], capture_output=True, text=True, timeout=30)
        (DATA/'private-access-serve-command.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Private Serve configuration command failed')
        changed = True
        after = serve_state()
        (DATA/'private-access-serve-after.json').write_text(json.dumps(after, indent=2), encoding='utf-8')
        if after.get('Web', {}).get(host_key, {}).get('Handlers', {}).get('/', {}).get('Proxy') != 'http://127.0.0.1:8788' or any(after.get('AllowFunnel', {}).values()):
            raise RuntimeError('Private Serve readback failed')
        origin = conf['allowed_origin']
        login_code, _ = request(origin + '/login')
        api_code, _ = request(origin + '/api/hub')
        session_code, body = request(origin + '/api/auth/session')
        remote_session = json.loads(body)
        if login_code != 200 or api_code != 401 or session_code != 200 or remote_session.get('can_setup') is not False or remote_session.get('transport') != 'private_https':
            raise RuntimeError('Live private TLS/login guard validation failed')
        conf.update(status='private_https_password_locked', enabled=True, tls_verified=True)
        save_config(conf)
        receipt = {'status':'private_https_password_locked', 'tls_verified':True, 'login_http':login_code,
            'unauthenticated_knowledge_http':api_code, 'private_first_password_setup_allowed':False,
            'funnel':False, 'firewall_changes':False, 'phone_url_stored_only_in_private_config':True}
        (DATA/'private-access-validation.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt), flush=True)
    except Exception:
        conf.update(enabled=False, status='validation_failed_disabled')
        save_config(conf)
        if changed:
            rollback = subprocess.run([TS, 'serve', '--bg', '--https=443', '--yes', 'http://127.0.0.1:8770'],capture_output=True,text=True,timeout=30)
            (DATA/'private-access-rollback.txt').write_text(rollback.stdout + rollback.stderr,encoding='utf-8')
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'not_enabled', 'error_type':type(error).__name__}),flush=True)
        raise SystemExit(1)
