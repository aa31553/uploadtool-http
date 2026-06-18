from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QComboBox,
)

from machine_client.agent import AgentService
from machine_client.config import AppConfig, ServerConfig, StorageConfig, UploadConfig
from machine_client.validation import validate_config


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, agent: AgentService) -> None:
        super().__init__()
        self._config = config
        self._agent = agent

        self.setWindowTitle(f"Machine Client - {config.machine_id}")
        self.resize(920, 640)

        tabs = QTabWidget()
        tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        tabs.addTab(self._build_upload_tab(), "Upload Settings")
        tabs.addTab(self._build_network_tab(), "Network Settings")
        tabs.addTab(self._build_storage_tab(), "Storage Settings")
        tabs.addTab(self._build_queue_tab(), "Queue Monitor")
        tabs.addTab(self._build_logs_tab(), "Logs")
        self.setCentralWidget(tabs)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(1000)
        self._refresh_status()

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

        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self._save_upload_settings)

        layout.addRow("Batch Size", self.batch_size)
        layout.addRow("Interval (sec)", self.interval_sec)
        layout.addRow("Retry Count", self.retry_count)
        layout.addRow("Compression", self.compression)
        layout.addRow(save_button)
        return widget

    def _build_network_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self.server_url = QLineEdit(self._config.server.primary)
        self.backup_server = QLineEdit(self._config.server.backup)
        self.token = QLineEdit(self._config.server.token)
        self.token.setEchoMode(QLineEdit.Password)
        layout.addRow("Server URL", self.server_url)
        layout.addRow("Backup Server", self.backup_server)
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
        self.fps_label.setText(f"{status.fps:.1f}")
        self.success_label.setText(f"{status.upload_success_rate:.1f}%")
        self.latency_label.setText(f"{status.latency_ms} ms")
        self.buffer_label.setText(f"{status.buffer_images} / {status.buffer_capacity} images")
        self.queue_label.setText(f"{status.queue_growth_per_sec:+.1f} / sec")
        self.note_label.setText(status.message)
        self.queue_buffer.setText(f"{status.buffer_images} / {status.buffer_capacity}")
        self.queue_status.setText("STABLE" if status.queue_growth_per_sec <= 0 else "GROWING")
        self.log_view.setPlainText("\n".join(self._agent.log_lines()))

    def _build_config(self) -> AppConfig:
        return AppConfig(
            machine_id=self._config.machine_id,
            server=ServerConfig(
                primary=self.server_url.text().strip(),
                backup=self.backup_server.text().strip(),
                token=self.token.text().strip(),
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
