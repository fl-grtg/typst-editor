"""B7: _named_lock (renamed from _doc_lock) semantics.

Keys are heterogeneous ("register", "dup:{user}", "upload:{doc_id}") and
case-sensitive: keys differing only in case are DISTINCT locks. Plus a
thread-contention smoke test proving mutual exclusion per key.
"""
import threading

import backend.main as main


def test_rename_applied():
    assert callable(main._named_lock)
    assert not hasattr(main, "_doc_lock")


def test_same_key_same_lock():
    assert main._named_lock("dup:alice") is main._named_lock("dup:alice")
    assert main._named_lock("upload:d_x") is main._named_lock("upload:d_x")


def test_case_only_difference_is_distinct():
    # Case-only test: casing is significant, no normalization anywhere.
    assert main._named_lock("dup:Alice") is not main._named_lock("dup:alice")
    assert main._named_lock("UPLOAD:d_x") is not main._named_lock("upload:d_x")
    assert main._named_lock("Register") is not main._named_lock("register")
    # ...but each spelling is still stable (identity per exact key).
    assert main._named_lock("dup:Alice") is main._named_lock("dup:Alice")
    assert main._named_lock("UPLOAD:d_x") is main._named_lock("UPLOAD:d_x")


def test_distinct_namespaces_distinct():
    assert main._named_lock("register") is not main._named_lock("dup:register")
    assert main._named_lock("dup:d_1") is not main._named_lock("upload:d_1")


def test_contention_serialized_per_key():
    counter = 0
    seen_overlap = False
    inside = 0
    guard = threading.Lock()

    def worker():
        nonlocal counter, seen_overlap, inside
        for _ in range(200):
            with main._named_lock("test:contention"):
                with guard:
                    inside += 1
                    if inside > 1:
                        seen_overlap = True
                counter += 1
                with guard:
                    inside -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter == 8 * 200
    assert not seen_overlap


def test_different_keys_do_not_block_each_other():
    # Sanity: two keys are independent locks; both workers finish with exact counts.
    counts = {"test:ka": 0, "test:kb": 0}

    def worker(key):
        for _ in range(100):
            with main._named_lock(key):
                counts[key] += 1

    ta = threading.Thread(target=worker, args=("test:ka",))
    tb = threading.Thread(target=worker, args=("test:kb",))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    assert counts == {"test:ka": 100, "test:kb": 100}
