"""Fixed provider worker protocol and bounded cancellation; no real provider calls."""
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import supervisor_provider as worker
from test_support import fixture_root


class FakeProcess:
    def __init__(self, *, output, response=None, hang=False):
        self.stdin=io.BytesIO();self.returncode=None if hang else 0
        self.killed=False;self.waits=[]
        if response is not None:
            output.write(response);output.flush()
    def poll(self):return self.returncode
    def kill(self):self.killed=True;self.returncode=-1
    def wait(self,timeout):self.waits.append(timeout);return self.returncode


class ProviderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=fixture_root());self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.payload={'provider':'ollama','model':'fixture','base_url':'http://127.0.0.1:11434','prompt':'PRIVATE FIXTURE'}

    def test_private_payload_never_enters_fixed_argv_and_output_is_returned(self):
        seen={}
        def spawn(argv,**kwargs):
            seen.update(argv=argv,kwargs=kwargs)
            return FakeProcess(output=kwargs['stdout'],response=json.dumps({'ok':True,'text':'fixture result'}).encode())
        self.assertEqual(worker.run_request(self.payload,lambda:False,root=self.root,popen=spawn),'fixture result')
        self.assertEqual(seen['argv'][-1],'--worker')
        self.assertIn('-B',seen['argv'])
        self.assertIn('-I',seen['argv']);self.assertIn('-S',seen['argv'])
        self.assertEqual(Path(seen['argv'][0]),Path(sys._base_executable).resolve())
        # Only a virtual environment has a redirector to bypass; under the system
        # interpreter the base executable is correctly the same file.
        if Path(sys.executable).resolve()!=Path(sys._base_executable).resolve():
            self.assertNotEqual(Path(seen['argv'][0]),Path(sys.executable).resolve())
        self.assertTrue(seen['kwargs']['env']['NEXEN_PROVIDER_PACKAGES'].endswith('site-packages'))
        self.assertNotIn('PRIVATE FIXTURE',' '.join(seen['argv']))
        self.assertTrue(seen['kwargs']['env']['TEMP'].startswith(str(self.root)))
        self.assertEqual(list(self.root.glob('request-*')),[])

    def test_unreadable_worker_output_becomes_the_sanitized_provider_error(self):
        for label,payload in (('non-utf8',b'\xff\xfe\x00raw worker bytes'),
                              ('truncated json',b'{"ok": tr')):
            with self.subTest(response=label):
                def spawn(argv,response=payload,**kwargs):
                    return FakeProcess(output=kwargs['stdout'],response=response)
                with self.assertRaises(worker.ProviderRequestError) as error:
                    worker.run_request(self.payload,lambda:False,root=self.root,popen=spawn)
                self.assertEqual(error.exception.provider_error_class,'InvalidWorkerResponse')
                self.assertNotIn('raw worker bytes',str(error.exception))
                self.assertNotIn('0xff',str(error.exception).lower())
                self.assertNotIn('position',str(error.exception).lower())

    def test_stuck_child_is_killed_only_through_owned_handle_at_hard_deadline(self):
        made=[]
        def spawn(argv,**kwargs):
            process=FakeProcess(output=kwargs['stdout'],hang=True);made.append(process);return process
        with self.assertRaises(worker.ProviderRequestError) as error:
            worker.run_request(self.payload,lambda:False,root=self.root,popen=spawn,max_seconds=.025)
        self.assertEqual(error.exception.provider_error_class,'RequestDeadlineExceeded')
        self.assertTrue(made[0].killed);self.assertEqual(made[0].waits,[5])
        self.assertEqual(list(self.root.glob('request-*')),[])

    def test_stop_signal_cancels_inflight_child_without_another_request(self):
        stop=threading.Event();made=[]
        def spawn(argv,**kwargs):
            process=FakeProcess(output=kwargs['stdout'],hang=True);made.append(process);stop.set();return process
        self.assertIsNone(worker.run_request(self.payload,stop.is_set,root=self.root,popen=spawn))
        self.assertEqual(len(made),1);self.assertTrue(made[0].killed)
        with patch.object(worker.subprocess,'Popen',side_effect=AssertionError('No process')):
            self.assertIsNone(worker.run_request(self.payload,lambda:True,root=self.root,popen=lambda *a,**k:self.fail('No process')))

    def test_request_and_response_limits_fail_without_unbounded_data(self):
        with self.assertRaises(worker.ProviderRequestError) as error:
            worker.run_request({**self.payload,'prompt':'x'*(worker.MAX_INPUT+1)},lambda:False,root=self.root,popen=lambda *a,**k:self.fail('No oversized request'))
        self.assertEqual(error.exception.provider_error_class,'RequestTooLarge')
        def spawn(argv,**kwargs):return FakeProcess(output=kwargs['stdout'],response=b'x'*(worker.MAX_OUTPUT+1))
        with self.assertRaises(worker.ProviderRequestError) as error:
            worker.run_request(self.payload,lambda:False,root=self.root,popen=spawn)
        self.assertEqual(error.exception.provider_error_class,'ResponseTooLarge')

    def test_worker_failure_only_exposes_safe_metadata(self):
        def spawn(argv,**kwargs):return FakeProcess(output=kwargs['stdout'],response=json.dumps({'ok':False,'error_class':'ReadTimeout','http_status':503,'private':'never surfaced'}).encode())
        with self.assertRaises(worker.ProviderRequestError) as error:
            worker.run_request(self.payload,lambda:False,root=self.root,popen=spawn)
        self.assertEqual(error.exception.provider_error_class,'ReadTimeout')
        self.assertEqual(error.exception.status_code,503)
        self.assertNotIn('never surfaced',str(error.exception))

    def test_fixed_dispatch_rejects_unknown_provider_without_requests(self):
        with patch('httpx.post',side_effect=AssertionError('No network')):
            with self.assertRaises(ValueError):worker.provider_text({'provider':'shell','prompt':'anything','model':'anything'})

    def test_ollama_rejects_invalid_endpoints_before_network(self):
        invalid = (
            None, '', 'localhost:11434', '//localhost:11434',
            'ftp://localhost:11434', 'file:///localhost', 'http://example.invalid',
            'http://192.0.2.1', 'http://0.0.0.0', 'http://[::]', 'http://[2001:db8::1]',
            'http://localhost.example.invalid', 'http://127.0.0.1.example.invalid',
            'http://user:password@localhost', 'http://@localhost',
            'http://localhost?token=fixture', 'http://localhost#fragment',
            'http://localhost?', 'http://localhost#',
            'http://localhost:', 'http://localhost:bad', 'http://localhost:65536',
            'http://localhost:0', 'http://[::1', 'http://[::1]extra',
            'http://::1', 'http://[::1%25fixture]', 'http://127.1',
            ' http://localhost', 'http://local\nhost', 'http://localhost/\tpath',
            'http://localhost\\@example.invalid', 'http://localhost/\x00',
        )
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint), patch('httpx.post') as post:
                with self.assertRaisesRegex(ValueError, '^Invalid local endpoint$'):
                    worker.provider_text({**self.payload, 'base_url':endpoint})
                post.assert_not_called()

    def test_ollama_preserves_loopback_endpoint_and_request_normalization(self):
        import httpx
        endpoints = (
            ('http://localhost:11434/', 'http://localhost:11434/api/generate'),
            ('HTTP://LOCALHOST:11434///', 'http://LOCALHOST:11434/api/generate'),
            ('https://127.0.0.1:11434', 'https://127.0.0.1:11434/api/generate'),
            ('http://127.0.0.2:11434/prefix///', 'http://127.0.0.2:11434/prefix/api/generate'),
            ('http://[::1]:11434/', 'http://[::1]:11434/api/generate'),
            ('https://[0:0:0:0:0:0:0:1]/prefix', 'https://[0:0:0:0:0:0:0:1]/prefix/api/generate'),
        )
        for endpoint, expected in endpoints:
            with self.subTest(endpoint=endpoint):
                response = httpx.Response(200, json={'response':'fixture result'}, request=httpx.Request('POST', expected))
                with patch('httpx.post', return_value=response) as post:
                    self.assertEqual(worker.provider_text({**self.payload, 'base_url':endpoint, 'timeout_seconds':15}), 'fixture result')
                args, kwargs = post.call_args
                self.assertEqual(args, (expected,))
                self.assertEqual(kwargs['json'], {'model':'fixture', 'prompt':'PRIVATE FIXTURE', 'stream':False})
                self.assertEqual(kwargs['timeout'].read, 15)
                self.assertEqual(kwargs['timeout'].connect, 5)
                self.assertIs(kwargs.get('trust_env'), False)
                self.assertIs(kwargs.get('follow_redirects'), False)

    def test_ollama_ignores_environment_proxies_with_fake_transport(self):
        import httpx
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'response':'local fixture'})
        environment = {'HTTP_PROXY':'http://proxy.invalid:8080',
                       'HTTPS_PROXY':'http://proxy.invalid:8080',
                       'ALL_PROXY':'http://proxy.invalid:8080', 'NO_PROXY':''}
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(httpx.Client, '_init_transport', return_value=httpx.MockTransport(respond)), \
                patch.object(httpx.Client, '_init_proxy_transport', side_effect=AssertionError('Environment proxy must not be used')):
            self.assertEqual(worker.provider_text(self.payload), 'local fixture')
        self.assertEqual([str(request.url) for request in requests], ['http://127.0.0.1:11434/api/generate'])

    def test_ollama_does_not_follow_redirects_with_fake_transport(self):
        import httpx
        requests = []
        def respond(request):
            requests.append(request)
            if len(requests) > 1:
                self.fail('A redirect must not issue another request')
            return httpx.Response(307, headers={'Location':'https://redirect.invalid/api/generate'})
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(httpx.Client, '_init_transport', return_value=httpx.MockTransport(respond)), \
                patch.object(httpx.Client, '_init_proxy_transport', side_effect=AssertionError('No proxy transport')):
            with self.assertRaises(httpx.HTTPStatusError) as error:
                worker.provider_text(self.payload)
        self.assertEqual(error.exception.response.status_code, 307)
        self.assertEqual(len(requests), 1)

    def test_real_isolated_worker_loads_dependencies_and_rejects_without_network(self):
        with self.assertRaises(worker.ProviderRequestError) as error:
            worker.run_request({**self.payload,'provider':'invalid-fixture'},lambda:False,root=self.root,max_seconds=10)
        self.assertEqual(error.exception.provider_error_class,'ValueError')
        self.assertEqual(list(self.root.glob('request-*')),[])

    @unittest.skipUnless(sys.platform=='win32','Windows redirector regression')
    def test_direct_base_process_is_the_owned_pid_and_kill_reaps_it(self):
        from storage_policy import tool_environment
        base,_=worker.worker_runtime()
        with subprocess.Popen([str(base),'-I','-S','-B','-c',
                              'import os,time; print(os.getpid(), flush=True); time.sleep(60)'],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              cwd=self.root,env=tool_environment(self.root/'pid-profile'),
                              creationflags=subprocess.CREATE_NO_WINDOW) as process:
            try:
                self.assertEqual(int(process.stdout.readline()),process.pid)
            finally:
                process.kill();process.wait(timeout=5)
            self.assertIsNotNone(process.returncode)


if __name__=='__main__':unittest.main()
