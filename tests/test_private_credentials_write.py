"""Windows readers/scanners can briefly deny replacement of a private token file."""
import json
import pytest
from integrations.chatgpt import auth


def test_private_write_retries_a_transient_windows_replace_denial(tmp_path,monkeypatch):
    target=tmp_path/"credentials.json"
    target.write_text('{"value":"old"}')
    replace=auth.os.replace
    attempts=[]
    def temporarily_locked(source,destination):
        attempts.append(True)
        if len(attempts) == 1:
            error=PermissionError("Synthetic sharing denial")
            error.winerror=5
            raise error
        return replace(source,destination)
    monkeypatch.setattr(auth.os,"replace",temporarily_locked)
    monkeypatch.setattr(auth.time,"sleep",lambda _:None)
    auth._write_private(target,{"value":"new"})
    assert json.loads(target.read_text()) == {"value":"new"} and len(attempts) == 2
    assert not list(tmp_path.glob(".credentials.json.*"))


def test_private_write_preserves_the_old_file_on_permanent_denial(tmp_path,monkeypatch):
    target=tmp_path/"credentials.json"
    target.write_text('{"value":"old"}')
    attempts=[]
    def denied(*_):
        attempts.append(True)
        error=PermissionError("Synthetic permanent denial")
        error.winerror=5
        raise error
    monkeypatch.setattr(auth.os,"replace",denied)
    monkeypatch.setattr(auth.time,"sleep",lambda _:None)
    with pytest.raises(PermissionError): auth._write_private(target,{"value":"new"})
    assert json.loads(target.read_text()) == {"value":"old"} and len(attempts) == 4
    assert not list(tmp_path.glob(".credentials.json.*"))
