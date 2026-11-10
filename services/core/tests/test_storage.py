from pathlib import Path
from unittest.mock import patch

from ahirena_core.storage import StorageError, disk_status, require_space


def test_disk_status_ok(tmp_path: Path):
    st = disk_status(tmp_path)
    assert st["free_bytes"] > 0
    assert "free_mib" in st
    assert st["ok"] is True


def test_require_space_rejects_low_disk(tmp_path: Path):
    fake = {"path": str(tmp_path), "total_bytes": 100, "used_bytes": 99, "free_bytes": 1, "free_mib": 0.0, "min_free_bytes": 50, "ok": False}
    with patch("ahirena_core.storage.disk_status", return_value=fake):
        try:
            require_space(tmp_path)
            assert False, "düşük disk kabul edilmemeli"
        except StorageError as e:
            assert "Disk" in str(e)
            assert "Uzak modele geçilmez" in str(e)
