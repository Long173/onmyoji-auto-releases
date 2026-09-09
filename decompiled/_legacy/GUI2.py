"""Onmyoji Auto — Pha Ket Gioi (Realm Raid).

Single-feature build. UI dung pyqtdarktheme + custom accent.
"""
import sys
import threading

import qdarktheme
import win32gui
from PyQt5 import QtCore, QtGui, QtWidgets

from realm import Processing as realm_raid_process
from Util import printWithTime, stopThread

APP_NAME = "Onmyoji Auto"
APP_SUBTITLE = "Pha Ket Gioi"
APP_VERSION = "1.0"
DEFAULT_WINDOW_TITLE = "陰陽師Onmyoji"
ACCENT = "#7c5cff"
SUCCESS = "#10b981"
DANGER = "#ef4444"
MUTED = "#94a3b8"


class RealmRaidWorker:
    """Thin wrapper around realm.Processing thread."""

    def __init__(self, tencuaso: str, vitri: int, refresh: bool):
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(tencuaso)
        if not windows:
            raise RuntimeError("Khong tim thay cua so game: %s" % tencuaso)
        windows[0].resizeTo(1138, 672)

        self.thread = realm_raid_process(
            tencuaso,
            9999999,
            False,
            False,
            vitri=vitri,
            accuracy=0.9,
            client=0,
            refresh=refresh,
        )

    def start(self):
        self.thread.start()


class StatusDot(QtWidgets.QWidget):
    """Colored circle indicator."""

    def __init__(self, color: str = MUTED, diameter: int = 12, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._d = diameter
        self.setFixedSize(diameter, diameter)

    def setColor(self, color: str):
        self._color = QtGui.QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(0, 0, self._d, self._d)


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self._worker = None
        self._settings = QtCore.QSettings("OnmyojiAuto", "RealmRaid")
        self.setWindowTitle("%s · %s" % (APP_NAME, APP_SUBTITLE))
        self.setFixedSize(480, 540)
        self._build_ui()
        self._load_settings()
        self._wire_events()
        self._set_status("idle")

    def _load_settings(self):
        vitri = int(self._settings.value("vitri", 3))
        idx = self.vitri_combo.findData(vitri)
        if idx >= 0:
            self.vitri_combo.setCurrentIndex(idx)
        refresh = self._settings.value("refresh", False, type=bool)
        self.refresh_check.setChecked(refresh)
        win_title = self._settings.value("window_title", DEFAULT_WINDOW_TITLE)
        self.window_input.setText(win_title)

    def _save_settings(self):
        self._settings.setValue("vitri", self.vitri_combo.currentData())
        self._settings.setValue("refresh", self.refresh_check.isChecked())
        self._settings.setValue("window_title", self.window_input.text().strip())

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        # ===== Header =====
        header = QtWidgets.QVBoxLayout()
        header.setSpacing(2)
        title = QtWidgets.QLabel(APP_NAME)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        subtitle = QtWidgets.QLabel(APP_SUBTITLE.upper())
        subtitle.setStyleSheet("font-size: 11px; color: %s; letter-spacing: 2px;" % ACCENT)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # ===== Card: Window detection =====
        win_card = self._make_card("Cửa sổ game")
        win_layout = win_card.layout()

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)
        self.window_input = QtWidgets.QLineEdit(DEFAULT_WINDOW_TITLE)
        self.window_input.setPlaceholderText("Tiêu đề cửa sổ game")
        self.window_input.setMinimumHeight(32)
        self.check_btn = QtWidgets.QPushButton("Kiểm tra")
        self.check_btn.setMinimumHeight(32)
        self.check_btn.setMinimumWidth(110)
        self.check_status = QtWidgets.QLabel("")
        self.check_status.setMinimumWidth(110)
        row1.addWidget(self.window_input, 1)
        row1.addWidget(self.check_btn)
        win_layout.addLayout(row1)
        win_layout.addWidget(self.check_status)
        root.addWidget(win_card)

        # ===== Card: Settings =====
        cfg_card = self._make_card("Cấu hình")
        cfg_layout = cfg_card.layout()

        pos_row = QtWidgets.QHBoxLayout()
        pos_row.addWidget(QtWidgets.QLabel("Vị trí target (tắt auto bắt đầu mới hoạt động)"))
        pos_row.addStretch()
        self.vitri_combo = QtWidgets.QComboBox()
        for i in range(1, 6):
            self.vitri_combo.addItem("Slot %d" % i, i)
        self.vitri_combo.setCurrentIndex(2)
        self.vitri_combo.setFixedWidth(110)
        pos_row.addWidget(self.vitri_combo)
        cfg_layout.addLayout(pos_row)

        self.refresh_check = QtWidgets.QCheckBox("Tự refresh khi bị đánh bại")
        cfg_layout.addWidget(self.refresh_check)
        root.addWidget(cfg_card)

        # ===== Card: Status =====
        st_card = self._make_card("Trạng thái")
        st_layout = st_card.layout()
        st_row = QtWidgets.QHBoxLayout()
        st_row.setSpacing(10)
        self.status_dot = StatusDot(MUTED, diameter=12)
        self.status_text = QtWidgets.QLabel("Sẵn sàng")
        self.status_text.setStyleSheet("font-size: 13px;")
        st_row.addWidget(self.status_dot)
        st_row.addWidget(self.status_text)
        st_row.addStretch()
        st_layout.addLayout(st_row)
        root.addWidget(st_card)

        # ===== Action buttons =====
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)
        self.start_btn = QtWidgets.QPushButton("▶  Bắt đầu")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: %s; color: white; font-weight: 600;"
            " border-radius: 6px; }"
            "QPushButton:hover { background-color: #6645ff; }"
            "QPushButton:disabled { background-color: #3f3a52; color: #888; }"
            % ACCENT
        )
        self.stop_btn = QtWidgets.QPushButton("■  Kết thúc")
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn, 2)
        btn_row.addWidget(self.stop_btn, 1)
        root.addLayout(btn_row)

        # ===== Footer =====
        root.addStretch()
        footer = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("F1 = Pause / Resume")
        hint.setStyleSheet("color: %s; font-size: 11px;" % MUTED)
        ver = QtWidgets.QLabel("v" + APP_VERSION)
        ver.setStyleSheet("color: %s; font-size: 11px;" % MUTED)
        footer.addWidget(hint)
        footer.addStretch()
        footer.addWidget(ver)
        root.addLayout(footer)

    def _make_card(self, title: str) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        box.setStyleSheet(
            "QGroupBox { font-size: 11px; font-weight: 600; color: %s;"
            " border: 1px solid #2d3142; border-radius: 8px;"
            " margin-top: 14px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;"
            " left: 12px; padding: 0 6px; background-color: transparent; }"
            % MUTED
        )
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(10)
        return box

    def _wire_events(self):
        self.check_btn.clicked.connect(self._on_check)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.vitri_combo.currentIndexChanged.connect(self._save_settings)
        self.refresh_check.stateChanged.connect(self._save_settings)
        self.window_input.editingFinished.connect(self._save_settings)

    def _on_check(self):
        title = self.window_input.text().strip()
        if not title:
            self.check_status.setStyleSheet("color: %s;" % DANGER)
            self.check_status.setText("✗ Trống")
            return
        if win32gui.FindWindow(0, title) == 0:
            self.check_status.setStyleSheet("color: %s;" % DANGER)
            self.check_status.setText("✗ Không tìm thấy")
        else:
            self.check_status.setStyleSheet("color: %s;" % SUCCESS)
            self.check_status.setText("✓ OK")

    def _on_start(self):
        title = self.window_input.text().strip()
        vitri = self.vitri_combo.currentData()
        refresh = self.refresh_check.isChecked()
        try:
            self._worker = RealmRaidWorker(title, vitri, refresh)
            self._worker.start()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Không khởi động được", str(exc))
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_status("running")

    def _on_stop(self):
        for thread in threading.enumerate():
            if thread.name != "ThreadTool" and thread.name != "MainThread":
                try:
                    stopThread(thread)
                except Exception:
                    pass
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_status("stopped")

    def _set_status(self, state: str):
        if state == "running":
            self.status_dot.setColor(SUCCESS)
            self.status_text.setText("Đang chạy — bấm Kết thúc để dừng")
            self.status_text.setStyleSheet("font-size: 13px; color: %s;" % SUCCESS)
        elif state == "stopped":
            self.status_dot.setColor(DANGER)
            self.status_text.setText("Đã dừng")
            self.status_text.setStyleSheet("font-size: 13px; color: %s;" % MUTED)
        else:
            self.status_dot.setColor(MUTED)
            self.status_text.setText("Sẵn sàng")
            self.status_text.setStyleSheet("font-size: 13px; color: %s;" % MUTED)


def _run_gui():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    th = threading.Thread(None, _run_gui)
    th.name = "ThreadTool"
    th.start()
