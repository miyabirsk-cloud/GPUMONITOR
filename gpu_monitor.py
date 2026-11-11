#!/usr/bin/env python3
"""A small live AMD GPU monitor for the Linux desktop."""

from __future__ import annotations

import glob
import re
import subprocess
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


COLORS = {
    "dark": {
        "background": "#0b1020",
        "surface": "#111a2e",
        "surface_alt": "#17233a",
        "border": "#25334f",
        "text": "#e8eefc",
        "muted": "#91a0bb",
        "grid": "#293650",
        "accent": "#72e0c1",
        "blue": "#76a9ff",
        "purple": "#bb9aff",
        "orange": "#ffb36b",
    },
    "light": {
        "background": "#f2f5fb",
        "surface": "#ffffff",
        "surface_alt": "#edf2fa",
        "border": "#d9e1ef",
        "text": "#19243a",
        "muted": "#687790",
        "grid": "#e0e7f1",
        "accent": "#087f68",
        "blue": "#356ed0",
        "purple": "#8456ce",
        "orange": "#c36a19",
    },
}


def read_int(path: str | Path) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


class AmdGpu:
    def __init__(self, card_path: str) -> None:
        self.card_path = Path(card_path)
        self.device_path = self.card_path / "device"
        self.card_name = self.card_path.name
        self.hwmon_path = next(
            (Path(path) for path in glob.glob(str(self.device_path / "hwmon" / "hwmon*"))),
            None,
        )
        self.name = self._get_name()

    def _get_name(self) -> str:
        pci_path = str(self.device_path.resolve())
        addresses = re.findall(r"\d{4}:\d{2}:\d{2}\.\d", pci_path)
        if addresses:
            try:
                result = subprocess.run(
                    ["lspci", "-s", addresses[-1]],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().split(": ", 1)[-1]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return f"AMD GPU ({self.card_name})"

    def _sensor(self, filename: str) -> int | None:
        if self.hwmon_path is None:
            return None
        return read_int(self.hwmon_path / filename)

    def snapshot(self) -> dict[str, float | None]:
        busy = read_int(self.device_path / "gpu_busy_percent")
        used = read_int(self.device_path / "mem_info_vram_used")
        total = read_int(self.device_path / "mem_info_vram_total")
        temp = self._sensor("temp1_input")
        fan = self._sensor("fan1_input")
        fan_max = self._sensor("fan1_max")
        power = self._sensor("power1_average")
        if power is None:
            power = self._sensor("power1_input")
        return {
            "gpu": float(busy) if busy is not None else None,
            "vram": min(100.0, used / total * 100.0) if used is not None and total else None,
            "vram_used_gb": used / 1_000_000_000 if used is not None else None,
            "vram_total_gb": total / 1_000_000_000 if total is not None else None,
            "temp": temp / 1000.0 if temp is not None else None,
            "fan_rpm": float(fan) if fan is not None else None,
            "fan_pct": min(100.0, fan / fan_max * 100.0)
            if fan is not None and fan_max
            else None,
            "power": power / 1_000_000.0 if power is not None else None,
        }


class HistoryChart(QWidget):
    def __init__(self, title: str, series_name: str, color_key: str, maximum: float) -> None:
        super().__init__()
        self.title = title
        self.series_name = series_name
        self.color_key = color_key
        self.maximum = maximum
        self.values: deque[float | None] = deque(maxlen=90)
        self.theme = COLORS["dark"]
        self.setMinimumHeight(190)

    def set_theme(self, theme: dict[str, str]) -> None:
        self.theme = theme
        self.update()

    def add_value(self, value: float | None) -> None:
        self.values.append(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(self.theme["border"]), 1))
        painter.setBrush(QColor(self.theme["surface"]))
        painter.drawRoundedRect(rect, 14, 14)

        painter.setPen(QColor(self.theme["text"]))
        painter.setFont(self.font())
        painter.drawText(16, 25, self.title)
        painter.setPen(QColor(self.theme["muted"]))
        painter.drawText(self.width() - 66, 25, f"0–{self.maximum:g}")

        plot = rect.adjusted(42, 42, -16, -24)
        if plot.width() <= 0 or plot.height() <= 0:
            return
        painter.setPen(QPen(QColor(self.theme["grid"]), 1, Qt.PenStyle.DashLine))
        for step in range(4):
            y = plot.top() + plot.height() * step / 3
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        painter.setPen(QColor(self.theme["muted"]))
        painter.drawText(8, int(plot.top() + 5), f"{self.maximum:g}")
        painter.drawText(15, int(plot.bottom() + 4), "0")
        if not self.values:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Collecting live readings…")
            return

        color = QColor(self.theme[self.color_key])
        points: list[tuple[float, float]] = []
        count = len(self.values)
        for index, value in enumerate(self.values):
            if value is None:
                points.append((float("nan"), float("nan")))
                continue
            x = plot.left() + plot.width() * index / max(1, count - 1)
            y = plot.bottom() - plot.height() * min(self.maximum, max(0.0, value)) / self.maximum
            points.append((x, y))

        painter.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path = QPainterPath()
        drawing = False
        for x, y in points:
            if x != x or y != y:
                drawing = False
            elif drawing:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                drawing = True
        painter.drawPath(path)
        last = next(((x, y) for x, y in reversed(points) if x == x and y == y), None)
        if last:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(last[0] - 4), int(last[1] - 4), 8, 8)


class MetricCard(QFrame):
    def __init__(self, title: str, accent: str, show_bar: bool = False) -> None:
        super().__init__()
        self.accent = accent
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(6)
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        self.detail_label = QLabel("Waiting for sensor")
        self.detail_label.setObjectName("metricDetail")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setVisible(show_bar)
        layout.addWidget(self.bar)

    def set_metric(self, value: str, detail: str, percentage: float | None = None) -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        if percentage is not None:
            self.bar.setValue(round(max(0, min(100, percentage))))


class GpuMonitor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GPU Monitor")
        self.resize(1180, 850)
        self.setMinimumSize(820, 650)
        self.gpus = self._discover_gpus()
        self.current_gpu: AmdGpu | None = None
        self.theme_name = "dark"
        self.theme = COLORS[self.theme_name]
        self.history = {
            "gpu": deque(maxlen=90),
            "vram": deque(maxlen=90),
            "temp": deque(maxlen=90),
            "fan_rpm": deque(maxlen=90),
        }
        self._build_ui()
        self._apply_theme()
        self._refresh_gpu_list()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    @staticmethod
    def _discover_gpus() -> list[AmdGpu]:
        cards = []
        for path in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
            device = Path(path) / "device"
            if not (device / "vendor").is_file() or not (device / "gpu_busy_percent").is_file():
                continue
            if (device / "vendor").read_text().strip().lower() == "0x1002":
                cards.append(AmdGpu(path))
        return cards

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("GPU Monitor")
        title.setObjectName("appTitle")
        subtitle = QLabel("Live performance and thermals · updates every 2 seconds")
        subtitle.setObjectName("subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.theme_picker = QComboBox()
        self.theme_picker.addItems(["Dark theme", "Light theme"])
        self.theme_picker.currentIndexChanged.connect(self._change_theme)
        self.theme_picker.setMinimumWidth(140)
        header.addWidget(self.theme_picker)
        root.addLayout(header)

        selection = QFrame()
        selection.setObjectName("selectionCard")
        row = QHBoxLayout(selection)
        row.setContentsMargins(16, 10, 16, 10)
        gpu_label = QLabel("MONITORING")
        gpu_label.setObjectName("eyebrow")
        row.addWidget(gpu_label)
        self.gpu_picker = QComboBox()
        self.gpu_picker.setMinimumWidth(360)
        self.gpu_picker.currentIndexChanged.connect(self._select_gpu)
        row.addWidget(self.gpu_picker, 1)
        self.status_label = QLabel("●  Connected")
        self.status_label.setObjectName("status")
        row.addWidget(self.status_label)
        root.addWidget(selection)

        self.metrics = {
            "gpu": MetricCard("GPU utilization", "accent", True),
            "vram": MetricCard("VRAM usage", "blue", True),
            "temp": MetricCard("GPU temperature", "orange", True),
            "fan": MetricCard("Fan speed", "purple", True),
            "power": MetricCard("Board power", "accent"),
        }
        metric_grid = QGridLayout()
        metric_grid.setSpacing(10)
        for column, key in enumerate(self.metrics):
            metric_grid.addWidget(self.metrics[key], 0, column)
        root.addLayout(metric_grid)

        charts_grid = QGridLayout()
        charts_grid.setSpacing(12)
        self.charts = {
            "gpu": HistoryChart("GPU UTILIZATION", "GPU", "accent", 100),
            "vram": HistoryChart("MEMORY UTILIZATION", "VRAM", "blue", 100),
            "temp": HistoryChart("GPU TEMPERATURE", "Temperature", "orange", 110),
            "fan_rpm": HistoryChart("FAN SPEED", "Fan", "purple", 4000),
        }
        charts_grid.addWidget(self.charts["gpu"], 0, 0)
        charts_grid.addWidget(self.charts["vram"], 0, 1)
        charts_grid.addWidget(self.charts["temp"], 1, 0)
        charts_grid.addWidget(self.charts["fan_rpm"], 1, 1)
        root.addLayout(charts_grid, 1)

        footer = QLabel("Sensor values are read locally from the Linux AMDGPU driver. Fan sensors may be unavailable on some cards.")
        footer.setObjectName("footer")
        root.addWidget(footer)
        self.setCentralWidget(central)

    def _refresh_gpu_list(self) -> None:
        self.gpu_picker.blockSignals(True)
        self.gpu_picker.clear()
        for gpu in self.gpus:
            self.gpu_picker.addItem(gpu.name, gpu.card_name)
        if self.gpus:
            preferred = max(
                range(len(self.gpus)),
                key=lambda index: read_int(
                    self.gpus[index].device_path / "mem_info_vram_total"
                )
                or 0,
            )
            self.current_gpu = self.gpus[preferred]
            self.gpu_picker.setCurrentIndex(preferred)
        else:
            self.status_label.setText("●  No supported AMD GPU found")
        self.gpu_picker.blockSignals(False)

    def _select_gpu(self, index: int) -> None:
        if 0 <= index < len(self.gpus):
            self.current_gpu = self.gpus[index]
            self.history = {key: deque(maxlen=90) for key in self.history}
            for chart in self.charts.values():
                chart.values.clear()
                chart.update()
            self.refresh()

    def _change_theme(self, index: int) -> None:
        self.theme_name = "dark" if index == 0 else "light"
        self.theme = COLORS[self.theme_name]
        self._apply_theme()

    def _apply_theme(self) -> None:
        t = self.theme
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {t['background']}; color: {t['text']}; }}
            QLabel {{ background: transparent; }}
            QLabel#appTitle {{ font-size: 25px; font-weight: 700; }}
            QLabel#subtitle, QLabel#footer, QLabel#metricDetail {{ color: {t['muted']}; }}
            QLabel#subtitle {{ font-size: 12px; }}
            QLabel#footer {{ font-size: 11px; }}
            QLabel#eyebrow, QLabel#metricTitle {{ color: {t['muted']}; font-size: 10px; font-weight: 700; }}
            QLabel#metricValue {{ color: {t['text']}; font-size: 23px; font-weight: 700; }}
            QLabel#metricDetail {{ font-size: 11px; }}
            QLabel#status {{ color: {t['accent']}; font-size: 12px; font-weight: 600; }}
            QFrame#metricCard, QFrame#selectionCard {{
                background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px;
            }}
            QComboBox {{
                background: {t['surface_alt']}; color: {t['text']}; border: 1px solid {t['border']};
                border-radius: 8px; padding: 8px 10px; min-height: 18px;
            }}
            QComboBox QAbstractItemView {{
                background: {t['surface']}; color: {t['text']}; selection-background-color: {t['border']};
            }}
            QProgressBar {{ background: {t['surface_alt']}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}
            """
        )
        for chart in self.charts.values():
            chart.set_theme(t)

    @staticmethod
    def _fmt(value: float | None, suffix: str, precision: int = 0) -> str:
        return f"{value:.{precision}f}{suffix}" if value is not None else "N/A"

    def refresh(self) -> None:
        if self.current_gpu is None:
            self.status_label.setText("●  No supported AMD GPU found")
            return
        data = self.current_gpu.snapshot()
        self.status_label.setText("●  Live")

        self.metrics["gpu"].set_metric(
            self._fmt(data["gpu"], "%"),
            "GPU engine load",
            data["gpu"],
        )
        used, total = data["vram_used_gb"], data["vram_total_gb"]
        memory_detail = f"{used:.1f} / {total:.1f} GB" if used is not None and total else "VRAM sensor unavailable"
        self.metrics["vram"].set_metric(
            self._fmt(data["vram"], "%"),
            memory_detail,
            data["vram"],
        )
        self.metrics["temp"].set_metric(
            self._fmt(data["temp"], "°C"),
            "GPU edge temperature",
            data["temp"] / 110 * 100 if data["temp"] is not None else None,
        )
        fan_rpm = data["fan_rpm"]
        fan_value = self._fmt(fan_rpm, " RPM")
        if fan_rpm == 0:
            fan_detail = "Fan stopped · 0% of maximum speed"
        elif data["fan_pct"] is not None:
            fan_detail = f"{data['fan_pct']:.0f}% of maximum speed"
        else:
            fan_detail = "Fan percentage unavailable"
        self.metrics["fan"].set_metric(fan_value, fan_detail, data["fan_pct"])
        self.metrics["power"].set_metric(self._fmt(data["power"], " W", 1), "GPU board power")

        for key in self.history:
            value = data[key]
            self.history[key].append(value)
            self.charts[key].add_value(value)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GPU Monitor")
    window = GpuMonitor()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
