"""Qo'ng'iroqdagi ovoz muammosini tekshirish uchun batafsil yozuvlar.

Har bir qo'ng'iroq tugagach, yozuvlar fayli (call-debug.log) egasiga yuboriladi.
.env da CALL_DEBUG=0 qilinsa o'chadi.
"""
import logging

from . import config

log = logging.getLogger(__name__)

LOG_FILE = config.DATA_DIR / "call-debug.log"
ENABLED = config.CALL_DEBUG


def setup_logging() -> None:
    if not ENABLED:
        return
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.DEBUG)
    for name in ("ntgcalls", "webrtc", "pytgcalls"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
        lg.propagate = False   # journal'ni to'ldirib yubormasin
    for name in ("yordamchi.caller", "yordamchi.livecall", __name__):
        logging.getLogger(name).addHandler(handler)


class BindingProxy:
    """NTgCalls obyektini o'rab, qo'ng'iroq parametrlarini yozib boradi."""

    def __init__(self, binding) -> None:
        self._b = binding

    def __getattr__(self, name):
        return getattr(self._b, name)

    def connect_p2p(self, user_id, servers, versions, p2p_allowed, custom_parameters):
        log.info("P2P ulanish: versiyalar=%s p2p_allowed=%s custom=%s", versions, p2p_allowed, custom_parameters)
        for s in servers:
            log.info("  server id=%s %s:%s ipv6=%s stun=%s turn=%s tcp=%s",
                     s.id, s.ipv4, s.port, s.ipv6, s.stun, s.turn, s.tcp)
        return self._b.connect_p2p(user_id, servers, versions, p2p_allowed, custom_parameters)

    def set_stream_sources(self, chat_id, mode, description):
        log.info("Ovoz manbai: mode=%s mic=%s speaker=%s", mode,
                 _desc(getattr(description, "microphone", None)), _desc(getattr(description, "speaker", None)))
        return self._b.set_stream_sources(chat_id, mode, description)


def _desc(d) -> str:
    if d is None:
        return "yo'q"
    return f"{d.media_source} {d.sample_rate}Hz x{d.channel_count} {str(d.input)[:120]}"


def attach(calls) -> None:
    """PyTgCalls ishga tushishidan OLDIN chaqiriladi."""
    if not ENABLED:
        return
    calls._binding = BindingProxy(calls._binding)
    original = calls._handle_connection_changed

    async def connection_changed(chat_id, net_state):
        log.info("Ulanish holati: chat=%s state=%s kind=%s", chat_id, net_state.state,
                 getattr(net_state, "kind", "?"))
        await original(chat_id, net_state)

    calls._handle_connection_changed = connection_changed
    original_status = calls._update_status

    async def update_status(chat_id, state):
        log.info("Qarshi tomon holati: chat=%s muted=%s video_stopped=%s", chat_id,
                 getattr(state, "muted", "?"), getattr(state, "video_stopped", "?"))
        await original_status(chat_id, state)

    calls._update_status = update_status

    def remote_source(chat_id, source):
        log.info("Qarshi tomon ovozi: chat=%s ssrc=%s state=%s device=%s",
                 chat_id, source.ssrc, source.state, source.device)

    try:
        calls._binding._b.on_remote_source_change(remote_source)
    except Exception:  # noqa: BLE001
        log.exception("on_remote_source_change ulanmadi")


async def log_state(calls, chat_id: int) -> None:
    if not ENABLED:
        return
    try:
        state = await calls._binding.get_state(chat_id)
        log.info("Qo'ng'iroq holati: muted=%s video_paused=%s video_stopped=%s",
                 getattr(state, "muted", "?"), getattr(state, "video_paused", "?"),
                 getattr(state, "video_stopped", "?"))
    except Exception:  # noqa: BLE001
        log.exception("get_state xatosi")


async def send_report(client) -> None:
    """Qo'ng'iroq yozuvlarini egasiga fayl qilib yuboradi, keyin faylni tozalaydi."""
    if not ENABLED or not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
        return
    try:
        await client.send_file(config.OWNER_ID, str(LOG_FILE), force_document=True,
                               caption="🔧 Qo'ng'iroq tekshiruvi fayli. Shuni Claude'ga yuboring.")
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.exception("Tekshiruv faylini yuborib bo'lmadi")
