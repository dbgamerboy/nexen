import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import zlib
import marvin_swarm_feed as m

OWNED = m.ROOT / "fixtures"


def png(red=240):
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",2,2,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"\0"+bytes([red,20,35])*2+b"\0"+bytes([red,20,35])*2))+chunk(b"IEND",b"")


class FeedTests(unittest.TestCase):
    def setUp(self):
        OWNED.mkdir(parents=True,exist_ok=True)
        self.base=Path(tempfile.mkdtemp(prefix="feed-",dir=OWNED))
        self.roster=self.base/"roles.json"
        self.roster.write_bytes(m.ROSTER.read_bytes())
        self.config=m.FeedConfig(self.base/"SWARM-REPORT.json",self.roster,(self.base,),self.base/"bus")
        self.feed=m.SwarmFeed(self.config)
        self.evidence=self.base/"evidence.json";self.evidence.write_text('{"fixture":"actual local file I/O"}')
        self.image=self.base/"NEXEN-task-fixture.png";self.image.write_bytes(png())
    def tearDown(self):
        if self.base.resolve().parent!=OWNED.resolve():raise RuntimeError("unsafe fixture cleanup")
        for p in self.base.rglob("*"):
            if p.is_symlink():p.unlink()
            elif getattr(p,"is_junction",lambda:False)():p.rmdir()
        shutil.rmtree(self.base)
    def emit(self,**changes):
        values=dict(task_id=318,worker="marvin-interface",state="running",summary="Actual fixture step",progress=25,evidence_paths=[self.evidence],screenshot_path=self.image)
        values.update(changes);return self.feed.emit(**values)
    def test_missing_feed_still_shows_twelve_defined_held_roles(self):
        result=self.feed.read();self.assertEqual(len(result["roles"]),12)
        self.assertTrue(all(x["state"]=="held" for x in result["roles"]))
        self.assertFalse(result["process_liveness_verified"])
    def test_actual_file_image_emit_readback_and_hash_verified_content(self):
        result=self.emit();report=self.feed.read()
        self.assertEqual(len(report["roles"]),12)
        active=next(x for x in report["roles"] if x["id"]=="marvin-interface")
        self.assertEqual(active["state"],"running");self.assertEqual(active["task_id"],318)
        sha=hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.assertEqual(active["screenshot"]["sha256"],sha)
        self.assertEqual(result["report_sha256"],hashlib.sha256(self.config.report_path.read_bytes()).hexdigest())
        content,mime=self.feed.image(sha);self.assertEqual(content,self.image.read_bytes());self.assertEqual(mime,"image/png")
    def test_secret_network_and_contact_redaction_before_storage(self):
        self.emit(summary="password=FAKE_NEVER_STORE token=OTHER_FAKE_NEVER_STORE Authorization: Bearer FAKE_BEARER_NEVER_STORE admin@example.org 192.168.1.9 DESKTOP-TEST12")
        text=self.config.report_path.read_text()
        for forbidden in ("FAKE_NEVER_STORE","OTHER_FAKE_NEVER_STORE","FAKE_BEARER_NEVER_STORE","admin@example.org","192.168.1.9","DESKTOP-TEST12"):self.assertNotIn(forbidden,text)
    def test_bad_task_role_state_progress_rejected(self):
        for change in ({"task_id":True},{"task_id":0},{"worker":"fake-agent"},{"state":"SUCCESS"},{"progress":True},{"progress":float("nan")},{"progress":101}):
            with self.subTest(change=change):
                with self.assertRaises((ValueError,TypeError)):self.emit(**change)
        self.assertFalse(self.config.report_path.exists())
    def test_invalid_evidence_list_is_rejected(self):
        with self.assertRaises(ValueError):self.emit(evidence_paths="one")
        with self.assertRaises(ValueError):self.emit(evidence_paths=[self.evidence]*9)
    def test_unaccepted_completion_cannot_be_written(self):
        with self.assertRaises((ValueError,KeyError)):self.emit(state="completed",progress=100)
        self.assertFalse(self.config.report_path.exists())
    def accepted(self):
        receipt=self.base/"accepted.json"
        receipt.write_text(json.dumps(dict(schema="nexen.accepted-task-receipt.v1",task_id=318,worker="marvin-interface",accepted=True,status="accepted",evidence=[self.feed.reference(self.evidence)])))
        return receipt
    def test_completed_requires_accepted_matching_evidence_receipt(self):
        self.emit(state="completed",progress=100,accepted_receipt=self.accepted())
        role=next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")
        self.assertEqual(role["state"],"completed");self.assertFalse(role["canonical_completion"])
    def test_changed_completion_receipt_withdraws_completed_state(self):
        receipt=self.accepted();self.emit(state="completed",progress=100,accepted_receipt=receipt)
        receipt.write_text('{}')
        role=next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")
        self.assertEqual(role["state"],"held")
    def test_changed_accepted_evidence_withdraws_completed_state(self):
        self.emit(state="completed",progress=100,accepted_receipt=self.accepted())
        self.evidence.write_text('changed')
        role=next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")
        self.assertEqual(role["state"],"held")
    def test_old_running_report_becomes_held_stale(self):
        self.emit();data=json.loads(self.config.report_path.read_text())
        data["entries"][0]["reported_at"]="2020-01-01T00:00:00+00:00";self.config.report_path.write_text(json.dumps(data))
        role=next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")
        self.assertEqual(role["state"],"held");self.assertIn("last_running_report_stale",role["warnings"])
    def test_changed_or_missing_screenshot_has_no_thumbnail(self):
        self.emit();self.image.write_bytes(png(100))
        role=next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")
        self.assertIsNone(role["screenshot"])
        self.image.unlink();self.assertIsNone(next(x for x in self.feed.read()["roles"] if x["id"]=="marvin-interface")["screenshot"])
    def test_image_bytes_changed_between_validation_and_serve_is_rejected(self):
        self.emit();sha=hashlib.sha256(self.image.read_bytes()).hexdigest();original=self.feed.reference
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs);self.image.write_bytes(png(101));return result
        with mock.patch.object(self.feed,"reference",side_effect=mutate):
            with self.assertRaisesRegex(ValueError,"changed_after_validation"):self.feed.image(sha)
    def test_path_escape_foreign_path_unc_and_bad_image_id_rejected(self):
        foreign=self.base.parent/"foreign-owned-test.png";foreign.write_bytes(png())
        try:
            for path in (foreign,self.base/".."/"foreign-owned-test.png",r"\\host\share\file.png"):
                with self.assertRaises((ValueError,OSError)):self.feed.reference(path,True)
        finally:foreign.unlink()
        for token in ("../file","a"*63,"A"*64):
            with self.assertRaises(ValueError):self.feed.image(token)
    def test_invalid_png_crc_wrong_extension_and_missing_file_rejected(self):
        self.image.write_bytes(png()[:-1]+b'x')
        with self.assertRaises(ValueError):self.feed.reference(self.image,True)
        fake=self.base/"fake.svg";fake.write_bytes(png())
        with self.assertRaises(ValueError):self.feed.reference(fake,True)
        self.image.unlink()
        with self.assertRaises(OSError):self.feed.reference(self.image,True)
    def test_oversized_image_and_evidence_explicitly_rejected(self):
        self.image.write_bytes(b'x'*(m.MAX_IMAGE+1))
        with self.assertRaises(ValueError):self.feed.reference(self.image,True)
        self.evidence.write_bytes(b'x'*(m.MAX_REFERENCE+1))
        with self.assertRaises(ValueError):self.feed.reference(self.evidence)
    def test_invalid_report_duplicate_keys_nonobject_and_cap_rejected(self):
        for text in ('[]','{"schema":"x","schema":"y"}','not json','x'*(m.MAX_REPORT+1)):
            self.config.report_path.write_text(text)
            with self.assertRaises((ValueError,TypeError)):self.feed.read()
    def test_malformed_existing_feed_is_not_silently_overwritten(self):
        self.config.report_path.write_text('{}');before=self.config.report_path.read_bytes()
        with self.assertRaises(ValueError):self.emit()
        self.assertEqual(self.config.report_path.read_bytes(),before)
    def test_duplicate_role_report_is_rejected(self):
        self.emit();data=json.loads(self.config.report_path.read_text());data["entries"]*=2;self.config.report_path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):self.feed.read()
    def test_writer_conflict_has_no_spin_or_overwrite(self):
        lock=self.base/".swarm-report.lock";lock.write_text('busy')
        start=time.monotonic()
        with self.assertRaisesRegex(RuntimeError,"writer_busy"):self.emit()
        self.assertLess(time.monotonic()-start,1)
    def test_atomic_replace_failure_preserves_old_report(self):
        self.emit();before=self.config.report_path.read_bytes()
        with mock.patch.object(m.os,"replace",side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):self.emit(progress=26)
        self.assertEqual(self.config.report_path.read_bytes(),before)
    def test_bus_option_is_note_only_no_discord_outbox(self):
        result=self.emit(bus_note=True)
        self.assertEqual(result["bus_status"],"note_appended_no_outbox")
        event=json.loads((self.config.bus_path/"events.jsonl").read_text())
        self.assertEqual(event["type"],"note");self.assertFalse((self.config.bus_path/"outbox.jsonl").exists())
    def test_bounded_child_reader_uses_real_fixture_report(self):
        self.emit();result=m._bounded("read",self.config)
        self.assertEqual(len(result["roles"]),12)
        encoded=m._bounded("image",self.config,hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(base64.b64decode(encoded["data"]),self.image.read_bytes())
    def test_public_emit_worker_contract_supports_isolated_fixture_values(self):
        values=dict(task_id=318,worker="marvin-interface",state="running",summary="Bounded public caller fixture",progress=20,evidence_paths=[str(self.evidence)],screenshot_path=str(self.image))
        result=m._bounded("emit",self.config,seconds=4,values=values)
        self.assertTrue(result["event_id"]);self.assertTrue(result["report_sha256"])
    def test_feed_unavailability_keeps_twelve_role_placeholders(self):
        with mock.patch.object(m,"_bounded",return_value=dict(status="unavailable",roles=[])):
            result=m.read_report()
        self.assertEqual(len(result["roles"]),12);self.assertTrue(all(x["state"]=="held" for x in result["roles"]))
    def test_actual_stalled_reader_killed_and_guard_released(self):
        script=self.base/"stall.py";script.write_text("import json,sys,time\nfrom pathlib import Path\nx=json.load(sys.stdin)\nPath(x['config']['report_path']).with_suffix('.started').write_text('entered')\ntime.sleep(4)\n")
        original=m.subprocess.Popen;children=[]
        def stalled(command,**kwargs):
            child=original([str(m.PYTHON),"-I","-B",str(script)],**kwargs);children.append(child);return child
        with mock.patch.object(m.subprocess,"Popen",side_effect=stalled):
            result=m._bounded("read",self.config,seconds=1)
        self.assertEqual(result["status"],"unavailable");self.assertIsNotNone(children[0].poll())
        self.assertTrue(self.config.report_path.with_suffix('.started').exists())
        self.assertTrue(m._GUARD.acquire(blocking=False));m._GUARD.release()
    @unittest.skipUnless(os.name=="nt","native Windows junction")
    def test_native_junction_rejected_without_foreign_image_read(self):
        target=self.base/"outside";target.mkdir();(target/"image.png").write_bytes(png())
        junction=self.base/"linked"
        result=subprocess.run(["cmd","/c","mklink","/J",str(junction),str(target)],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0)
        with self.assertRaises(ValueError):self.feed.reference(junction/"image.png",True)


if __name__=="__main__":unittest.main(verbosity=2)
