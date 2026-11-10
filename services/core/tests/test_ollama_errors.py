from ahirena_core.providers.ollama import _error_text


def test_oom_message_is_honest_and_local():
    msg = _error_text(500, '{"error":"model requires more VRAM than available"}')
    assert "belleğe sığmadı" in msg.lower() or "Model belleğe" in msg
    assert "Uzak modele geçilmez" in msg
    plain = _error_text(404, '{"error":"model not found"}')
    assert "Uzak modele geçilmez" not in plain
    assert "model not found" in plain
