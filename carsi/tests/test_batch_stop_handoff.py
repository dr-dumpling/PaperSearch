"""Stop at the last attachment save and between backend processes, without data loss."""
import json
import time
from unittest.mock import Mock

import pytest

from paper_search_carsi import entitlements as ent, progress_reporter as progress, server


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('CARSI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('CARSI_PROGRESS_BAR', '0')
    monkeypatch.setattr(progress, 'ensure_progress_bar', lambda *a, **k: None)
    with progress.tracked_download('10.1000/first', batch=progress.BatchContext('batch-a', 1, 2)):
        yield progress.read_state()['run_id']


def test_stop_survives_focus_request_and_doi_handoff(run):
    ent.request_action('10.1000/first', ent.STOP_BATCH, run)
    ent.request_action('10.1000/first', ent.SHOW_BROWSER, run)
    for doi in ('10.1000/first', '10.1000/next'):
        with pytest.raises(ent.UserStoppedBatch):
            ent.apply_user_decision(doi, '', time.time() + 1)
    assert ent.batch_stop_requested()


def test_old_run_stop_cannot_cancel_a_new_batch(run):
    ent.request_action('10.1000/first', ent.STOP_BATCH, run)
    with progress.tracked_download('10.1000/first', batch=progress.BatchContext('batch-b', 1, 2)):
        assert not ent.batch_stop_requested()
        assert ent.take_action('10.1000/first', 0) is None


@pytest.mark.parametrize('supplements', ['with', 'only', None])
def test_stop_at_last_save_preserves_files_and_prevents_next_download(run, tmp_path, monkeypatch, supplements):
    main = tmp_path / 'main.pdf'
    extra = tmp_path / 'extra.txt'

    def download(*args, **kwargs):
        main.write_bytes(b'%PDF-saved')
        extra.write_bytes(b'already saved attachment')
        ent.request_action('10.1000/first', ent.STOP_BATCH, run)
        return {'success': True, 'file': str(main), 'artifacts': {'state': 'pdf_response_captured'},
                **({'supplements': [{'status': 'saved', 'file': str(extra)}]} if supplements else {})}

    fn = Mock(side_effect=download)
    monkeypatch.setattr(server, 'download', fn)
    first = json.loads(server.carsi_download('10.1000/first', str(tmp_path), supplements=supplements,
                                            batch_id='batch-a', batch_index=1, batch_total=2))
    assert first['success'] and first['artifacts']['state'] == 'batch_stopped'
    assert main.read_bytes() == b'%PDF-saved'
    assert extra.read_bytes() == b'already saved attachment'
    if supplements:
        assert first['supplements'][0]['status'] == 'saved'
        assert first['supplements'][-1]['reason'] == 'batch_stopped'
    next_item = json.loads(server.carsi_download('10.1000/next', str(tmp_path), supplements=supplements,
                                                batch_id='batch-a', batch_index=2, batch_total=2))
    assert next_item['error_type'] == 'batch_stopped'
    fn.assert_called_once()
