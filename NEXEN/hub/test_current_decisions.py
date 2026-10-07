"""Current owner constraints must survive small prompt budgets and old evidence."""
import unittest
from unittest.mock import patch

from memory_bridge import SharedMemory


class CurrentDecisionTests(unittest.TestCase):
    def packet(self, max_chars, exports=()):
        memory = SharedMemory(context_policy=None)
        with patch.object(memory, '_search_exports', return_value=list(exports)), \
             patch.object(memory, '_search_notes', return_value=[]), \
             patch.object(memory, '_search_knowledge', return_value=[]), \
             patch.object(memory, '_search_completions', return_value=[]):
            return memory.build_context('Lumipaw budget money workflow', max_chars=max_chars)

    def test_current_spending_approval_and_revenue_order_survive_minimum_context_budget(self):
        packet = self.packet(2000)
        self.assertIn('blanket $0 new-usage rule is removed', packet['text'])
        self.assertIn('exact MARVIN approval', packet['text'])
        self.assertIn('paid clipping or campaign work', packet['text'])
        self.assertNotIn('The ad test has a $50 daily cap', packet['text'])
        current = {item['id']: item for item in packet['decisions']}
        self.assertIn('budget-zero-spend', current['20260930-spending-via-marvin']['supersedes'])
        self.assertIn('D-2026-09-27-MONEY-82-FIRST-01', current['20260929-revenue-order-clipping-first']['supersedes'])
        self.assertNotIn('budget-zero-spend', current)
        self.assertNotIn('D-2026-09-27-MONEY-82-FIRST-01', current)

    def test_old_budget_remains_cited_evidence_without_becoming_current_authority(self):
        old = {'kind': 'conversation', 'source_id': 'budget-history',
               'role': 'user', 'title': 'Lumipaw historical budget',
               'text': 'Lumipaw ad budget was $50 per day in the older plan.',
               'ts': '2026-09-09T00:00:00Z', 'provenance': []}
        packet = self.packet(6000, [old])
        self.assertIn('exact MARVIN approval', packet['text'])
        self.assertIn('blanket $0 new-usage rule is removed', packet['text'])
        self.assertIn('ARCHIVED EVIDENCE', packet['text'])
        self.assertIn('Lumipaw ad budget was $50', packet['text'])
        self.assertEqual(packet['citations'][0]['source_id'], 'budget-history')

    def test_live_runtime_replaces_stale_f_runtime_without_claiming_all_cutovers(self):
        packet = self.packet(6000)
        current = {item['id']: item for item in packet['decisions']}
        runtime = current['20260926-nexen-core-on-h']
        self.assertIn('H:/NEXEN/v1/app', runtime['selected'])
        self.assertIn('n8n on port 5678 still uses F:', runtime['selected'])
        self.assertIn('architecture-v1-current', runtime['supersedes'])
        self.assertNotIn('architecture-v1-current', current)
        self.assertNotIn('live app and indexes stay on F:', packet['text'])
        self.assertIn('Keep writes to the failing F: drive small', current['storage-h-models']['selected'])
        self.assertIn('required control/session-log entries', current['storage-h-models']['selected'])


if __name__ == '__main__':
    unittest.main()
