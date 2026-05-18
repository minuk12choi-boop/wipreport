from django.test import SimpleTestCase

from .services import build_lot_type_breakdown, build_summary_card_issue_comments, build_wip_issue_summary_rows


class SummaryIssueLogicTests(SimpleTestCase):
    def test_build_lot_type_breakdown(self):
        rows = [
            {'status': 'WAIT', 'cur_qty': 10, 'lot_id': 'L1', 'lot_type': 'PP'},
            {'status': 'HOLD', 'cur_qty': 20, 'lot_id': 'L2', 'lot_type': 'PP'},
            {'status': 'WAIT(진행불가)', 'cur_qty': 15, 'lot_id': 'L3', 'lot_type': 'PG'},
            {'status': 'RUN', 'cur_qty': 99, 'lot_id': 'L4', 'lot_type': 'PG'},
        ]
        result = build_lot_type_breakdown(rows)
        self.assertEqual(result[0]['lot_type'], 'PP')
        self.assertEqual(result[0]['total'], 30)
        self.assertEqual(result[1]['lot_type'], 'PG')
        self.assertEqual(result[1]['blocked'], 15)

    def test_build_issue_comment_contains_korean_risk_text(self):
        rows = [
            {'status': 'WAIT', 'cur_qty': 10, 'lot_id': 'L1', 'lot_type': 'PP', 'proc_id': 'P1', 'layer_id': 'L1', 'step_seq': 'S1', 'step_desc': 'DESC', 'eqpgroup': 'E1'},
            {'status': 'WAIT(진행불가)', 'cur_qty': 20, 'lot_id': 'L2', 'lot_type': 'PP', 'proc_id': 'P1', 'layer_id': 'L1', 'step_seq': 'S1', 'step_desc': 'DESC', 'eqpgroup_cham': 'E1C'},
        ]
        issue_rows = build_wip_issue_summary_rows(rows)
        lot_types = build_lot_type_breakdown(rows)
        lines = build_summary_card_issue_comments(issue_rows, lot_types, ['PP'])
        self.assertEqual(len(lines), 3)
        self.assertIn('진행 차단 가능성', lines[0])
        self.assertIn('선택 lot_type(PP)', lines[2])
