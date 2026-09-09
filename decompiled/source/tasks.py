"""What the app can automate, declared in one place.

This module is the extension point. Adding an automation means adding a
:class:`TaskSpec` here plus a worker class it can build — the sidebar, the
config panel, the queue chips, the settings persistence and the start/stop
plumbing all read from this registry, so none of the UI files need touching.

A worker is any object with this shape (``realm_raid.RealmRaidWorker`` is the
reference implementation)::

    start()  stop()  join(timeout)  is_alive()
    pause()  resume()  is_paused
    elapsed_seconds   -> float  running time, excluding pauses
    latest_frame()    -> frame or None, for the window thumbnail

    progress          -> int    OPTIONAL. Units of work done. Declare it only
                                alongside a ``progress_label``, and only when
                                the number is actually trustworthy — a count
                                that quietly drifts from reality is worse than
                                no count. Realm Raid has none: it could only be
                                inferred from reward panels, which are missed
                                whenever one is skipped or matched late.

``build`` is what turns a config dict into one of those. A spec with no
``build`` is *declared but not implemented*: it shows in the sidebar so the
shape of the app is visible, and the UI refuses to start it rather than
pretending to run something.

Settings come in two layers, both declared as :class:`Field` tuples so both get
their controls generated for free:

* ``APP_FIELDS`` — things true of the whole app, whichever task is running. The
  reply to a co-op Wanted Quest invite lives here because that dialog blocks
  every task, not just the one that happened to open it.
* ``TaskSpec.fields`` — settings that only mean something to that task.

The manager hands a worker the app layer with the task layer merged on top, so
a builder just reads ``config[key]`` and does not care which layer it came
from. A task key must never shadow an app key; a test enforces that.

Nothing here imports Qt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import geometry
import realm_raid

# ── field kinds ─────────────────────────────────────────────────────────────

SEGMENTED = "segmented"   # a row of mutually exclusive chips
TOGGLE = "toggle"         # a checkbox
NUMBER = "number"         # a spin box
POINT = "point"           # a click position, picked off a live screenshot
NOTE = "note"             # explanatory prose, no value
HOTKEY = "hotkey"         # a system-wide key combination


@dataclass(frozen=True)
class Field:
    """One control in a task's config panel."""

    key: str
    kind: str
    label: str
    options: Tuple[str, ...] = ()
    default: Any = None
    # NUMBER only. `special` is the text shown *instead of* the minimum value —
    # Qt's own idiom for "this end of the range means something else", which
    # avoids documenting a magic number the user cannot see.
    minimum: int = 0
    maximum: int = 999
    special: str = ""
    # NUMBER only. Drawn inside the box after the value, so the unit travels
    # with the number instead of having to be worked into the label.
    suffix: str = ""
    # Settings that differ per game window rather than per task. A co-op room
    # has exactly one leader, so "which role is this window" cannot be one value
    # shared by every window running the task. These render on each window's
    # card instead of the task's config panel.
    per_window: bool = False
    # POINT only. A box on the screen where a stray click does something the
    # user did not ask for, and the sentence to show when the chosen point falls
    # inside it. Per field rather than global: the event clicker's danger is the
    # ticket shop, which has nothing to do with any other point the app asks for
    # — a picker that warned about buying event tickets while someone was
    # choosing a chapter row would be telling them something untrue.
    danger_zone: Any = None
    danger_note: str = ""
    # ``(key, value)``: this control is greyed out while that other field holds
    # that value. Lets "run forever" switch off the count it would ignore,
    # rather than leaving a live-looking number that does nothing.
    disabled_when: Tuple[Any, ...] = ()

    @property
    def holds_value(self) -> bool:
        return self.kind != NOTE


Builder = Callable[..., Any]

TRUE_WORDS = ("1", "true", "yes", "on")


def as_bool(value: Any) -> bool:
    """Read a toggle from whatever the settings store handed back.

    QSettings answers differently per backend: an INI file returns a real
    ``bool``, but the Windows registry — which is what the packaged app uses —
    returns the string ``'false'``. Plain ``bool('false')`` is ``True``, so a
    setting the user turned *off* would come back *on* after a restart.
    """
    if isinstance(value, str):
        return value.strip().lower() in TRUE_WORDS
    return bool(value)


def as_point(value: Any, default: Tuple[int, int]) -> Tuple[int, int]:
    """Read a click position from whatever the settings store handed back.

    Three shapes have to be accepted, because the backends disagree: an INI
    file gives back a real list of ints, the Windows registry — which is what
    the packaged app uses — gives a list of *strings*, and a value it decided
    to flatten comes back as one comma-joined string. A point that fails to
    parse falls back to the default rather than to (0, 0), which would click
    the top-left corner of the game.

    Clamped to the reference client area on the way through. A point outside it
    could only come from a corrupted setting, and clicking off-window does
    nothing at all — silently, which is the worst way for this to fail.
    """
    parts: Any = value
    if isinstance(value, str):
        parts = value.replace("(", "").replace(")", "").split(",")
    try:
        x, y = (int(str(part).strip()) for part in tuple(parts)[:2])
    except (TypeError, ValueError):
        return default
    width, height = geometry.REFERENCE_CLIENT_SIZE
    return (max(0, min(width - 1, x)), max(0, min(height - 1, y)))


@dataclass(frozen=True)
class TaskSpec:
    """One automation: how it is described, configured and started."""

    id: str
    name: str
    kicker: str
    summary: str
    # Empty means this task reports no count, so no counter is shown for it.
    progress_label: str = ""
    fields: Tuple[Field, ...] = ()
    build: Optional[Builder] = None
    todo: str = ""

    @property
    def is_available(self) -> bool:
        """False for a task that is declared but has no worker behind it."""
        return self.build is not None

    @property
    def counts_progress(self) -> bool:
        """Whether this task has a number worth putting on a card."""
        return bool(self.progress_label)

    @property
    def shared_fields(self) -> Tuple[Field, ...]:
        """Settings on the task's own panel — one value for every window."""
        return tuple(f for f in self.fields if not f.per_window)

    @property
    def window_fields(self) -> Tuple[Field, ...]:
        """Settings that live on each window's card, one value per window."""
        return tuple(f for f in self.fields if f.per_window and f.holds_value)

    def defaults(self) -> Dict[str, Any]:
        return defaults_for(self.fields)

    def coerce(self, stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return coerce_fields(self.fields, stored)


def defaults_for(fields: Tuple[Field, ...]) -> Dict[str, Any]:
    return {f.key: f.default for f in fields if f.holds_value}


def coerce_fields(
    fields: Tuple[Field, ...], stored: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge saved settings over the defaults.

    Unknown keys are dropped and a value no longer offered falls back to the
    default, so a settings file written by an older build cannot feed a stale
    option into a worker.
    """
    config = defaults_for(fields)
    for f in fields:
        if not f.holds_value or not stored or f.key not in stored:
            continue
        value = stored[f.key]
        if f.kind == SEGMENTED and value not in f.options:
            continue
        if f.kind == HOTKEY:
            # Kept as typed rather than validated here. An unusable combination
            # is reported when it is registered, by the code that finds out —
            # quietly rewriting somebody's setting to the default would take
            # away the only clue about why their key stopped working.
            config[f.key] = str(value or "").strip()
            continue
        if f.kind == TOGGLE:
            value = as_bool(value)
        if f.kind == POINT:
            config[f.key] = as_point(value, f.default)
            continue
        if f.kind == NUMBER:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            # Clamped rather than rejected: a settings file naming 5000 rounds
            # means "a lot", and the worker should not see a number the control
            # could never have produced.
            value = max(f.minimum, min(f.maximum, value))
        config[f.key] = value
    return config


# ── Realm Raid ──────────────────────────────────────────────────────────────

ACCEPT = "Chấp nhận"
REFUSE = "Từ chối"

# ── settings that belong to the app, not to a task ───────────────────────────

# A co-op Wanted Quest invite is a dialog somebody else opens on your window.
# It covers whatever is on screen and blocks every task, not just Realm Raid,
# so the answer is an app-wide setting. There is deliberately no "leave it"
# choice: an unanswered dialog is exactly the problem being solved.
APP_FIELDS: Tuple[Field, ...] = (
    Field("wanted_invite", SEGMENTED, "Lời mời truy", (REFUSE, ACCEPT), REFUSE),
    Field("notify_on_finish", TOGGLE, "Thông báo khi xong", default=False),
    Field("pause_while_hovering", TOGGLE,
          "Ngừng bấm khi chuột ở trên cửa sổ game", default=True),
    Field("close_to_tray", TOGGLE, "Đóng thì thu xuống khay", default=True),
    Field("start_with_windows", TOGGLE, "Khởi động cùng Windows", default=False),
    Field("snapshot_hotkey", HOTKEY, "Phím chụp nhanh",
          default="Ctrl+Shift+S"),
    Field("record_fps", SEGMENTED, "Quay video",
          ("5 fps", "10 fps", "15 fps", "30 fps"), "10 fps"),
)

# Explanations shown under each app setting in the dialog.
APP_FIELD_NOTES = {
    "snapshot_hotkey":
        "Chụp cửa sổ game đang ở trước mà không cần rời game. Để trống là tắt.",
    "wanted_invite": "Người khác mời co-op Truy nã: hộp thoại che màn hình và "
                     "chặn mọi tác vụ tới khi được trả lời, nên auto luôn trả "
                     "lời thay bạn.",
    "notify_on_finish": "Hiện thông báo của Windows khi một cửa sổ chạy xong "
                        "tác vụ.",
    "start_with_windows": "Bật máy là app tự chạy sẵn dưới khay, không hiện "
                          "cửa sổ. Không tự bắt đầu tác vụ nào — chỉ sẵn ở đó "
                          "để bạn mở lên dùng. Ghi vào mục Startup của Windows "
                          "cho riêng tài khoản này, nên bỏ được cả từ đây hoặc "
                          "từ tab Startup trong Task Manager; app đọc lại từ đó "
                          "nên hai bên không lệch nhau.",
    "record_fps": "Số khung mỗi giây khi bấm Quay trên một cửa sổ. Cảnh ít "
                  "động thì 10 fps khoảng 6 MB/phút, 30 fps khoảng 20 MB/phút; "
                  "cảnh đánh nhau liên tục có thể lên 26 MB/phút — một đêm là "
                  "vài GB, nên nhớ bấm Dừng. "
                  "Tới 15 fps thì tác vụ đang chạy gần như không bị ảnh hưởng "
                  "(đo được: cú chụp của nó đi từ 16,7 lên 16,9 ms). Ở 30 fps "
                  "thì cả hai chia nhau đường chụp của Windows và cú chụp của "
                  "tác vụ chậm gấp đôi — còn 30 lần mỗi giây, vẫn nhiều hơn "
                  "mức mọi tác vụ trong app cần, nhưng máy yếu thì nên để 10.",
    "close_to_tray": "Bấm X thì cửa sổ ẩn xuống khay hệ thống chứ không thoát, "
                     "auto vẫn chạy tiếp. Mở lại bằng cách nhấn đúp vào biểu "
                     "tượng ở khay; thoát hẳn thì nhấn phải rồi chọn Thoát. Tắt "
                     "tuỳ chọn này thì X thoát luôn như trước.",
}


def app_defaults() -> Dict[str, Any]:
    return defaults_for(APP_FIELDS)


def coerce_app(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return coerce_fields(APP_FIELDS, stored)


def merge_layers(app: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """App-wide settings with a task's own on top — the dict a builder receives.

    Defined here rather than inline in the manager so there is one description
    of the shape, and so a builder can be exercised against exactly it.
    """
    merged = dict(app)
    merged.update(task)
    return merged


# ── Realm Raid ──────────────────────────────────────────────────────────────

REALM_RAID_FIELDS = (
    Field("auto_refresh", TOGGLE, "Thua thì đổi danh sách đối thủ", default=True),
    Field("stop_when_out_of_tickets", TOGGLE, "Tự dừng khi hết vé", default=True),
    Field("", NOTE, "Nhận diện bằng ảnh mẫu trong screenshots/RealmRaid; toạ độ "
                    "quy theo tỉ lệ cửa sổ nên không phụ thuộc độ phân giải."),
    Field("", NOTE, "\"Thua thì đổi danh sách\": thua một trận thì bấm Refresh "
                    "lấy bảng đối thủ mới. Thua là mất luôn lượt ở thẻ đó — thẻ "
                    "bị khoá y như đã đánh xong nhưng không tính là phá được "
                    "kết giới, nên bảng đó sẽ không bao giờ tự đổi. Tác vụ nhận "
                    "ra cả hai đường: bảng kết quả thua ngay sau trận, và dấu "
                    "thua còn lại trên thẻ khi về danh sách."),
    Field("", NOTE, "Không phụ thuộc tuỳ chọn trên: khi trên bảng không còn kết "
                    "giới nào đánh được, tác vụ tự bấm Refresh — nếu không thì "
                    "nó đứng nhìn một bảng đã hết việc. Chỉ làm ở phá kết giới "
                    "cá nhân; bảng của hội không có nút Refresh nên tác vụ để "
                    "yên, không bấm gì."),
)


def build_realm_raid(hwnd, control, config, on_finished, on_error):
    # `config` is this task's own settings with the app-wide ones merged
    # underneath, which is where `wanted_invite` comes from.
    return realm_raid.RealmRaidWorker(
        hwnd=hwnd,
        auto_refresh=bool(config["auto_refresh"]),
        stop_when_out_of_tickets=bool(config["stop_when_out_of_tickets"]),
        accept_wanted_quest=config["wanted_invite"] == ACCEPT,
        accuracy=realm_raid.DEFAULT_ACCURACY,
        control=control,
        on_finished=on_finished,
        on_error=on_error,
    )


# ── Souls dungeon ───────────────────────────────────────────────────────────

LEADER = "Chủ phòng"
MEMBER = "Thành viên"

SOULS_FIELDS = (
    # Per window: a co-op room has exactly one leader, so this cannot be one
    # value shared by every window running the task.
    Field("role", SEGMENTED, "Vai trong phòng", (LEADER, MEMBER), LEADER,
          per_window=True),
    Field("rounds", NUMBER, "Dừng sau", default=30, minimum=1, maximum=999,
          disabled_when=("unlimited", True)),
    Field("unlimited", TOGGLE, "Chạy vĩnh viễn", default=False),
    Field("", NOTE, "Chủ phòng bấm Bắt đầu khi phòng đủ người; thành viên chỉ "
                    "bấm qua màn kết thúc. Nút Bắt đầu được nhận biết bằng màu "
                    "chứ không phải hình dạng — ngay sau mỗi trận nó còn xám "
                    "vài giây trong lúc đồng đội quay lại."),
)


def build_souls_dungeon(hwnd, control, config, on_finished, on_error):
    import souls_dungeon

    return souls_dungeon.SoulsDungeonWorker(
        hwnd=hwnd,
        role=(souls_dungeon.ROLE_LEADER if config["role"] == LEADER
              else souls_dungeon.ROLE_MEMBER),
        # The worker's own convention is 0 = keep going; the UI says it with a
        # checkbox instead, so the number never has to mean two things.
        rounds=0 if as_bool(config["unlimited"]) else int(config["rounds"]),
        accept_wanted_quest=config["wanted_invite"] == ACCEPT,
        accuracy=souls_dungeon.DEFAULT_ACCURACY,
        control=control,
        on_finished=on_finished,
        on_error=on_error,
    )


BEANS_5 = "5 hạt"
BEANS_10 = "10 hạt"

PARADE_FIELDS = (
    Field("beans", SEGMENTED, "Mỗi phát ném", (BEANS_5, BEANS_10), BEANS_10),
    Field("rounds", NUMBER, "Dừng sau", default=30, minimum=1, maximum=999,
          disabled_when=("unlimited", True)),
    Field("unlimited", TOGGLE, "Chạy vĩnh viễn", default=False),
    Field("", NOTE, "Mỗi lượt vào tốn một vé; hết vé thì tự dừng và báo. Đậu "
                    "250 hạt là ngân sách của riêng từng vòng, hết vòng lại "
                    "đầy nên không phải lo. Bot rải đậu dọc lối đi thay vì "
                    "nhắm từng con — đo thật thì rải được 26 mảnh một vòng, "
                    "còn ném có nhắm ba phát thì không được mảnh nào."),
)


def build_demon_parade(hwnd, control, config, on_finished, on_error):
    import demon_parade

    return demon_parade.DemonParadeWorker(
        hwnd=hwnd,
        beans=5 if config["beans"] == BEANS_5 else 10,
        # 0 = keep going, said with a checkbox in the UI so the number never
        # has to mean two things.
        rounds=0 if as_bool(config["unlimited"]) else int(config["rounds"]),
        accept_wanted_quest=config["wanted_invite"] == ACCEPT,
        accuracy=demon_parade.DEFAULT_ACCURACY,
        control=control,
        on_finished=on_finished,
        on_error=on_error,
    )


# ── Event ───────────────────────────────────────────────────────────────────

EVENT_FIELDS = (
    Field("click_point", POINT, "Chỗ tự nhấn", default=geometry.EVENT_CLICK_POINT,
          danger_zone=geometry.EVENT_SHOP_PANEL,
          danger_note="Điểm này nằm trong vùng bảng bán vé hiện ra khi hết vé — "
                      "nhấn vào đó có thể bấm nhầm nút mua bằng ngọc. Nên chọn "
                      "chỗ ngoài vùng giữa màn hình."),
    Field("interval", NUMBER, "Nhấn mỗi", default=2, minimum=1, maximum=10,
          suffix=" giây"),
    Field("", NOTE, "Tác vụ này không đọc màn hình, chỉ nhấn đúng một chỗ và "
                    "lặp lại. Chữ trên nút bắt đầu mỗi event một khác "
                    "(Challenge, Fight…) nên không thể nhận diện theo chữ, còn "
                    "vị trí nút thì không đổi — ở màn event cú nhấn đó vào "
                    "trận, ở màn kết thúc nó là cú chạm tắt bảng, đang đánh "
                    "thì nó rơi vào chỗ vô hại. Đổi lại, nó không biết lúc nào "
                    "hết vé: hết vé thì game mở bảng bán vé bằng ngọc, chỗ "
                    "nhấn mặc định nằm ngoài bảng đó nên chỉ tắt bảng, nhưng "
                    "chỗ nhấn đặt vào giữa màn hình thì có thể bấm nhầm nút "
                    "mua. Số đếm là số lần nhấn, không phải số trận."),
)


def build_event_clicker(hwnd, control, config, on_finished, on_error):
    import event_clicker

    return event_clicker.EventClickerWorker(
        hwnd=hwnd,
        point=as_point(config["click_point"], geometry.EVENT_CLICK_POINT),
        interval=float(config["interval"]),
        accept_wanted_quest=config["wanted_invite"] == ACCEPT,
        control=control,
        on_finished=on_finished,
        on_error=on_error,
    )


# ── Exploration ─────────────────────────────────────────────────────────────

EXPLORATION_FIELDS = (
    Field("chapter_point", POINT, "Chỗ nhấn vào chương",
          default=geometry.EXPLORATION_CHAPTER_POINT),
    Field("raid_relay", TOGGLE, "Đủ 30/30 vé thì đi phá kết giới (thử nghiệm)",
          default=False),
    Field("", NOTE, "Tự đi ổ quái trong một chương: thấy ổ quái thì nhấn "
                    "vào (nhấn là vào trận luôn, không qua bảng xếp đội), "
                    "không thấy thì kéo bản đồ ngang đi tìm — kéo mà cảnh "
                    "không nhích thì đã tới rìa, tự đổi chiều. Hiện boss là "
                    "đánh boss trước, không dọn hết ổ thường, vì hạ boss là "
                    "xong chương. Đánh xong boss "
                    "game trả về màn chọn chương, tác vụ nhấn lại vào chương "
                    "cũ và chạy vòng mới. Độ khó (Normal/Hard) lấy theo cái "
                    "bạn chọn tay lần cuối, tác vụ không đổi. Chỗ nhấn mặc "
                    "định là dòng chương 28; farm chương khác thì chọn lại "
                    "toạ độ. Nó không biết lúc nào hết sushi: hết thì nó cứ "
                    "nhấn mãi một ổ mà ổ không mất, và ghi cảnh báo vào log. "
                    "Số đếm là số ổ đã vào, không phải số trận thắng."),
    Field("", NOTE, "Bật \"đủ 30/30 vé\": mỗi lần quay về bảng chương, tác vụ "
                    "đọc ô vé phá kết giới ở thanh trên. Đúng 30/30 thì nó "
                    "chuyển sang phá kết giới ngay tại cửa sổ này, đánh tới khi "
                    "hết vé rồi tự quay lại farm map — lặp mãi cho tới khi bạn "
                    "bấm Dừng. Vé hồi theo giờ và ngừng cộng khi đầy, nên để "
                    "nguyên 30/30 là phí vé. Nó đọc từng chữ số chứ không so "
                    "ảnh cả ô, nên 0/30, 6/30 hay 20/30 không thể bị nhận nhầm "
                    "thành 30/30; đọc không ra thì nó coi như chưa đủ và cứ "
                    "farm tiếp. Lưu ý "
                    "nó vẫn không biết lúc nào hết sushi. "
                    "Đang thử nghiệm: mới chạy đúng trên một tài khoản, và "
                    "riêng cảnh 30/30 thì chưa chụp được ảnh game thật để đối "
                    "chiếu — mới kiểm bằng chữ số thật ghép lại. Lần đầu bật, "
                    "nên ngồi xem vài vòng rồi hẵng để chạy một mình. Nếu raid "
                    "kẹt không thoát, sau 15 phút tác vụ tự lấy lại cửa sổ và "
                    "quay về farm."),
)


def build_exploration(hwnd, control, config, on_finished, on_error):
    import exploration

    return exploration.ExplorationWorker(
        hwnd=hwnd,
        chapter_point=as_point(
            config["chapter_point"], geometry.EXPLORATION_CHAPTER_POINT
        ),
        accept_wanted_quest=config["wanted_invite"] == ACCEPT,
        raid_relay=as_bool(config["raid_relay"]),
        control=control,
        on_finished=on_finished,
        on_error=on_error,
    )


# ── the registry ────────────────────────────────────────────────────────────

# Every task here is implemented. A spec may also be *declared* without a
# `build`, carrying a `todo` instead: the UI then lists it and refuses to start
# it, showing what writing it would involve. That is the registry's extension
# point and the app still renders it — there is simply nothing waiting in it
# right now. "Nhiệm vụ truy nã" sat here until it was dropped, unbuilt: it
# needed OCR over Chinese shikigami names on a moving background, and it is not
# being written.
TASKS: Tuple[TaskSpec, ...] = (
    TaskSpec(
        id="realm_raid",
        name="Phá Kết Giới",
        kicker="Tác vụ · Realm Raid",
        summary="Đánh kết giới của người chơi khác theo vị trí target đã chọn, "
                "tự dừng khi hết vé.",
        # No progress_label: see the worker protocol above for why this loop
        # reports no battle count.
        fields=REALM_RAID_FIELDS,
        build=build_realm_raid,
    ),
    TaskSpec(
        id="beans",
        name="Ném đậu",
        kicker="Tác vụ · Demon Parade",
        summary="Chơi một mình: vào Demon Parade, chọn thức thần, rải đậu suốt "
                "vòng rồi đóng bảng kết quả. Hết vé thì dừng.",
        progress_label="vòng đã chơi",
        fields=PARADE_FIELDS,
        build=build_demon_parade,
    ),
    TaskSpec(
        id="event",
        name="Event",
        kicker="Tác vụ · Event",
        summary="Tự nhấn một chỗ để đánh event lặp lại, không phụ thuộc chữ "
                "trên nút bắt đầu.",
        progress_label="lần nhấn",
        fields=EVENT_FIELDS,
        build=build_event_clicker,
    ),
    TaskSpec(
        id="exploration",
        name="Thám hiểm chương",
        kicker="Tác vụ · Exploration",
        summary="Đánh ổ quái trong một chương, hiện boss thì đánh boss ngay. "
                "Không thấy ổ thì kéo bản đồ đi tìm. Xong thì vào lại chương.",
        progress_label="ổ đã đánh",
        fields=EXPLORATION_FIELDS,
        build=build_exploration,
    ),
    TaskSpec(
        id="souls",
        name="Phụ bản ngự hồn",
        kicker="Tác vụ · Souls",
        summary="Chạy phòng co-op ngự hồn: chủ phòng bấm Bắt đầu, cả hai vai "
                "tự bấm qua màn kết thúc. Game tự tạo lại phòng và mời.",
        progress_label="trận đã đánh",
        fields=SOULS_FIELDS,
        build=build_souls_dungeon,
    ),
)

BY_ID: Dict[str, TaskSpec] = {spec.id: spec for spec in TASKS}
DEFAULT_TASK_ID = TASKS[0].id


def get(task_id: str) -> Optional[TaskSpec]:
    return BY_ID.get(task_id)


def is_available(task_id: str) -> bool:
    """True only for a known task that has a worker behind it."""
    spec = BY_ID.get(task_id)
    return spec is not None and spec.is_available


def available() -> List[TaskSpec]:
    return [spec for spec in TASKS if spec.is_available]


def clean_task(value) -> Optional[str]:
    """The task id in ``value``, or None if there is not a usable one.

    Accepts a list as well as a single id, and takes the first entry it knows.
    Earlier versions ran a queue of tasks per window and saved that queue, so a
    settings file written by one of those holds a list where this now wants one
    id — reading it as "the task this window was set to" keeps a returning
    user's choice instead of silently resetting them to the default.
    """
    if isinstance(value, str):
        return value if value in BY_ID else None
    for task_id in value or ():
        if isinstance(task_id, str) and task_id in BY_ID:
            return task_id
    return None
