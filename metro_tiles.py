# metro_tiles.py
# A standalone, Windows 8 "Metro/Modern UI"-style tile dashboard
# ---------------------------------------------------------------

# Features
# - Grid of colorful tiles (small/wide/large) with icons + labels
# - Actions per tile: open URL, launch app/command, open file/folder, or built-in widgets (Clock)
# - Add/Edit/Delete tiles via a GUI dialog
# - Right-click context menu on tiles
# - Light/Dark theme toggle
# - Layout engine that packs variable-size tiles (bin-like placement)
# - Config is auto-saved to JSON in user config folder
# - Cross-platform (Windows/macOS/Linux)
# - Packaging notes with PyInstaller at bottom of this file

import json
import os
import sys
import webbrowser
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QSize, QPoint
from PySide6.QtGui import QAction, QIcon, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFileDialog, QComboBox, QLineEdit, QColorDialog,
    QDialog, QDialogButtonBox, QMessageBox, QToolBar, QMenu, QSpinBox
)

APP_NAME = "MetroTiles"
DEFAULT_COLUMNS = 4
CELL_SIZE = 140  # base cell size in pixels
CELL_GAP = 12

# -------------------------- Utilities & Config ---------------------------

def user_config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path

CONFIG_PATH = os.path.join(user_config_dir(), "config.json")

@dataclass
class Tile:
    id: str
    title: str
    color: str = "#0078D7"  # Windows blue
    icon_path: Optional[str] = None
    action_type: str = "url"  # url | command | file | builtin
    action_value: str = ""  # e.g., https://..., notepad, C:\...
    size: str = "small"  # small (1x1) | wide (2x1) | large (2x2)
    row: int = 0
    col: int = 0

@dataclass
class AppState:
    theme: str = "dark"  # dark | light
    columns: int = DEFAULT_COLUMNS
    tiles: List[Tile] = None

class ConfigManager:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> AppState:
        if not os.path.exists(self.path):
            return self._default_state()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tiles = [Tile(**t) for t in data.get("tiles", [])]
            return AppState(
                theme=data.get("theme", "dark"),
                columns=data.get("columns", DEFAULT_COLUMNS),
                tiles=tiles
            )
        except Exception:
            return self._default_state()

    def save(self, state: AppState):
        payload = {
            "theme": state.theme,
            "columns": state.columns,
            "tiles": [asdict(t) for t in state.tiles or []],
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _default_state(self) -> AppState:
        defaults = [
            Tile(id="tile_browser", title="Browser", color="#0078D7", icon_path=None,
                 action_type="url", action_value="https://www.example.com", size="wide"),
            Tile(id="tile_docs", title="Documents", color="#107C10", icon_path=None,
                 action_type="file", action_value=os.path.expanduser("~"), size="small"),
            Tile(id="tile_cmd", title="Notepad", color="#D83B01", icon_path=None,
                 action_type="command",
                 action_value="notepad" if sys.platform.startswith("win") else
                              "open -a TextEdit" if sys.platform == "darwin" else
                              "gedit",
                 size="small"),
            Tile(id="tile_clock", title="Clock", color="#5C2D91", icon_path=None,
                 action_type="builtin", action_value="clock", size="large"),
            Tile(id="tile_settings", title="Settings", color="#FFB900", icon_path=None,
                 action_type="builtin", action_value="settings", size="small"),
        ]
        return AppState(theme="dark", columns=DEFAULT_COLUMNS, tiles=defaults)

# -------------------------- Tile Widgets ---------------------------

SIZE_MAP = {
    "small": (1, 1),
    "wide": (1, 2),
    "large": (2, 2),
}

class TileButton(QPushButton):
    def __init__(self, tile: Tile, parent=None):
        super().__init__(parent)
        self.tile = tile
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(False)
        self.setAcceptDrops(True)
        self.setMinimumSize(self.tile_pixel_size())
        self.setMaximumSize(self.tile_pixel_size())
        self.setStyle()
        self.update_content()

    def tile_pixel_size(self) -> QSize:
        r, c = SIZE_MAP.get(self.tile.size, (1,1))
        w = c * CELL_SIZE + (c - 1) * CELL_GAP
        h = r * CELL_SIZE + (r - 1) * CELL_GAP
        return QSize(w, h)

    def setStyle(self):
        radius = 12
        self.setStyleSheet(f"""
        QPushButton {{
            background: {self.tile.color};
            color: white;
            border: none;
            border-radius: {radius}px;
            padding: 16px;
            text-align: left;
        }}
        QPushButton:hover {{
            filter: brightness(1.05);
        }}
        """)

    def update_content(self):
        label_html = f"<div style='font-size:18px; font-weight:600; font-family:Segoe UI, Arial'>{self.tile.title}</div>"
        icon_html = ""
        if self.tile.icon_path and os.path.exists(self.tile.icon_path):
            pix = QPixmap(self.tile.icon_path)
            if not pix.isNull():
                icon = QIcon(pix)
                self.setIcon(icon)
                self.setIconSize(QSize(32,32))
            else:
                self.setIcon(QIcon())
        self.setText("")
        self.setToolTip(self.tile.title)
        self.setAccessibleName(self.tile.title)

        if self.tile.action_type == "builtin" and self.tile.action_value == "clock":
            self.setText(self._clock_text())
            f = QFont("Segoe UI", 22, QFont.Bold)
            self.setFont(f)
            self.setStyleSheet(self.styleSheet() + "\nQPushButton { text-align: left; padding: 16px; }")
        else:
            f = QFont("Segoe UI", 14, QFont.DemiBold)
            self.setFont(f)
            self.setText(self.tile.title)
            self.setStyleSheet(self.styleSheet() + "\nQPushButton { text-align: left; padding: 16px; }")

    def _clock_text(self) -> str:
        return time.strftime("%H:%M\n%a %d %b")

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.parent().start_drag(self)
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        self.parent().open_tile_menu(self, event.globalPos())

# -------------------------- Editor Dialog ---------------------------

class TileEditor(QDialog):
    def __init__(self, tile: Optional[Tile] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Tile" if tile else "Add Tile")
        self.tile = tile or Tile(id=f"tile_{int(time.time())}", title="New Tile")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        # Title
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit(self.tile.title)
        row1.addWidget(self.title_edit)
        layout.addLayout(row1)

        # Color & Size
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Color:"))
        self.color_btn = QPushButton(self.tile.color)
        self.color_btn.clicked.connect(self.pick_color)
        row2.addWidget(self.color_btn)
        row2.addWidget(QLabel("Size:"))
        self.size_combo = QComboBox()
        self.size_combo.addItems(["small", "wide", "large"])
        self.size_combo.setCurrentText(self.tile.size)
        row2.addWidget(self.size_combo)
        layout.addLayout(row2)

        # Icon
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Icon (png/svg):"))
        self.icon_edit = QLineEdit(self.tile.icon_path or "")
        browse_icon = QPushButton("Browse…")
        browse_icon.clicked.connect(self.pick_icon)
        row3.addWidget(self.icon_edit)
        row3.addWidget(browse_icon)
        layout.addLayout(row3)

        # Action
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Action Type:"))
        self.action_combo = QComboBox()
        self.action_combo.addItems(["url", "command", "file", "builtin"])
        self.action_combo.setCurrentText(self.tile.action_type)
        row4.addWidget(self.action_combo)
        row4.addWidget(QLabel("Value:"))
        self.value_edit = QLineEdit(self.tile.action_value)
        browse_val = QPushButton("…")
        browse_val.clicked.connect(self.pick_value)
        row4.addWidget(self.value_edit)
        row4.addWidget(browse_val)
        layout.addLayout(row4)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def pick_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.color_btn.setText(color.name())

    def pick_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pick Icon", "", "Images (*.png *.jpg *.jpeg *.svg)")
        if path:
            self.icon_edit.setText(path)

    def pick_value(self):
        t = self.action_combo.currentText()
        if t in ("file",):
            path = QFileDialog.getExistingDirectory(self, "Pick Folder or Cancel for File")
            if path:
                self.value_edit.setText(path)
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Pick File")
                if path:
                    self.value_edit.setText(path)
        elif t == "command":
            path, _ = QFileDialog.getOpenFileName(self, "Pick Executable (or Cancel to type)")
            if path:
                self.value_edit.setText(path)
        elif t == "url":
            pass
        elif t == "builtin":
            QMessageBox.information(self, "Builtin", "Builtin values: 'clock' or 'settings'")

    def get_tile(self) -> Tile:
        self.tile.title = self.title_edit.text().strip() or "Tile"
        self.tile.color = self.color_btn.text()
        self.tile.size = self.size_combo.currentText()
        self.tile.icon_path = self.icon_edit.text().strip() or None
        self.tile.action_type = self.action_combo.currentText()
        self.tile.action_value = self.value_edit.text().strip()
        return self.tile

# -------------------------- Main Window ---------------------------

class TileGrid(QWidget):
    def __init__(self, state: AppState, on_change, parent=None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.grid = QGridLayout(self)
        self.grid.setHorizontalSpacing(CELL_GAP)
        self.grid.setVerticalSpacing(CELL_GAP)
        self.grid.setContentsMargins(16, 16, 16, 16)
        self.buttons: List[TileButton] = []
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(1000)
        self.rebuild()

    def _tick(self):
        for b in self.buttons:
            if b.tile.action_type == "builtin" and b.tile.action_value == "clock":
                b.setText(b._clock_text())

    def clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        self.buttons.clear()

    def rebuild(self):
        self.clear()
        positions = self._pack_tiles(self.state.tiles, self.state.columns)
        for tile, (row, col, rowspan, colspan) in positions:
            btn = TileButton(tile, parent=self)
            btn.clicked.connect(lambda checked=False, t=tile: self.activate_tile(t))
            self.grid.addWidget(btn, row, col, rowspan, colspan)
            self.buttons.append(btn)
        self.on_change()

    def _pack_tiles(self, tiles: List[Tile], columns: int) -> List[Tuple[Tile, Tuple[int,int,int,int]]]:
        occupancy = {}
        positions = []

        def first_fit(rspan, cspan):
            r = 0
            while True:
                for c in range(columns):
                    if c + cspan > columns:
                        continue
                    ok = True
                    for rr in range(r, r + rspan):
                        for cc in range(c, c + cspan):
                            if occupancy.get((rr, cc)):
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        for rr in range(r, r + rspan):
                            for cc in range(c, c + cspan):
                                occupancy[(rr, cc)] = True
                        return r, c
                r += 1

        for t in tiles:
            rspan, cspan = SIZE_MAP.get(t.size, (1,1))
            r, c = first_fit(rspan, cspan)
            t.row, t.col = r, c
            positions.append((t, (r, c, rspan, cspan)))
        return positions

    def start_drag(self, btn: TileButton):
        idx = self._index_of(btn.tile)
        if idx is None:
            return
        if idx < len(self.state.tiles) - 1:
            self.state.tiles[idx], self.state.tiles[idx+1] = self.state.tiles[idx+1], self.state.tiles[idx]
            self.rebuild()

    def _index_of(self, tile: Tile) -> Optional[int]:
        for i, t in enumerate(self.state.tiles):
            if t.id == tile.id:
                return i
        return None

    def open_tile_menu(self, btn: TileButton, global_pos: QPoint):
        menu = QMenu(self)
        act_open = QAction("Open", self)
        act_edit = QAction("Edit…", self)
        act_dup = QAction("Duplicate", self)
        act_del = QAction("Delete", self)
        act_bring_forward = QAction("Move Forward", self)
        act_send_back = QAction("Move Back", self)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_edit)
        menu.addAction(act_dup)
        menu.addSeparator()
        menu.addAction(act_bring_forward)
        menu.addAction(act_send_back)
        menu.addSeparator()
        menu.addAction(act_del)
        act_open.triggered.connect(lambda: self.activate_tile(btn.tile))
        act_edit.triggered.connect(lambda: self.edit_tile(btn.tile))
        act_dup.triggered.connect(lambda: self.duplicate_tile(btn.tile))
        act_del.triggered.connect(lambda: self.delete_tile(btn.tile))
        act_bring_forward.triggered.connect(lambda: self.move_tile(btn.tile, +1))
        act_send_back.triggered.connect(lambda: self.move_tile(btn.tile, -1))
        menu.exec(global_pos)

    def move_tile(self, tile: Tile, delta: int):
        i = self._index_of(tile)
        if i is None:
            return
        j = max(0, min(len(self.state.tiles)-1, i+delta))
        if i != j:
            self.state.tiles[i], self.state.tiles[j] = self.state.tiles[j], self.state.tiles[i]
            self.rebuild()

    def edit_tile(self, tile: Tile):
        dlg = TileEditor(tile, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.get_tile()
            self.rebuild()

    def duplicate_tile(self, tile: Tile):
        t = Tile(**asdict(tile))
        t.id = f"tile_{int(time.time())}"
        self.state.tiles.append(t)
        self.rebuild()

    def delete_tile(self, tile: Tile):
        ans = QMessageBox.question(self, "Delete", f"Delete tile '{tile.title}'?")
        if ans == QMessageBox.Yes:
            self.state.tiles = [t for t in self.state.tiles if t.id != tile.id]
            self.rebuild()

    def activate_tile(self, tile: Tile):
        if tile.action_type == "url":
            if tile.action_value:
                webbrowser.open(tile.action_value)
        elif tile.action_type == "file":
            path = tile.action_value
            if not path:
                return
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        elif tile.action_type == "command":
            if tile.action_value:
                try:
                    if sys.platform.startswith("win"):
                        subprocess.Popen(tile.action_value, shell=True)
                    else:
                        subprocess.Popen(tile.action_value, shell=True, executable="/bin/bash")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to run command:\n{e}")
        elif tile.action_type == "builtin":
            if tile.action_value == "settings":
                self._open_settings()
            elif tile.action_value == "clock":
                pass

    def _open_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        v = QVBoxLayout(dlg)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        theme_combo = QComboBox()
        theme_combo.addItems(["dark", "light"])
        theme_combo.setCurrentText(self.state.theme)
        theme_row.addWidget(theme_combo)
        v.addLayout(theme_row)
        col_row = QHBoxLayout()
        col_row.addWidget(QLabel("Columns:"))
        col_spin = QSpinBox()
        col_spin.setRange(2, 8)
        col_spin.setValue(self.state.columns)
        col_row.addWidget(col_spin)
        v.addLayout(col_row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.Accepted:
            self.state.theme = theme_combo.currentText()
            self.state.columns = col_spin.value()
            self.apply_theme(self.state.theme)
            self.rebuild()

    def apply_theme(self, theme: str):
        if theme == "dark":
            self.parent().setStyleSheet("""
            QMainWindow { background: #121212; }
            QWidget { color: white; }
            QMenu { background: #1e1e1e; color: white; }
            """)
        else:
            self.parent().setStyleSheet("""
            QMainWindow { background: #ffffff; }
            QWidget { color: #111; }
            QMenu { background: #ffffff; color: #111; }
            """)

class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigManager):
        super().__init__()
        self.cfg = cfg
        self.state = self.cfg.load()
        self.setWindowTitle("Tile Dashboard")
        self.setMinimumSize(720, 480)
        self.grid_widget = TileGrid(self.state, on_change=self._auto_save, parent=self)
        self.setCentralWidget(self.grid_widget)
        self._make_toolbar()
        self.grid_widget.apply_theme(self.state.theme)

    def _make_toolbar(self):
        tb = QToolBar("Toolbar")
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        add_act = QAction("Add Tile", self)
        add_act.triggered.connect(self.add_tile)
        tb.addAction(add_act)
        save_act = QAction("Save", self)
        save_act.triggered.connect(self._auto_save)
        tb.addAction(save_act)
        theme_act = QAction("Toggle Theme", self)
        theme_act.triggered.connect(self.toggle_theme)
        tb.addAction(theme_act)
        cols_act = QAction("Columns +", self)
        cols_act.triggered.connect(lambda: self._change_columns(+1))
        tb.addAction(cols_act)
        cols_act2 = QAction("Columns -", self)
        cols_act2.triggered.connect(lambda: self._change_columns(-1))
        tb.addAction(cols_act2)

    def add_tile(self):
        dlg = TileEditor(parent=self)
        if dlg.exec() == QDialog.Accepted:
            t = dlg.get_tile()
            self.state.tiles.append(t)
            self.grid_widget.rebuild()

    def toggle_theme(self):
        self.state.theme = "light" if self.state.theme == "dark" else "dark"
        self.grid_widget.apply_theme(self.state.theme)
        self._auto_save()

    def _change_columns(self, delta: int):
        self.state.columns = max(2, min(8, self.state.columns + delta))
        self.grid_widget.rebuild()

    def _auto_save(self):
        try:
            self.cfg.save(self.state)
        except Exception as e:
            print("Failed to save:", e)

# ------------------------------ Main ---------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow(ConfigManager(CONFIG_PATH))
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

"""
# ------------------------ Packaging (PyInstaller) ------------------------
# 1) Install dependencies
# python -m pip install --upgrade pip
# pip install PySide6 pyinstaller
#
# 2) Run locally
# python metro_tiles.py
#
# 3) Build a standalone executable (Windows example)
# pyinstaller --noconfirm --windowed --name MetroTiles metro_tiles.py
# The EXE will be in the ./dist/MetroTiles/ directory
#
# For an app icon, add: --icon path/to/icon.ico
# For macOS: use --name "MetroTiles" --icon icon.icns (add --onefile if desired)
# For Linux: similar; may want to package as AppImage with additional tools
#
# 4) Persisted configuration lives at:
# Windows: %APPDATA%\MetroTiles\config.json
# macOS: ~/Library/Application Support/MetroTiles/config.json
# Linux: ~/.config/MetroTiles/config.json
#
# Notes
# - Dragging a tile quickly moves it forward; context menu offers fine reordering.
# - Sizes available: small (1x1), wide (2x1), large (2x2). The packer auto-places them.
# - Built-in tiles: 'clock' (live), 'settings' opens quick settings.
# - You can customize default tiles by editing ConfigManager._default_state().
# - To ship default icons, reference absolute paths or package resources with PyInstaller data files.
"""
