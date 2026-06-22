from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from machine_client.agent import AgentService
from machine_client.config import AppConfig, ControlConfig, ServerConfig, StorageConfig, UploadConfig
from machine_client.validation import validate_config


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, agent: AgentService) -> None:
        super().__init__()
        self._config = config
        self._agent = agent

        self.setWindowTitle(f"Machine Client - {config.machine_id}")
        self.resize(920, 640)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self.tabs.addTab(self._build_account_tab(), "Account")
        self.upload_tab_index = self.tabs.addTab(self._build_upload_tab(), "Upload Settings")
        self.network_tab_index = self.tabs.addTab(self._build_network_tab(), "Network Settings")
        self.storage_tab_index = self.tabs.addTab(self._build_storage_tab(), "Storage Settings")
        self.tabs.addTab(self._build_queue_tab(), "Queue Monitor")
        self.tabs.addTab(self._build_logs_tab(), "Logs")
        self.setCentralWidget(self.tabs)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(1000)
        self._refresh_status()

    def _build_account_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        box = QGroupBox("Operator Access")
        form = QFormLayout(box)
        self.auth_status_label = QLabel()
        self.auth_user_label = QLabel()
        self.auth_role_label = QLabel()
        form.addRow("Login Status", self.auth_status_label)
        form.addRow("Employee ID", self.auth_user_label)
        form.addRow("Role", self.auth_role_label)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self._login)
        self.logout_button = QPushButton("Logout")
        self.logout_button.clicked.connect(self._logout)
        self.change_password_button = QPushButton("Change Password")
        self.change_password_button.clicked.connect(self._change_password)
        self.register_user_button = QPushButton("Register User")
        self.register_user_button.clicked.connect(self._register_user)
        self.reset_password_button = QPushButton("Reset Password")
        self.reset_password_button.clicked.connect(self._reset_password)

        layout.addWidget(box)
        layout.addWidget(self.login_button)
        layout.addWidget(self.logout_button)
        layout.addWidget(self.change_password_button)
        layout.addWidget(self.register_user_button)
        layout.addWidget(self.reset_password_button)
        layout.addStretch(1)
        return widget

    def _build_dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.machine_label = QLabel()
        self.status_label = QLabel()
        self.fps_label = QLabel()
        self.success_label = QLabel()
        self.latency_label = QLabel()
        self.buffer_label = QLabel()
        self.queue_label = QLabel()
        self.note_label = QLabel()

        box = QGroupBox("Machine Status")
        form = QFormLayout(box)
        form.addRow("Machine ID", self.machine_label)
        form.addRow("Status", self.status_label)
        form.addRow("FPS", self.fps_label)
        form.addRow("Upload Success", self.success_label)
        form.addRow("Latency", self.latency_label)
        form.addRow("Buffer", self.buffer_label)
        form.addRow("Queue Growth", self.queue_label)
        form.addRow("Message", self.note_label)

        layout.addWidget(box)
        return widget

    def _build_upload_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 9999)
        self.batch_size.setValue(self._config.upload.batch_size)

        self.interval_sec = QSpinBox()
        self.interval_sec.setRange(1, 60)
        self.interval_sec.setValue(self._config.upload.interval_sec)

        self.retry_count = QSpinBox()
        self.retry_count.setRange(0, 99)
        self.retry_count.setValue(self._config.upload.retry)

        self.compression = QComboBox()
        self.compression.addItems(["webp", "jpeg", "none"])
        self.compression.setCurrentText(self._config.upload.compression)

        self.stage_copy_limit = QSpinBox()
        self.stage_copy_limit.setRange(1, 100000)
        self.stage_copy_limit.setValue(self._config.upload.stage_copy_limit_per_cycle)

        self.index_existing_on_startup_only = QCheckBox("Enable")
        self.index_existing_on_startup_only.setChecked(self._config.upload.index_existing_on_startup_only)

        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self._save_upload_settings)

        layout.addRow("Batch Size", self.batch_size)
        layout.addRow("Interval (sec)", self.interval_sec)
        layout.addRow("Retry Count", self.retry_count)
        layout.addRow("Compression", self.compression)
        layout.addRow("Stage/Copy Limit", self.stage_copy_limit)
        layout.addRow("Index Existing Only On Startup", self.index_existing_on_startup_only)
        layout.addRow(save_button)
        return widget

    def _build_network_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self.server_url = QLineEdit(self._config.server.primary)
        self.backup_server = QLineEdit(self._config.server.backup)
        self.control_server = QLineEdit(self._config.control.base_url)
        self.token = QLineEdit(self._config.server.token)
        self.token.setEchoMode(QLineEdit.Password)
        layout.addRow("Server URL", self.server_url)
        layout.addRow("Backup Server", self.backup_server)
        layout.addRow("Control Server", self.control_server)
        layout.addRow("API Token", self.token)

        self.timeout_sec = QSpinBox()
        self.timeout_sec.setRange(1, 120)
        self.timeout_sec.setValue(self._config.upload.timeout_sec)
        layout.addRow("Timeout (sec)", self.timeout_sec)

        test_button = QPushButton("Test Connection")
        test_button.clicked.connect(self._test_connection)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._save_network_settings)
        layout.addRow(test_button, save_button)
        return widget

    def _build_storage_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self.image_root = QLineEdit(self._config.storage.image_root)
        self.buffer_path = QLineEdit(self._config.storage.buffer_path)
        layout.addRow("Image Root Path", self.image_root)
        layout.addRow("Temp Buffer Path", self.buffer_path)

        self.max_usage = QSpinBox()
        self.max_usage.setRange(1, 95)
        self.max_usage.setValue(self._config.storage.max_usage_percent)
        layout.addRow("Max Disk Usage (%)", self.max_usage)

        self.auto_cleanup = QCheckBox("Enabled")
        self.auto_cleanup.setChecked(self._config.storage.auto_cleanup)
        layout.addRow("Auto Cleanup", self.auto_cleanup)

        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setValue(self._config.storage.retention_days)
        layout.addRow("Retention Days", self.retention)

        browse_button = QPushButton("Browse Folder")
        browse_button.setEnabled(False)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._save_storage_settings)
        layout.addRow(browse_button, save_button)
        return widget

    def _build_queue_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        self.queue_buffer = QLabel()
        self.queue_status = QLabel()
        layout.addRow("Buffered Images", self.queue_buffer)
        layout.addRow("Queue Status", self.queue_status)
        return widget

    def _build_logs_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlainText(
            "[INFO] Client initialized\n"
            "[INFO] Waiting for upload pipeline hook-up\n"
            "[INFO] Local buffer monitoring active"
        )
        layout.addWidget(self.log_view)
        return widget

    def _refresh_status(self) -> None:
        status = self._agent.snapshot()
        self.machine_label.setText(status.machine_id)
        self.status_label.setText(status.message)
        self.auth_status_label.setText("LOGGED IN" if status.authenticated else "LOCKED")
        self.auth_user_label.setText(status.current_user or "--")
        self.auth_role_label.setText(status.current_role or "--")
        self.fps_label.setText(f"{status.fps:.1f}")
        self.success_label.setText(f"{status.upload_success_rate:.1f}%")
        self.latency_label.setText(f"{status.latency_ms} ms")
        self.buffer_label.setText(f"{status.buffer_images} / {status.buffer_capacity} images")
        self.queue_label.setText(f"{status.queue_growth_per_sec:+.1f} / sec")
        self.note_label.setText(status.message)
        self.queue_buffer.setText(f"{status.buffer_images} / {status.buffer_capacity}")
        self.queue_status.setText("STABLE" if status.queue_growth_per_sec <= 0 else "GROWING")
        self.log_view.setPlainText("\n".join(self._agent.log_lines()))
        self._apply_auth_state(status.authenticated, status.current_role)

    def _apply_auth_state(self, authenticated: bool, role: str) -> None:
        for index in [self.upload_tab_index, self.network_tab_index, self.storage_tab_index]:
            self.tabs.setTabEnabled(index, authenticated)
        self.login_button.setEnabled(not authenticated)
        self.logout_button.setEnabled(authenticated)
        self.change_password_button.setEnabled(authenticated)
        is_admin = authenticated and role == "admin"
        self.register_user_button.setEnabled(is_admin)
        self.reset_password_button.setEnabled(is_admin)

    def _build_config(self) -> AppConfig:
        return AppConfig(
            machine_id=self._config.machine_id,
            server=ServerConfig(
                primary=self.server_url.text().strip(),
                backup=self.backup_server.text().strip(),
                token=self.token.text().strip(),
            ),
            control=ControlConfig(
                base_url=self.control_server.text().strip(),
            ),
            storage=StorageConfig(
                image_root=self.image_root.text().strip(),
                buffer_path=self.buffer_path.text().strip(),
                max_usage_percent=self.max_usage.value(),
                auto_cleanup=self.auto_cleanup.isChecked(),
                retention_days=self.retention.value(),
            ),
            upload=UploadConfig(
                batch_size=self.batch_size.value(),
                interval_sec=self.interval_sec.value(),
                retry=self.retry_count.value(),
                compression=self.compression.currentText(),
                timeout_sec=self.timeout_sec.value(),
                stage_copy_limit_per_cycle=self.stage_copy_limit.value(),
                index_existing_on_startup_only=self.index_existing_on_startup_only.isChecked(),
            ),
        )

    def _save_upload_settings(self) -> None:
        self._save_config(require_connection_test=False)

    def _save_storage_settings(self) -> None:
        self._save_config(require_connection_test=False)

    def _save_network_settings(self) -> None:
        self._save_config(require_connection_test=True)

    def _save_config(self, require_connection_test: bool) -> None:
        config = self._build_config()
        errors = self._agent.update_config(config, require_connection_test=require_connection_test)
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        self._config = config
        QMessageBox.information(self, "Saved", "Configuration saved successfully")

    def _login(self) -> None:
        dialog = CredentialsDialog(self, title="Login", include_role=False, include_current_password=False)
        if dialog.exec_() != QDialog.Accepted:
            return
        employee_id, password, _role, _current_password = dialog.values()
        result = self._agent.login_user(employee_id, password)
        if result.ok:
            QMessageBox.information(self, "Login", f"Logged in as {result.employee_id} ({result.role})")
            return
        QMessageBox.critical(self, "Login", result.message)

    def _logout(self) -> None:
        self._agent.logout_user()
        QMessageBox.information(self, "Logout", "Logged out")

    def _change_password(self) -> None:
        dialog = CredentialsDialog(self, title="Change Password", include_role=False, include_current_password=True, employee_id_readonly=True)
        status = self._agent.snapshot()
        dialog.employee_id_input.setText(status.current_user)
        if dialog.exec_() != QDialog.Accepted:
            return
        _employee_id, password, _role, current_password = dialog.values()
        ok, message = self._agent.change_password(current_password, password)
        if ok:
            QMessageBox.information(self, "Change Password", message)
            return
        QMessageBox.critical(self, "Change Password", message)

    def _register_user(self) -> None:
        dialog = CredentialsDialog(self, title="Register User", include_role=True, include_current_password=False)
        if dialog.exec_() != QDialog.Accepted:
            return
        employee_id, password, role, _current_password = dialog.values()
        ok, message = self._agent.register_user(employee_id, employee_id, password, role)
        if ok:
            QMessageBox.information(self, "Register User", message)
            return
        QMessageBox.critical(self, "Register User", message)

    def _reset_password(self) -> None:
        dialog = CredentialsDialog(self, title="Reset Password", include_role=False, include_current_password=False)
        if dialog.exec_() != QDialog.Accepted:
            return
        employee_id, password, _role, _current_password = dialog.values()
        ok, message = self._agent.reset_password(employee_id, password)
        if ok:
            QMessageBox.information(self, "Reset Password", message)
            return
        QMessageBox.critical(self, "Reset Password", message)

    def _test_connection(self) -> None:
        config = self._build_config()
        errors = validate_config(config)
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        result = self._agent.test_connection_for_config(config)
        if result.ok:
            QMessageBox.information(self, "Connection Test", f"Success. Latency: {result.latency_ms} ms")
            return
        QMessageBox.critical(self, "Connection Test", result.message)


def run_app(config: AppConfig, agent: AgentService) -> int:
    app = QApplication([])
    window = MainWindow(config, agent)
    window.show()
    return app.exec_()


class CredentialsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        include_role: bool,
        include_current_password: bool,
        employee_id_readonly: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QFormLayout(self)

        self.employee_id_input = QLineEdit()
        self.employee_id_input.setReadOnly(employee_id_readonly)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addRow("Employee ID", self.employee_id_input)

        self.current_password_input: QLineEdit | None = None
        if include_current_password:
            self.current_password_input = QLineEdit()
            self.current_password_input.setEchoMode(QLineEdit.Password)
            layout.addRow("Current Password", self.current_password_input)

        layout.addRow("Password", self.password_input)

        self.role_input: QComboBox | None = None
        if include_role:
            self.role_input = QComboBox()
            self.role_input.addItems(["operator", "supervisor", "admin"])
            layout.addRow("Role", self.role_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str, str, str]:
        return (
            self.employee_id_input.text().strip(),
            self.password_input.text().strip(),
            self.role_input.currentText() if self.role_input is not None else "operator",
            self.current_password_input.text().strip() if self.current_password_input is not None else "",
        )
