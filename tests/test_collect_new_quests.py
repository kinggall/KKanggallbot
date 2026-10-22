import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_new_quests import PAGE, read_source, save, fetch

HTML = '<html><h1>任務</h1><h2 id="New">新任務</h2><table><tr><td>2610 B1</td></tr></table></html>'


class NewQuestCollectionTests(unittest.TestCase):
    def test_save_and_reject_challenge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = save(HTML, root, 'offline_import')
            self.assertEqual((result / 'page.html').read_text(encoding='utf-8'), HTML)
            self.assertIn('2610 B1', (result / 'page.txt').read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):
                save('<html>Access denied</html>', root, 'http')
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_har_only_reads_target_response(self):
        content = {'encoding': 'base64', 'text': base64.b64encode(HTML.encode()).decode()}
        har = {'log': {'entries': [{'request': {'url': PAGE},
               'response': {'status': 200, 'content': content}}]}}
        with patch.object(Path, 'read_text', return_value=json.dumps(har)):
            self.assertEqual(read_source(Path('page.har')), HTML)

    def test_denied_robots_never_fetches_page(self):
        from unittest.mock import Mock
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.text = 'User-agent: *\nDisallow: /'
        with self.assertRaises(ValueError):
            fetch(session)
        self.assertEqual(session.get.call_count, 1)
