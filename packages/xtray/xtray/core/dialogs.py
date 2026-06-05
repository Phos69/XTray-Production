"""Shared Qt dialogs usable from any package (tray or Computer Manager).

`AdapterInfoDialog` and `NetworkDriveDialog` were originally in xtray.tray
but Computer Manager needs them too (in its Network Adapters / Drives tabs).
Moving them to xtray.core eliminates the
`computer_manager → xtray.tray.dialogs` reverse import, restoring the
cross-package dependency direction.
"""
from __future__ import annotations

from typing import Any

from xtray.core import qt_assets
from xtray.core.theme import DEFAULT_THEME, build_app_stylesheet, theme_by_name


def _current_theme() -> Any:
    """Look up the configured theme. Lives here so xtray.core.dialogs is
    self-contained and does not depend on xtray.tray."""
    try:
        from xtray import config as xtray_config

        return theme_by_name(xtray_config.get_theme_name())
    except Exception:
        return DEFAULT_THEME


class AdapterInfoDialog:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, adapter: Any, parent: Any = None) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        self.adapter = adapter
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle(f"Adapter: {adapter.name}")
        qt_assets.set_window_icon(self.dialog)
        self.dialog.setMinimumWidth(440)
        self.dialog.setStyleSheet(build_app_stylesheet(_current_theme()))

        layout = QVBoxLayout(self.dialog)
        summary = QLabel(
            f"{adapter.description}\nStatus: {adapter.status} | MAC: {adapter.mac_address or '-'}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self.dhcp_check = QCheckBox("Use DHCP")
        self.dhcp_check.setChecked(bool(adapter.dhcp_enabled))
        form.addRow("IPv4", self.dhcp_check)

        self.static_widget = QWidget()
        static_form = QFormLayout(self.static_widget)
        static_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.ip_address = QLineEdit()
        self.ip_address.setPlaceholderText("192.168.1.10")
        self.ip_address.setText(adapter.primary_ipv4 or "")
        static_form.addRow("IP address", self.ip_address)

        self.prefix_length = QSpinBox()
        self.prefix_length.setRange(1, 32)
        self.prefix_length.setValue(int(adapter.primary_prefix_length or 24))
        static_form.addRow("Prefix length", self.prefix_length)

        self.gateway = QLineEdit()
        self.gateway.setPlaceholderText("192.168.1.1")
        self.gateway.setText(adapter.gateway or "")
        static_form.addRow("Gateway", self.gateway)

        self.dns_servers = QLineEdit()
        self.dns_servers.setPlaceholderText("1.1.1.1, 8.8.8.8")
        self.dns_servers.setText(", ".join(adapter.dns_servers))
        static_form.addRow("DNS", self.dns_servers)
        layout.addWidget(self.static_widget)

        self.status = QLabel("")
        self.status.setObjectName("trayPanelStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

        self.dhcp_check.toggled.connect(self._sync_static_fields)
        self._sync_static_fields(self.dhcp_check.isChecked())
        self._message_box = QMessageBox

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def exec(self) -> int:
        return self.dialog.exec()

    def accept(self) -> None:
        if not self.dhcp_check.isChecked() and not self.ip_address.text().strip():
            self.status.setText("IP address is required when DHCP is disabled.")
            return
        answer = self._message_box.question(
            self.dialog,
            "Apply network settings",
            "Apply these adapter settings now? Windows may briefly disconnect the adapter.",
        )
        if answer != self._message_box.StandardButton.Yes:
            return
        self.dialog.accept()

    def ip_settings(self) -> Any:
        from xtray.core.computer_models import AdapterIpSettings

        dns_servers = tuple(
            part.strip()
            for part in self.dns_servers.text().replace(";", ",").split(",")
            if part.strip()
        )
        return AdapterIpSettings(
            dhcp_enabled=self.dhcp_check.isChecked(),
            ip_address=self.ip_address.text().strip() or None,
            prefix_length=self.prefix_length.value(),
            gateway=self.gateway.text().strip() or None,
            dns_servers=dns_servers,
        )

    def _sync_static_fields(self, dhcp_enabled: bool) -> None:
        self.static_widget.setEnabled(not dhcp_enabled)


class NetworkDriveDialog:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, parent: Any = None) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QVBoxLayout,
        )

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Add network drive")
        qt_assets.set_window_icon(self.dialog)
        self.dialog.setMinimumWidth(420)
        self.dialog.setStyleSheet(build_app_stylesheet(_current_theme()))

        layout = QVBoxLayout(self.dialog)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self.letter = QLineEdit()
        self.letter.setMaxLength(2)
        self.letter.setPlaceholderText("Z")
        form.addRow("Drive letter", self.letter)

        self.remote_path = QLineEdit()
        self.remote_path.setPlaceholderText(r"\\server\share")
        form.addRow("UNC path", self.remote_path)

        self.username = QLineEdit()
        self.username.setPlaceholderText(r"DOMAIN\user")
        form.addRow("Username", self.username)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self.password)

        self.persistent = QCheckBox("Reconnect at sign-in")
        self.persistent.setChecked(True)
        form.addRow("Persistence", self.persistent)

        self.status = QLabel("")
        self.status.setObjectName("trayPanelStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def exec(self) -> int:
        return self.dialog.exec()

    def accept(self) -> None:
        if not self.letter.text().strip():
            self.status.setText("Drive letter is required.")
            return
        if not self.remote_path.text().strip().startswith("\\\\"):
            self.status.setText("UNC path must start with \\\\.")
            return
        self.dialog.accept()

    def mapping(self) -> dict[str, Any]:
        return {
            "letter": self.letter.text().strip(),
            "remote_path": self.remote_path.text().strip(),
            "username": self.username.text().strip() or None,
            "password": self.password.text() or None,
            "persistent": self.persistent.isChecked(),
        }


__all__ = ["AdapterInfoDialog", "NetworkDriveDialog"]
