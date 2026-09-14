#!/usr/bin/env /usr/bin/python3
"""
macOS-styled 'About This Mac' dialog for Waybar and Niri.
Authentically matches macOS Monterey / Sonoma / Sequoia styling.
"""

import os
import re
import sys
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen,
    QPainterPath, QPixmap, QKeySequence, QShortcut
)
from PyQt6.QtCore import Qt, QRectF


def get_current_wallpaper():
    cache_path = os.path.expanduser("~/.cache/current_wallpaper")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                p = f.read().strip()
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass
    avatar = os.path.expanduser("~/.config/waybar/avatar.png")
    if os.path.exists(avatar):
        return avatar
    return None


def get_system_specs():
    # Model
    model = "IdeaPad Gaming 3"
    for path in ["/sys/devices/virtual/dmi/id/product_version", "/sys/devices/virtual/dmi/id/product_family"]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    val = f.read().strip()
                    if val and val.lower() != "none":
                        model = val
                        break
            except Exception:
                pass

    # CPU
    cpu = "AMD Ryzen 5 4600H"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    cpu = line.split(":", 1)[1].strip()
                    # Clean up long names
                    cpu = re.sub(r'\(R\)|\(TM\)', '', cpu).strip()
                    break
    except Exception:
        pass

    # RAM
    ram = "16 GB DDR4"
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line:
                    kb = int(re.search(r'\d+', line).group())
                    gb = round(kb / (1024 * 1024))
                    if gb in [15, 16]:
                        ram = "16 GB DDR4"
                    elif gb in [7, 8]:
                        ram = "8 GB DDR4"
                    elif gb in [31, 32]:
                        ram = "32 GB DDR4"
                    else:
                        ram = f"{gb} GB"
                    break
    except Exception:
        pass

    # OS Name and Version
    os_name = "Fedora Linux"
    os_ver = "44"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("NAME="):
                    os_name = line.split("=", 1)[1].strip('"\n')
                elif line.startswith("VERSION_ID="):
                    os_ver = line.split("=", 1)[1].strip('"\n')
    except Exception:
        pass

    # Graphics
    gpus = []
    try:
        out = subprocess.check_output(["lspci"], text=True)
        for line in out.splitlines():
            if "VGA" in line or "3D controller" in line:
                raw_desc = line.lower()
                if "nvidia" in raw_desc:
                    if "1650" in raw_desc or "tu117m" in raw_desc:
                        gpus.append("NVIDIA GeForce GTX 1650 Mobile (4 GB)")
                    else:
                        gpus.append("NVIDIA Dedicated Graphics")
                elif any(k in raw_desc for k in ["amd", "ati", "radeon", "renoir"]):
                    gpus.append("AMD Radeon Vega Graphics")
    except Exception:
        pass
    gpu_str = " / ".join(gpus) if gpus else "AMD Radeon Graphics"

    # Startup disk
    disk = "NVMe SSD (Fedora Linux)"

    return {
        "model": f"Lenovo {model} (15.6-inch)",
        "os_title": f"{os_name}",
        "os_version": f"Version {os_ver} (Workstation Edition • Niri)",
        "processor": cpu,
        "memory": ram,
        "disk": disk,
        "graphics": gpu_str,
    }


class CircularImageWidget(QWidget):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self._pixmap = QPixmap(image_path) if image_path else QPixmap()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        size = min(self.width(), self.height())
        rect = QRectF(
            (self.width() - size) / 2,
            (self.height() - size) / 2,
            size, size
        )

        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.setClipPath(clip)

        if self._pixmap.isNull():
            painter.fillPath(clip, QBrush(QColor(100, 105, 120)))
        else:
            pm = self._pixmap.scaled(
                int(size), int(size),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x = rect.x() + (rect.width() - pm.width()) / 2
            y = rect.y() + (rect.height() - pm.height()) / 2
            painter.drawPixmap(int(x), int(y), pm)

        painter.setClipping(False)
        pen = QPen(QColor(180, 180, 190, 180))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))


class InfoRow(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setFixedWidth(105)
        lbl.setStyleSheet("color: #77777d; font-size: 12px; font-weight: 500;")

        val = QLabel(value)
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        val.setStyleSheet("color: #f0f0f2; font-size: 12px; font-weight: 400;")
        val.setWordWrap(True)

        layout.addWidget(lbl)
        layout.addWidget(val, 1)


class AboutThisMac(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("About This PC")
        self.setFixedSize(540, 325)

        # Allow Escape to close
        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)

        specs = get_system_specs()
        wall_path = get_current_wallpaper()

        # Modern macOS dark / translucent styling
        self.setStyleSheet("""
            QWidget {
                background: #1e1e24;
                color: #e2e2e6;
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Cantarell", sans-serif;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(26, 22, 26, 18)
        main_layout.setSpacing(0)

        # Content row: Image Left, Info Right
        content = QHBoxLayout()
        content.setSpacing(22)

        # Left circular wallpaper thumbnail
        img_widget = CircularImageWidget(wall_path)
        img_container = QVBoxLayout()
        img_container.addSpacerItem(
            QSpacerItem(0, 8, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        )
        img_container.addWidget(img_widget, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        img_container.addStretch()
        content.addLayout(img_container)

        # Right Specs
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        os_title = QLabel(specs["os_title"])
        os_title.setStyleSheet("font-size: 21px; font-weight: 700; color: #ffffff; letter-spacing: -0.4px;")
        info_layout.addWidget(os_title)

        version = QLabel(specs["os_version"])
        version.setStyleSheet("font-size: 12px; color: #9a9aa2; margin-bottom: 8px;")
        info_layout.addWidget(version)
        info_layout.addSpacing(6)

        model_lbl = QLabel(specs["model"])
        model_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #e5e5ea; margin-bottom: 4px;")
        model_lbl.setWordWrap(True)
        info_layout.addWidget(model_lbl)

        spec_rows = [
            ("Processor", specs["processor"]),
            ("Memory", specs["memory"]),
            ("Startup Disk", specs["disk"]),
            ("Graphics", specs["graphics"]),
            ("Serial Number", None),
        ]

        for label, val in spec_rows:
            if val is None:
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 1, 0, 1)
                row_l.setSpacing(8)

                lbl = QLabel(label)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl.setFixedWidth(105)
                lbl.setStyleSheet("color: #77777d; font-size: 12px; font-weight: 500;")

                box = QFrame()
                box.setFixedSize(120, 16)
                box.setStyleSheet("""
                    background: rgba(255, 255, 255, 0.12);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 3px;
                """)
                row_l.addWidget(lbl)
                row_l.addWidget(box)
                row_l.addStretch()
                info_layout.addWidget(row_w)
            else:
                info_layout.addWidget(InfoRow(label, val))

        info_layout.addStretch()
        content.addLayout(info_layout, 1)
        main_layout.addLayout(content, 1)
        main_layout.addSpacing(14)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        btn_report = QPushButton("System Report...")
        btn_report.setFixedHeight(26)
        btn_report.setFixedWidth(130)
        btn_report.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.09);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 5px;
                font-size: 12px;
                font-weight: 500;
                color: #ffffff;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                border-color: rgba(255, 255, 255, 0.35);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.05);
            }
        """)
        btn_report.clicked.connect(self.open_system_report)
        btn_layout.addWidget(btn_report)

        btn_update = QPushButton("Software Update...")
        btn_update.setFixedHeight(26)
        btn_update.setFixedWidth(130)
        btn_update.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.09);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 5px;
                font-size: 12px;
                font-weight: 500;
                color: #ffffff;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                border-color: rgba(255, 255, 255, 0.35);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.05);
            }
        """)
        btn_update.clicked.connect(self.open_software_update)
        btn_layout.addWidget(btn_update)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        main_layout.addSpacing(10)

        # Footer copyright
        copy_lbl = QLabel("™ and © 2026 Niri Linux Desktop. All Rights Reserved.")
        copy_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy_lbl.setStyleSheet("font-size: 10px; color: #6e6e76;")
        main_layout.addWidget(copy_lbl)

    def open_system_report(self):
        self.close()
        subprocess.Popen([
            "/usr/bin/python3",
            os.path.expanduser("~/.config/niri/niri-settings.py"),
            "--page", "about"
        ])

    def open_software_update(self):
        self.close()
        try:
            subprocess.Popen(["gnome-software"])
        except Exception:
            subprocess.Popen(["kitty", "-e", "sudo", "dnf", "upgrade"])


def main():
    app = QApplication(sys.argv)
    window = AboutThisMac()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
