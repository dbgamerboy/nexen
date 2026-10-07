"""HUD route/state fixture checks; no live probes, models, reload or DB edits."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
from fastapi import HTTPException

BASE=Path(r"H:\NEXEN\handoffs\swarm-execution-20261005\marvin-feed")
spec=importlib.util.spec_from_file_location("_staged_marvin_hud",BASE/"marvin_hud.candidate.py")
hud=importlib.util.module_from_spec(spec);sys.modules[spec.name]=hud;spec.loader.exec_module(hud)


class App:
    def __init__(self):self.state=types.SimpleNamespace();self.routes={}
    def get(self,path,**kwargs):
        def decorate(fn):self.routes[("GET",path)]=fn;return fn
        return decorate
    def post(self,path,**kwargs):
        def decorate(fn):self.routes[("POST",path)]=fn;return fn
        return decorate


class HudTests(unittest.TestCase):
    def setUp(self):
        self.auth=[]
        def validate(request,**kwargs):
            self.auth.append(request)
            if request=="locked":raise HTTPException(403,"locked fixture")
        control=types.ModuleType("pc_control");control.validate_request=validate
        self.patch=mock.patch.dict(sys.modules,{"pc_control":control});self.patch.start()
        self.app=App();hud.register(self.app,None)
    def tearDown(self):self.patch.stop()
    def test_new_routes_preserve_existing_owner_validation(self):
        for route,args in (("/api/marvin/swarm",("locked",)),("/api/marvin/swarm/image/{image_sha}",("a"*64,"locked"))):
            with self.assertRaises(HTTPException) as caught:self.app.routes[("GET",route)](*args)
            self.assertEqual(caught.exception.status_code,403)
        self.assertEqual(len(self.auth),2)
    def test_feed_route_returns_bounded_reader_data(self):
        report={"status":"ready","roles":[{"id":"core-backend","task_id":315,"state":"running"}]}
        with mock.patch.object(hud,"read_swarm_report",return_value=report) as reader:
            self.assertEqual(self.app.routes[("GET","/api/marvin/swarm")]("owner"),report)
            reader.assert_called_once()
    def test_image_route_serves_only_verified_bytes_with_nosniff(self):
        with mock.patch.object(hud,"read_screenshot",return_value=(b'fixture-bytes',"image/png")):
            response=self.app.routes[("GET","/api/marvin/swarm/image/{image_sha}")]("a"*64,"owner")
        self.assertEqual(response.body,b'fixture-bytes');self.assertEqual(response.media_type,"image/png")
        self.assertEqual(response.headers["cache-control"],"no-store");self.assertEqual(response.headers["x-content-type-options"],"nosniff")
    def test_missing_or_changed_image_returns_404(self):
        with mock.patch.object(hud,"read_screenshot",side_effect=FileNotFoundError("changed")):
            with self.assertRaises(HTTPException) as caught:self.app.routes[("GET","/api/marvin/swarm/image/{image_sha}")]("a"*64,"owner")
        self.assertEqual(caught.exception.status_code,404)
    def test_skeleton_and_builder_include_swarm_without_probe_execution(self):
        report={"status":"partial","roles":[]}
        with mock.patch.object(hud,"read_swarm_report",return_value=report):
            self.assertEqual(hud.skeleton("fixture")["swarm"],report)
            with mock.patch.object(hud.StateBuilder,"_gather",return_value={}),mock.patch.object(hud,"money_section",return_value={"lanes":[]}),mock.patch.object(hud,"pc2_section",return_value={}),mock.patch.object(hud,"log_section",return_value=([],None)),mock.patch.object(hud,"db_section",return_value=([],[],{},{})),mock.patch.object(hud,"tonight_section",return_value={}),mock.patch.object(hud,"v3_section",return_value={}),mock.patch.object(hud,"posts_section",return_value={}),mock.patch.object(hud,"reels_section",return_value={}):
                self.assertEqual(hud.StateBuilder(None)._build()["swarm"],report)


if __name__=="__main__":unittest.main(verbosity=2)
