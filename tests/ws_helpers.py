from pycrdt import Doc

from backend import sync


def _step1(sv=None):
    if sv is None:
        sv = Doc().get_state()  # server never answers empty b"" (continue) -> valid vector needed
    return sync.blob(sync.write_var(sync.MSG_SYNC), sync.write_var(sync.STEP1),
                     sync.write_var(len(sv)), sv)


def _parse(data):
    t, p = sync.read_var(data, 0)
    st, p = sync.read_var(data, p)
    ln, p = sync.read_var(data, p)
    return t, st, data[p:p + ln]


def _update_msg(doc):
    upd = doc.get_update()
    return sync.blob(sync.write_var(sync.MSG_SYNC), sync.write_var(sync.UPDATE),
                     sync.write_var(len(upd)), upd)
