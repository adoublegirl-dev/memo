from scripts.service_control import listener_pids


def test_listener_pids_only_selects_memo_listening_ports():
    sample = """\
  TCP    127.0.0.1:9120         0.0.0.0:0              LISTENING       101
  TCP    127.0.0.1:9121         0.0.0.0:0              LISTENING       102
  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       103
  TCP    127.0.0.1:9120         127.0.0.1:60000        ESTABLISHED     104
"""
    assert listener_pids(sample) == {101, 102}
