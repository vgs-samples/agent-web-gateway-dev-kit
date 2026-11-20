"""Offline checks: blocked pages must stop checkout and preserve useful diagnostics."""
import json
import tempfile
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from awg_sitecheck import purchase
from awg_sitecheck.browser import PageAccessError, Run


class NavigationFailureTests(unittest.TestCase):
    def test_blocked_product_stops_before_size_selection_and_cleans_up(self):
        events = []
        response = SimpleNamespace(status=403, headers={'vgs-request-id': 'test-request-id'})
        page = Mock()
        page.goto.return_value = response
        page.screenshot.side_effect = lambda **kwargs: events.append('screenshot')
        ctx = Mock()
        ctx.new_page.return_value = page
        session = Mock(id='RS-offline-test')
        session.attrs = {'allowed_hosts': ['shop.example']}
        session.card.return_value = {'number': {'value': 'stand-in-0000'}}
        session.summary.return_value = {'id': session.id}
        session.counters.return_value = {'reveal_count': 0, 'refusal_count': 0}
        session.delete.side_effect = lambda: events.append('session_deleted') or 204
        site = SimpleNamespace(id='hm-us', name='H&M US', recipe='recipes/hm_us.py', adapter=None,
                               urls=['https://shop.example/product'], contact={'size': 'S'},
                               cookie_reject=[], egress=None)
        cfg = SimpleNamespace(path=Path, defaults={'egress': 'soax-us'})

        @contextmanager
        def fake_launch(*args, **kwargs):
            try:
                yield Mock(), ctx
            finally:
                events.append('browser_closed')

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(purchase, 'create', return_value=session), \
                 patch.object(purchase, 'sync_playwright', return_value=nullcontext(Mock())), \
                 patch.object(purchase, 'launch', side_effect=fake_launch), \
                 patch.object(purchase.Run, 'exit_ip', return_value={}), \
                 patch.object(purchase.Run, 'browse') as browse:
                result = purchase.run_purchase(Mock(), cfg, site, folder)
            page.get_by_label.assert_not_called()
            browse.assert_not_called()
            self.assertFalse(result['submitted'])
            self.assertIn('HTTP 403', result['error'])
            self.assertNotIn('Timeout', result['error'])
            self.assertEqual(result['failure']['stage'], 'product_page')
            self.assertEqual(result['failure']['vgs_request_id'], 'test-request-id')
            self.assertEqual(result['failure']['egress_profile'], 'soax-us')
            self.assertEqual(result['failure']['response_origin'], 'unconfirmed')
            self.assertEqual(result['session_deleted'], 204)
            self.assertEqual(events, ['screenshot', 'browser_closed', 'session_deleted'])
            saved = json.loads((Path(folder) / 'result.json').read_text())
            self.assertEqual(saved['failure']['http_status'], 403)

    def test_successful_page_is_allowed_to_continue(self):
        run = Run(Mock(), Mock(), Mock())
        run.require_success(SimpleNamespace(status=200), stage='product_page', url='https://shop.example/product')
        run.page.screenshot.assert_not_called()

    def test_missing_response_stops_instead_of_trying_selectors(self):
        run = Run(Mock(), Mock(), Mock())
        with self.assertRaises(PageAccessError) as caught:
            run.require_success(None, stage='product_page', url='https://shop.example/product')
        self.assertIsNone(caught.exception.details['http_status'])

    def test_diagnostics_strip_credentials_queries_and_fragments(self):
        error = PageAccessError(status=403, stage='product_page',
                                url='https://user:secret@shop.example/product?token=secret#secret')
        self.assertEqual(error.details['url'], 'https://shop.example/product')
        self.assertNotIn('secret', json.dumps(error.details) + str(error))

    def test_screenshot_failure_does_not_hide_the_http_error(self):
        page = Mock()
        page.screenshot.side_effect = OSError('test screenshot failure')
        with tempfile.TemporaryDirectory() as folder:
            run = Run(page, Mock(), Mock(), artifact_dir=folder)
            with self.assertRaises(PageAccessError) as caught:
                run.require_success(SimpleNamespace(status=403, headers={}), stage='product_page',
                                    url='https://shop.example/product')
        self.assertEqual(caught.exception.details['http_status'], 403)
        self.assertEqual(caught.exception.details['screenshot_error'], 'OSError')


if __name__ == '__main__':
    unittest.main()
