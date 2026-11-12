"""Actual streamed HTTP responses and bounded collector behavior, without publisher traffic."""
import gzip
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from paper_search_school.adapters.base import SupplementLink
from paper_search_school.engine import supplement_transfer as transfer, supplements
from paper_search_school.browser import watchdog
from paper_search_school.entitlements import UserStoppedBatch


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(watchdog.clear_interrupt)

    def test_stop_before_transfer_does_not_send_any_requests(self):
        request = MagicMock()
        request.get.return_value = SimpleNamespace(status=200, ok=True, headers={},
            chunks=lambda: iter([b'file']), dispose=MagicMock())
        watchdog.interrupted = UserStoppedBatch('stop')
        with TemporaryDirectory() as tmp:
            files = supplements.collect(request, [SupplementLink('https://fixture/1.pdf'),
                        SupplementLink('https://fixture/2.pdf')], Path(tmp), '10.1000/stop')
            self.assertEqual([f['reason'] for f in files], ['batch_stopped', 'batch_stopped'])
        request.get.assert_not_called()

    def test_stop_after_headers_does_not_start_browser_fallback(self):
        refused = SimpleNamespace(status=403, headers={}, dispose=MagicMock())
        def get(*args, **kwargs):
            watchdog.interrupted = UserStoppedBatch('stop')
            return refused
        request = SimpleNamespace(get=get)
        fallback = MagicMock(return_value=(b'file', '1.pdf'))
        with TemporaryDirectory() as tmp:
            files = supplements.collect(request, [SupplementLink('https://fixture/1.pdf')],
                        Path(tmp), '10.1000/stop', download=fallback)
            self.assertEqual(files[0]['reason'], 'batch_stopped')
        fallback.assert_not_called()
        refused.dispose.assert_called_once()

    def test_stop_on_final_read_does_not_publish_partial_work(self):
        def chunks():
            yield b'file'
            watchdog.interrupted = UserStoppedBatch('stop')
        response = SimpleNamespace(status=200, ok=True, headers={}, chunks=chunks, dispose=MagicMock())
        request = MagicMock();request.get.return_value = response
        with TemporaryDirectory() as tmp:
            files = supplements.collect(request, [SupplementLink('https://fixture/1.pdf')],
                        Path(tmp), '10.1000/stop')
            self.assertEqual(files[0]['reason'], 'batch_stopped')
            folder = supplements.supplements_dir(Path(tmp), '10.1000/stop')
            self.assertEqual([p.name for p in folder.iterdir()], ['manifest.json'])
        response.dispose.assert_called_once()

    def test_stop_between_files_keeps_success_and_does_not_request_next_file(self):
        response = SimpleNamespace(status=200, ok=True, headers={},
            chunks=lambda: iter([b'first']), dispose=MagicMock())
        request = MagicMock();request.get.return_value = response
        def progress(saved):
            if saved == 1:
                watchdog.interrupted = UserStoppedBatch('stop')
        with TemporaryDirectory() as tmp:
            files = supplements.collect(request, [SupplementLink('https://fixture/1.pdf'),
                        SupplementLink('https://fixture/2.pdf')], Path(tmp), '10.1000/stop', progress=progress)
            self.assertEqual([f['status'] for f in files], ['saved', 'skipped'])
            self.assertEqual(Path(files[0]['file']).read_bytes(), b'first')
            manifest = supplements.supplements_dir(Path(tmp), '10.1000/stop')/'manifest.json'
            self.assertEqual(json.loads(manifest.read_text())['files'], files)
        request.get.assert_called_once()

    def test_browser_fallback_copies_owned_temp_file_without_loading_it_into_memory(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / 'browser.part'
            source.write_bytes(b'fixture attachment')
            refused = SimpleNamespace(status=403, headers={}, dispose=MagicMock())
            request = MagicMock();request.get.return_value = refused
            files = supplements.collect(request, [SupplementLink('https://fixture/S1.pdf')], Path(tmp)/'output',
                         '10.1000/fallback', download=lambda url:(source, 'original.pdf'))
            self.assertEqual(files[0]['status'], 'saved')
            self.assertEqual(Path(files[0]['file']).read_bytes(), b'fixture attachment')
            self.assertFalse(source.exists())
            refused.dispose.assert_called_once()

    def test_real_http_cookie_scope_redirect_compression_and_chunked_writes(self):
        body = b'%PDF attachment\n' + b'x' * (2 * 1024 * 1024)
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append((self.path, self.headers.get('Cookie', ''), self.headers.get('User-Agent')))
                if self.path == '/redirect':
                    self.send_response(302);self.send_header('Location', '/files/data.pdf');self.end_headers();return
                data = gzip.compress(body) if self.path.endswith('gzip.pdf') else body
                self.send_response(200);self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Length', str(len(data)))
                if self.path.endswith('gzip.pdf'):self.send_header('Content-Encoding', 'gzip')
                self.end_headers();self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        page = SimpleNamespace(url=url+'/article', evaluate=lambda s:'Fixture Browser',
             context=SimpleNamespace(cookies=lambda:[
                 {'name':'session','value':'fixture','domain':'127.0.0.1','path':'/files','secure':False},
                 {'name':'other','value':'secret','domain':'other.invalid','path':'/','secure':False}]))
        with TemporaryDirectory() as tmp, transfer.browser_request(page, {}) as request:
            files = supplements.collect(request,[SupplementLink(url+'/redirect'), SupplementLink(url+'/files/gzip.pdf')],Path(tmp),'10.1000/stream')
            self.assertEqual([f['status'] for f in files], ['saved','saved'])
            for f in files:self.assertEqual(Path(f['file']).read_bytes(), body)
        self.assertEqual(seen[0][1], '')
        self.assertEqual(seen[1][1], 'session=fixture')
        self.assertTrue(all('other=' not in row[1] for row in seen))
        self.assertEqual(seen[1][2], 'Fixture Browser')

    def test_progressing_transfer_can_exceed_old_total_budget_then_continue(self):
        now = [0]
        def chunks():
            for _ in range(4):now[0] += 70;yield b'chunk'
        first = SimpleNamespace(status=200,ok=True,headers={},chunks=chunks,dispose=MagicMock())
        second = SimpleNamespace(status=200,ok=True,headers={},chunks=lambda:iter([b'next']),dispose=MagicMock())
        request=MagicMock();request.get.side_effect=[first,second]
        with TemporaryDirectory() as tmp:
            files=supplements.collect(request,[SupplementLink('https://fixture/1.pdf'),SupplementLink('https://fixture/2.pdf')],Path(tmp),'10.1000/stream',clock=lambda:now[0])
            self.assertEqual([f['status'] for f in files],['saved','saved'])
            self.assertEqual(Path(files[0]['file']).read_bytes(),b'chunk'*4)
        first.dispose.assert_called_once();second.dispose.assert_called_once()

    def test_truncated_transfer_is_not_published_and_next_file_continues(self):
        def chunks():yield b'partial';raise OSError('network failure https://signed.invalid?secret=value')
        failed=SimpleNamespace(status=200,ok=True,headers={'content-length':'100'},chunks=chunks,dispose=MagicMock())
        good=SimpleNamespace(status=200,ok=True,headers={},chunks=lambda:iter([b'complete']),dispose=MagicMock())
        request=MagicMock();request.get.side_effect=[failed,good]
        with TemporaryDirectory() as tmp:
            out=Path(tmp);files=supplements.collect(request,[SupplementLink('https://fixture/1.pdf'),SupplementLink('https://fixture/2.pdf')],out,'10.1000/stream')
            self.assertEqual([f['status'] for f in files],['failed','saved'])
            self.assertNotIn('secret',files[0]['reason'])
            folder=supplements.supplements_dir(out,'10.1000/stream')
            self.assertEqual(sorted(p.name for p in folder.iterdir()),['2.pdf','manifest.json'])
            self.assertEqual(json.loads((folder/'manifest.json').read_text())['files'],files)
        failed.dispose.assert_called_once()

    def test_hard_budget_size_and_user_stop_keep_partial_files_out_of_results(self):
        for reason in ('size','deadline','stop'):
            with self.subTest(reason=reason), TemporaryDirectory() as tmp:
                now=[0]
                def chunks():
                    yield b'abc'
                    if reason=='deadline':now[0]=supplements.MAX_COLLECTION_SEC+1
                    if reason=='stop':watchdog.interrupted=UserStoppedBatch('stop')
                    yield b'def'
                response=SimpleNamespace(status=200,ok=True,headers={},chunks=chunks,dispose=MagicMock())
                request=MagicMock();request.get.return_value=response
                try:
                    with patch.object(supplements,'MAX_FILE_BYTES',4 if reason=='size' else 100):
                        files=supplements.collect(request,[SupplementLink('https://fixture/1.pdf')],Path(tmp),'10.1000/stream',clock=lambda:now[0])
                    self.assertNotEqual(files[0]['status'],'saved')
                    folder=supplements.supplements_dir(Path(tmp),'10.1000/stream')
                    self.assertEqual([p.name for p in folder.iterdir()],['manifest.json'])
                finally:watchdog.interrupted=None
