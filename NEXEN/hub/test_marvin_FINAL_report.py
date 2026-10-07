"""The V3 report section the main page shows: read-only, capped, links limited to http(s), missing file degrades."""
import json
import tempfile
import unittest
from pathlib import Path

import marvin_hud as H


class V3ReportSectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, data):
        p = self.tmp / 'V3-REPORT.json'
        p.write_text(json.dumps(data), encoding='utf-8')
        return p

    def test_missing_file_degrades_to_note(self):
        out = H.v3_section(self.tmp / 'nope.json')
        self.assertIn('note', out)
        self.assertNotIn('loop', out)

    def test_normal_report(self):
        out = H.v3_section(self.write({
            'updated': '2026-09-27T19:40:00-07:00', 'revenue_verified_usd': 0, 'money_count': 11,
            'next_action': {'id': 'M-001', 'title': 'Send the $100 Upwork reply', 'step': 'paste it', 'link': 'https://www.upwork.com/x', 'value': '$100'},
            'alerts': [{'level': 'red', 'title': 'Memory: 91%', 'fix': 'close tabs', 'ticket': ''}],
            'loop': {'mode': 'ACTIVE', 'commit_pct': 91.2, 'ram_free_gb': 4.6, 'tickets': {'queued': 76, 'done': 1}, 'done_this_week': 1, 'pc2': 'not linked'},
            'goals': [{'n': 1, 'goal': 'First verified dollar', 'by': 'Oct 4', 'now': '$0 verified'}],
            'agents': [{'agent': 'loop-pc1', 'open': 24, 'done': 0}]}))
        self.assertEqual(out['next_action']['id'], 'M-001')
        self.assertEqual(out['next_action']['link'], 'https://www.upwork.com/x')
        self.assertEqual(out['loop']['tickets'], {'queued': 76, 'done': 1})
        self.assertEqual(out['alerts'][0]['level'], 'red')
        self.assertEqual(out['revenue_verified_usd'], 0)

    def test_hostile_values_are_neutralized(self):
        out = H.v3_section(self.write({
            'next_action': {'id': 'M-9', 'title': 'x' * 5000, 'step': 's', 'link': 'javascript:alert(1)'},
            'alerts': [{'level': '<img onerror=1>', 'title': 't'}] * 50,
            'loop': {'mode': 'ACTIVE', 'commit_pct': 'lots', 'tickets': {'queued': 'many', 'done': 2}},
            'revenue_verified_usd': '1000000'}))
        self.assertEqual(out['next_action']['link'], '')              # only http(s) links survive
        self.assertLessEqual(len(out['next_action']['title']), 160)   # capped
        self.assertEqual(len(out['alerts']), 10)                      # capped count
        self.assertEqual(out['alerts'][0]['level'], 'info')           # unknown level -> info
        self.assertIsNone(out['loop']['commit_pct'])                  # non-numbers dropped
        self.assertEqual(out['loop']['tickets'], {'done': 2})
        self.assertIsNone(out['revenue_verified_usd'])                # a string can't pose as verified revenue

    def test_not_an_object(self):
        self.assertIn('note', H.v3_section(self.write(['a', 'list'])))


if __name__ == '__main__':
    unittest.main()
