import json
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from intake_workspace import IntakeWorkspace, confined_file, register, safe_url

FIXTURES=Path('H:/NEXEN/work/push-20260913/intake-module/fixtures')

class IntakeTests(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'previews').mkdir()
        self.sid='phone-'+'1'*12;self.secret='phone-'+'2'*12
        self.preview=self.root/'previews'/'one.jpg';self.preview.write_bytes(b'jpeg-test')
        self.write('manifest.json',{'summary':{'images':2},'sources':[
            {'source_id':self.sid,'source_name':'tool.png','kind':'image','preview_path':str(self.preview)},
            {'source_id':self.secret,'source_name':'private.png','private_source':True,'preview_path':str(self.preview)}]})
        self.write('software-cards.json',[{'id':'public','source_id':self.sid,'name':'Claude','exact_ocr_quotes':['a quote']},{'id':'secret','source_id':self.secret,'name':'private text'}])
        self.write('prompt-tips.json',[{'id':'tip','source_id':self.sid,'quote':'A tip.'},{'id':'secret-tip','source_id':self.secret,'quote':'Private text.'}])
        self.page=self.root/'page.html';self.page.write_text('<h1>Desk</h1>')
        self.desk=IntakeWorkspace(self.root,self.root/'repos',self.page)
        self.app=FastAPI();register(self.app,workspace=self.desk);self.client=TestClient(self.app)
    def write(self,name,value):(self.root/name).write_text(json.dumps(value),encoding='utf-8')
    def test_inventory_omits_private_content_and_disk_paths(self):
        response=self.client.get('/api/intake-desk');self.assertEqual(response.status_code,200)
        d=response.json();self.assertEqual(len(d['sources']),1);self.assertEqual(d['private_sources_hidden'],1)
        self.assertEqual([t['id'] for t in d['tools']],['public']);self.assertEqual(len(d['prompt_tips']),1)
        self.assertNotIn('private text',response.text.lower());self.assertNotIn(str(self.root),response.text)
        self.assertFalse(d['executed']);self.assertEqual(response.headers['cache-control'],'no-store')
    def test_preview_is_manifest_allowlisted_and_private_denied(self):
        self.assertEqual(self.client.get('/api/intake-desk/preview/'+self.sid).content,b'jpeg-test')
        self.assertEqual(self.client.get('/api/intake-desk/preview/'+self.secret).status_code,404)
        self.assertEqual(self.client.get('/api/intake-desk/preview/phone-'+'3'*12).status_code,404)
    def test_manifest_cannot_serve_outside_preview_root(self):
        outside=self.root/'outside.jpg';outside.write_bytes(b'private')
        self.write('manifest.json',{'sources':[{'source_id':self.sid,'source_name':'x','preview_path':str(outside)}]})
        self.assertEqual(self.client.get('/api/intake-desk/preview/'+self.sid).status_code,404)
    def test_symlink_preview_rejected(self):
        linked=self.root/'previews'/'linked.jpg'
        try:linked.symlink_to(self.preview)
        except OSError:self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError):confined_file(self.root/'previews',linked)
    def test_existing_auth_middleware_still_gates_routes(self):
        from starlette.responses import Response
        @self.app.middleware('http')
        async def gate(request,call_next):
            if request.headers.get('x-test-auth')!='ok':return Response(status_code=401)
            return await call_next(request)
        guarded=TestClient(self.app)
        for path in ['/intake-desk','/api/intake-desk','/api/intake-desk/preview/'+self.sid]:
            self.assertEqual(guarded.get(path).status_code,401)
            self.assertEqual(guarded.get(path,headers={'x-test-auth':'ok'}).status_code,200)
    def test_bad_catalog_returns_controlled_error_without_path_leak(self):
        (self.root/'manifest.json').write_text('{oops')
        result=self.client.get('/api/intake-desk');self.assertEqual(result.status_code,503)
        self.assertNotIn(str(self.root),result.text)
    def test_repository_urls_drop_unsafe_schemes_and_credentials(self):
        self.assertIsNone(safe_url('javascript:alert(1)'));self.assertIsNone(safe_url('https://user:password@example.com'))
        self.assertEqual(safe_url('https://github.com/owner/repo'),'https://github.com/owner/repo')
    def test_no_write_endpoints(self):
        self.assertEqual(self.client.post('/api/intake-desk',json={}).status_code,405)
    def test_actual_catalog_schema_and_reviewed_dedup(self):
        self.write('reviewed-software-cards.json',[{'id':'reviewed','source_id':self.sid,'name':'Claude','url':'https://claude.ai'}])
        repo_root=self.root/'repos';repo_root.mkdir()
        (repo_root/'repositories.json').write_text(json.dumps({'repositories':[{'repo':'owner/repo','url':'https://github.com/owner/repo','verification':'URL extracted'}]}))
        (repo_root/'bookmarks-tools.json').write_text(json.dumps({'bookmarks':[{'name':'Game mod','url':'https://example.com/mod','category':'Game tools and mods'}]}))
        d=self.desk.inventory();self.assertEqual(d['repositories'][0]['name'],'owner/repo');self.assertEqual(d['bookmark_cards'],1)
        self.assertEqual(len(d['tools']),2);self.assertEqual(d['tools'][0]['id'],'reviewed')

if __name__=='__main__':unittest.main()
