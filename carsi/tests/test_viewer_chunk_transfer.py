import base64
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
from paper_search_carsi.engine.batch import PublisherBatchDownloader


class ViewerChunkTransferTests(unittest.TestCase):
    def transfer(self, body, truncate=False, fail=False, output=None):
        calls=[]
        def evaluate(script, args):
            calls.append(args)
            if isinstance(args,str):return None  # release the retained native bytes
            if fail:raise RuntimeError('viewer navigated')
            part=body[args['offset']:args['offset']+args['length']]
            if truncate:part=part[:-1]
            return 'data:application/pdf;base64,'+base64.b64encode(part).decode()
        page=Mock(evaluate=evaluate)
        result=PublisherBatchDownloader._read_viewer_chunks(page,'fixture',len(body),output=output)
        return result,calls

    def test_large_binary_pdf_is_exact_and_bridge_messages_are_bounded(self):
        body=b'%PDF-'+bytes(range(256))*13000+b'%%EOF'
        result,calls=self.transfer(body)
        self.assertEqual(result,body)
        self.assertEqual(calls[-1],'fixture')
        chunks=calls[:-1]
        self.assertGreater(len(chunks),1)
        self.assertLessEqual(max(c['length'] for c in chunks),1024*1024)
        self.assertEqual(sum(c['length'] for c in chunks),len(body))

    def test_truncated_chunk_or_navigation_releases_data_without_partial_success(self):
        body=b'%PDF-'+b'x'*1200000
        for opts in ({'truncate':True},{'fail':True}):
            with self.subTest(opts=opts):
                result,calls=self.transfer(body,**opts)
                self.assertIsNone(result)
                self.assertEqual(calls[-1],'fixture')

    def test_non_pdf_data_is_rejected(self):
        self.assertIsNone(self.transfer(b'html'+b'x'*1200000)[0])

    def test_file_sink_preserves_bytes_and_removes_partial_output(self):
        body=b'%PDF-'+bytes(range(256))*13000+b'%%EOF'
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'supplement.part'
            result,calls=self.transfer(body,output=output)
            self.assertEqual(result,output)
            self.assertEqual(output.read_bytes(),body)
            self.assertLessEqual(max(c['length'] for c in calls[:-1]),1024*1024)
            result,_=self.transfer(body,output=output,truncate=True)
            self.assertIsNone(result)
            self.assertFalse(output.exists())
