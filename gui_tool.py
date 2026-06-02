#!/usr/bin/env python3
import sys
import os
import subprocess
import glob
import shutil
import time
from datetime import datetime
from PySide6 import QtCore, QtWidgets, QtGui


# ======================================================================
#  Utility
# ======================================================================
class SudoExecutor:
    @staticmethod
    def has_pkexec():
        return shutil.which('pkexec') is not None

    @staticmethod
    def run(cmd, parent=None):
        if SudoExecutor.has_pkexec():
            full_cmd = ['pkexec'] + cmd
            result = subprocess.run(full_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or f"Exit code {result.returncode}")
            return result
        else:
            return SudoExecutor._run_with_password_dialog(cmd, parent)

    @staticmethod
    def _run_with_password_dialog(cmd, parent):
        password, ok = QtWidgets.QInputDialog.getText(
            parent, "Sudo Password",
            f"Root access required for:\n{' '.join(cmd)}\n\nEnter sudo password:",
            QtWidgets.QLineEdit.Password)
        if not ok or not password:
            raise RuntimeError("Password entry cancelled.")
        full_cmd = ['sudo', '-S'] + cmd
        result = subprocess.run(full_cmd, input=password + '\n',
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or f"Exit code {result.returncode}")
        return result

    @staticmethod
    def get_password(parent, purpose=""):
        if SudoExecutor.has_pkexec():
            return None
        password, ok = QtWidgets.QInputDialog.getText(
            parent, "Sudo Password",
            f"Root access required{purpose}.\nEnter sudo password:",
            QtWidgets.QLineEdit.Password)
        if not ok or not password:
            return None
        return password + '\n'


# ======================================================================
#  Install Dialog with real-time output
# ======================================================================
class InstallProcessThread(QtCore.QThread):
    output_line = QtCore.Signal(str)
    finished_with = QtCore.Signal(bool, str)
    progress_text = QtCore.Signal(str)

    def __init__(self, cmd, input_data=None, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.input_data = input_data

    def run(self):
        try:
            self.progress_text.emit("Starting installation process...")
            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if self.input_data else None,
                text=True,
                bufsize=1
            )
            if self.input_data:
                proc.stdin.write(self.input_data)
                proc.stdin.close()

            for line in iter(proc.stdout.readline, ''):
                if line:
                    self.output_line.emit(line.rstrip())
                    txt = line.lower()
                    if 'unpacking' in txt:
                        self.progress_text.emit("Unpacking packages...")
                    elif 'setting up' in txt:
                        self.progress_text.emit("Configuring packages...")
                    elif 'downloading' in txt or 'getting' in txt:
                        self.progress_text.emit("Downloading packages...")
                    elif 'processing' in txt:
                        self.progress_text.emit("Processing triggers...")

            proc.wait(timeout=300)
            if proc.returncode == 0:
                self.progress_text.emit("Installation complete.")
                self.finished_with.emit(True, "")
            else:
                self.finished_with.emit(False, f"Process exited with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            self.finished_with.emit(False, "Installation timed out.")
        except Exception as e:
            self.finished_with.emit(False, str(e))


class InstallDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Install Software")
        self.setMinimumSize(850, 620)
        self.resize(850, 620)
        self.search_results = []
        self.thread = None
        self._loop = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_search_tab(), " Search Repositories")
        self.tabs.addTab(self._build_local_tab(), " Install Local Package")
        layout.addWidget(self.tabs, stretch=1)

    # ---------- Search tab ----------
    def _build_search_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(8)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Repository:"))
        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.addItems(["APT", "Snap", "Flatpak"])
        self.source_combo.setMinimumWidth(110)
        top.addWidget(self.source_combo)
        top.addSpacing(10)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search packages (e.g. firefox, vlc, gimp)...")
        self.search_input.setMinimumHeight(32)
        top.addWidget(self.search_input, stretch=1)
        self.search_btn = QtWidgets.QPushButton(" Search")
        self.search_btn.setStyleSheet(
            "background-color: #4a90d9; color: white; font-weight: bold;")
        self.search_btn.setMinimumHeight(32)
        top.addWidget(self.search_btn)
        layout.addLayout(top)

        self.results_model = QtGui.QStandardItemModel()
        self.results_model.setHorizontalHeaderLabels(["Package", "Version", "Description", "Full ID"])
        self.results_table = QtWidgets.QTableView()
        self.results_table.setModel(self.results_model)
        self.results_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setColumnWidth(0, 220)
        self.results_table.setColumnWidth(1, 100)
        self.results_table.setColumnWidth(2, 320)
        self.results_table.setColumnHidden(3, True)
        layout.addWidget(self.results_table, stretch=1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self.status_label)

        self.install_btn = QtWidgets.QPushButton(" Install Selected Package")
        self.install_btn.setStyleSheet(
            "background-color: #5cb85c; color: white; font-weight: bold; font-size: 13px;")
        self.install_btn.setMinimumHeight(40)
        self.install_btn.setEnabled(False)
        install_row = QtWidgets.QHBoxLayout()
        install_row.addStretch()
        install_row.addWidget(self.install_btn)
        install_row.addStretch()
        layout.addLayout(install_row)

        self.search_btn.clicked.connect(self.do_search)
        self.search_input.returnPressed.connect(self.do_search)
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        self.results_table.selectionModel().selectionChanged.connect(
            lambda: self.install_btn.setEnabled(len(self.results_table.selectedIndexes()) > 0))
        self.install_btn.clicked.connect(self.do_install)

        return tab

    # ---------- Local .deb tab ----------
    def _build_local_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(12)

        info = QtWidgets.QLabel(
            "Install a downloaded .deb package file.\n"
            "Dependencies are resolved automatically.")
        info.setStyleSheet("font-size: 13px; color: #555; padding: 10px;")
        layout.addWidget(info)

        file_row = QtWidgets.QHBoxLayout()
        self.deb_path = QtWidgets.QLineEdit()
        self.deb_path.setPlaceholderText("Select a .deb file...")
        self.deb_path.setMinimumHeight(32)
        self.deb_path.setReadOnly(True)
        file_row.addWidget(self.deb_path, stretch=1)
        self.browse_btn = QtWidgets.QPushButton(" Browse...")
        self.browse_btn.setMinimumHeight(32)
        file_row.addWidget(self.browse_btn)
        layout.addLayout(file_row)

        self.deb_info_label = QtWidgets.QLabel("")
        self.deb_info_label.setWordWrap(True)
        self.deb_info_label.setStyleSheet(
            "background: #f5f5f5; padding: 10px; border-radius: 4px;")
        layout.addWidget(self.deb_info_label)

        layout.addStretch()

        self.install_deb_btn = QtWidgets.QPushButton(" Install .deb Package")
        self.install_deb_btn.setStyleSheet(
            "background-color: #5cb85c; color: white; font-weight: bold; font-size: 13px;")
        self.install_deb_btn.setMinimumHeight(40)
        self.install_deb_btn.setEnabled(False)
        deb_btn_row = QtWidgets.QHBoxLayout()
        deb_btn_row.addStretch()
        deb_btn_row.addWidget(self.install_deb_btn)
        deb_btn_row.addStretch()
        layout.addLayout(deb_btn_row)

        self.browse_btn.clicked.connect(self._browse_deb)
        self.install_deb_btn.clicked.connect(self._install_local_deb)

        return tab

    # ---------- Search ----------
    def _on_source_changed(self):
        self.search_results.clear()
        self.results_model.removeRows(0, self.results_model.rowCount())
        self.install_btn.setEnabled(False)
        self.status_label.setText("")

    def do_search(self):
        query = self.search_input.text().strip()
        if not query:
            QtWidgets.QMessageBox.warning(self, "Empty Search", "Enter a search term.")
            return

        source = self.source_combo.currentText()
        self.results_model.removeRows(0, self.results_model.rowCount())
        self.search_results.clear()
        self.install_btn.setEnabled(False)
        self.status_label.setText(f"Searching {source} for '{query}'...")
        QtWidgets.QApplication.processEvents()

        try:
            if source == "APT":
                self._search_apt(query)
            elif source == "Snap":
                self._search_snap(query)
            elif source == "Flatpak":
                self._search_flatpak(query)
            self.status_label.setText(f"Found {len(self.search_results)} result(s) in {source}.")
        except Exception as e:
            self.status_label.setText("Search failed.")
            QtWidgets.QMessageBox.critical(self, "Search Failed", str(e))
            return

        for pkg in self.search_results:
            items = [
                QtGui.QStandardItem(pkg['name']),
                QtGui.QStandardItem(pkg.get('version', '')),
                QtGui.QStandardItem(pkg.get('description', '')),
                QtGui.QStandardItem(pkg.get('full_id', '')),
            ]
            for it in items:
                it.setEditable(False)
            self.results_model.appendRow(items)

        if not self.search_results:
            QtWidgets.QMessageBox.information(self, "No Results",
                f"No packages found for '{query}' in {source}.")

    def _search_apt(self, query):
        r = subprocess.run(['apt-cache', 'search', query], capture_output=True, text=True)
        name_map = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if ' - ' in line:
                name, desc = line.split(' - ', 1)
                name_map[name.strip()] = desc.strip()
        for i, (name, desc) in enumerate(name_map.items()):
            if i >= 150:
                break
            version = ""
            try:
                vr = subprocess.run(['apt-cache', 'policy', name],
                                    capture_output=True, text=True)
                for vline in vr.stdout.splitlines():
                    if 'Candidate:' in vline:
                        version = vline.split(':', 1)[1].strip()
                        break
            except Exception:
                pass
            self.search_results.append({
                'name': name, 'description': desc,
                'version': version, 'full_id': name
            })

    def _search_snap(self, query):
        r = subprocess.run(['snap', 'find', query], capture_output=True, text=True)
        lines = r.stdout.splitlines()
        start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('Name') or line.strip().startswith('---'):
                start = i + 1
        for line in lines[start:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                version = parts[1] if len(parts) > 1 else ''
                desc = ' '.join(parts[2:]) if len(parts) > 2 else ''
                self.search_results.append({
                    'name': name, 'description': desc,
                    'version': version, 'full_id': name
                })

    def _search_flatpak(self, query):
        r = subprocess.run(['flatpak', 'search', query], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if not line.strip() or line.startswith("Name") or line.startswith("Description"):
                continue
            parts = line.split('\t')
            name = parts[0].strip() if len(parts) > 0 else ''
            desc = parts[1].strip() if len(parts) > 1 else ''
            app_id = parts[2].strip() if len(parts) > 2 else name
            version = parts[3].strip() if len(parts) > 3 else ''
            self.search_results.append({
                'name': name, 'description': desc,
                'version': version, 'full_id': app_id
            })

    # ---------- Install with real-time output ----------
    def do_install(self):
        idx = self.results_table.selectedIndexes()
        if not idx:
            return
        row = idx[0].row()
        source = self.source_combo.currentText()

        install_target = self.results_model.item(row, 0).text()
        full_id = self.results_model.item(row, 3).text()
        if full_id:
            install_target = full_id
        version = self.results_model.item(row, 1).text()

        msg = f"Install '{install_target}' from {source}?"
        if version:
            msg += f"\nVersion: {version}"

        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Install", msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        input_data = None
        purpose = f" for installing {install_target}"
        if source == "APT":
            base = ['apt', 'install', '-y', install_target]
            if SudoExecutor.has_pkexec():
                cmd = ['pkexec'] + base
            else:
                pw = SudoExecutor.get_password(self, purpose)
                if pw is None:
                    return
                cmd = ['sudo', '-S'] + base
                input_data = pw
        elif source == "Snap":
            base = ['snap', 'install', install_target]
            if SudoExecutor.has_pkexec():
                cmd = ['pkexec'] + base
            else:
                pw = SudoExecutor.get_password(self, purpose)
                if pw is None:
                    return
                cmd = ['sudo', '-S'] + base
                input_data = pw
        elif source == "Flatpak":
            cmd = ['flatpak', 'install', '-y', install_target]
        else:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unknown source: {source}")
            return

        self._show_progress_dialog(cmd, install_target, input_data=input_data)

    def _install_local_deb(self):
        path = self.deb_path.text().strip()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "No File", "Select a .deb file first.")
            return

        fname = os.path.basename(path)
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Install",
            f"Install local package '{fname}'?\n"
            f"Path: {path}\n\n"
            "Dependencies will be resolved automatically.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        input_data = None
        base = ['apt', 'install', '-y', path]
        if SudoExecutor.has_pkexec():
            cmd = ['pkexec'] + base
        else:
            pw = SudoExecutor.get_password(self, " for .deb install")
            if pw is None:
                return
            cmd = ['sudo', '-S'] + base
            input_data = pw

        self._show_progress_dialog(cmd, fname, is_deb=True, input_data=input_data)

    def _browse_deb(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select .deb Package", "",
            "Debian Packages (*.deb);;All Files (*)")
        if not path:
            return
        self.deb_path.setText(path)
        self.install_deb_btn.setEnabled(True)
        try:
            r = subprocess.run(['dpkg-deb', '--info', path], capture_output=True, text=True)
            info_lines = []
            for line in r.stdout.splitlines():
                if any(k in line for k in ['Package:', 'Version:', 'Description:',
                                            'Maintainer:', 'Architecture:', 'Size:',
                                            'Depends:', 'Section:', 'Priority:']):
                    info_lines.append(line.strip())
            self.deb_info_label.setText('\n'.join(info_lines) if info_lines else
                                        "(no details available)")
        except Exception:
            self.deb_info_label.setText("(could not read package info)")

    # ---------- Progress dialog with live output ----------
    def _show_progress_dialog(self, cmd, display_name, is_deb=False, input_data=None):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Installing: {display_name}")
        dialog.setMinimumSize(700, 400)
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)

        title = QtWidgets.QLabel(f"Installing '{display_name}'...")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self._progress_status = QtWidgets.QLabel("Starting...")
        self._progress_status.setStyleSheet("color: #555;")
        layout.addWidget(self._progress_status)

        self._prog = QtWidgets.QProgressBar()
        self._prog.setRange(0, 0)
        layout.addWidget(self._prog)

        output_label = QtWidgets.QLabel("Installation output:")
        output_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(output_label)

        self._output = QtWidgets.QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(1000)
        self._output.setStyleSheet(
            "font-family: 'Courier New', monospace; font-size: 11px;"
            "background: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self._output, stretch=1)

        self._close_btn = QtWidgets.QPushButton(" Close")
        self._close_btn.setEnabled(False)
        self._close_btn.setMinimumHeight(32)
        self._close_btn.clicked.connect(dialog.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        dialog.show()
        QtWidgets.QApplication.processEvents()

        self.thread = InstallProcessThread(cmd, input_data=input_data)

        def on_output(line):
            self._output.appendPlainText(line)
            scrollbar = self._output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def on_progress(text):
            self._progress_status.setText(text)

        def on_finished(success, error):
            self._prog.setRange(0, 100)
            self._prog.setValue(100)
            self._close_btn.setEnabled(True)
            if success:
                self._progress_status.setText(" Done!")
                self._progress_status.setStyleSheet("color: green; font-weight: bold;")
                if is_deb:
                    self.deb_path.clear()
                    self.deb_info_label.clear()
                    self.install_deb_btn.setEnabled(False)
            else:
                self._progress_status.setText(" Failed!")
                self._progress_status.setStyleSheet("color: red; font-weight: bold;")
                self._output.appendPlainText(f"\nERROR: {error}")

        self.thread.output_line.connect(on_output)
        self.thread.progress_text.connect(on_progress)
        self.thread.finished_with.connect(on_finished)
        self.thread.start()

        loop = QtCore.QEventLoop()
        self.thread.finished_with.connect(loop.quit)
        loop.exec()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(2000)
        super().closeEvent(event)


class CheckUpdatesThread(QtCore.QThread):
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(dict, dict, set)  # apt_updates, snap_updates, flatpak_updates

    def run(self):
        apt_updates = {}
        snap_updates = {}
        flatpak_updates = set()

        # APT
        self.progress.emit("Checking APT updates...")
        try:
            r = subprocess.run(['apt', 'list', '--upgradable', '2>/dev/null'],
                               capture_output=True, text=True, shell=True)
            for line in r.stdout.splitlines():
                line = line.strip()
                if 'upgradable' in line:
                    pkg = line.split('/')[0].strip()
                    apt_updates[pkg] = True
        except Exception:
            pass

        # Snap
        self.progress.emit("Checking Snap updates...")
        try:
            r = subprocess.run(['snap', 'refresh', '--list'],
                               capture_output=True, text=True)
            for line in r.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith('Name') and not line.startswith('---') and not line.startswith('Snap'):
                    parts = line.split()
                    if parts:
                        snap_updates[parts[0]] = True
        except Exception:
            pass

        # Flatpak
        self.progress.emit("Checking Flatpak updates...")
        try:
            r = subprocess.run(['flatpak', 'remote-ls', '--updates'],
                               capture_output=True, text=True)
            for line in r.stdout.splitlines():
                line = line.strip()
                if line and '\t' in line:
                    app_id = line.split('\t')[0].strip()
                    flatpak_updates.add(app_id)
        except Exception:
            pass

        self.finished.emit(apt_updates, snap_updates, flatpak_updates)


# ======================================================================
#  Main Window
# ======================================================================
class AppScannerGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Application Manager")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)

        self.all_packages = []
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Name", "Source", "Status", "Category", "Path"])

        self._build_ui()
        self._connect_signals()

    # ---------- Build UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(5)

        # Top bar: scan group + actions
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setSpacing(8)

        # Scan group
        scan_group = QtWidgets.QGroupBox(" Scan")
        scan_gl = QtWidgets.QHBoxLayout(scan_group)
        scan_gl.setContentsMargins(4, 2, 4, 2)
        scan_gl.setSpacing(4)
        scan_sources = [
            (" APT", self.scan_apt_packages, "#4a90d9"),
            (" Snap", self.scan_snap_packages, "#4a90d9"),
            (" Flatpak", self.scan_flatpak_packages, "#4a90d9"),
            (" Desktop", self.scan_desktop_apps, "#4a90d9"),
            (" AppImage", self.scan_appimages, "#4a90d9"),
            (" /opt", self.scan_opt, "#4a90d9"),
            (" All", self.scan_all, "#2c6fb0"),
        ]
        self._scan_btns = []
        for text, slot, color in scan_sources:
            btn = QtWidgets.QPushButton(text)
            btn.setMinimumHeight(30)
            btn.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;"
                             if color == "#2c6fb0" else "")
            btn.setToolTip(f"Scan {text.strip()} packages")
            btn.clicked.connect(slot)
            scan_gl.addWidget(btn)
            self._scan_btns.append(btn)
        top_bar.addWidget(scan_group)

        # Actions group
        act_group = QtWidgets.QGroupBox(" Actions")
        act_gl = QtWidgets.QHBoxLayout(act_group)
        act_gl.setContentsMargins(4, 2, 4, 2)
        act_gl.setSpacing(4)

        self.install_btn = QtWidgets.QPushButton(" Install")
        self.install_btn.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
        self.install_btn.setMinimumHeight(30)
        self.install_btn.setToolTip("Search and install packages from repositories")
        act_gl.addWidget(self.install_btn)

        self.update_btn = QtWidgets.QPushButton(" Update All")
        self.update_btn.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")
        self.update_btn.setMinimumHeight(30)
        self.update_btn.setToolTip("Update package lists and upgrade all APT packages")
        act_gl.addWidget(self.update_btn)

        self.export_btn = QtWidgets.QPushButton(" Export List")
        self.export_btn.setMinimumHeight(30)
        self.export_btn.setToolTip("Export installed package list to a file")
        act_gl.addWidget(self.export_btn)

        self.check_updates_btn = QtWidgets.QPushButton(" Check Updates")
        self.check_updates_btn.setStyleSheet("background-color: #5bc0de; color: white; font-weight: bold;")
        self.check_updates_btn.setMinimumHeight(30)
        self.check_updates_btn.setToolTip("Check which installed packages have updates available")
        act_gl.addWidget(self.check_updates_btn)

        self.remove_btn = QtWidgets.QPushButton(" Remove Selected")
        self.remove_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
        self.remove_btn.setMinimumHeight(30)
        self.remove_btn.setToolTip("Completely uninstall the selected package")
        act_gl.addWidget(self.remove_btn)

        top_bar.addWidget(act_group)
        main_layout.addLayout(top_bar)

        # Filter bar
        filter_bar = QtWidgets.QHBoxLayout()
        filter_bar.setSpacing(8)
        filter_bar.addWidget(QtWidgets.QLabel("Category:"))
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItems(["All", "System", "User"])
        self.filter_combo.setMinimumWidth(100)
        filter_bar.addWidget(self.filter_combo)

        filter_bar.addWidget(QtWidgets.QLabel(" Search:"))
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Filter by name...")
        self.search_input.setMinimumWidth(200)
        filter_bar.addWidget(self.search_input, stretch=1)

        filter_bar.addWidget(QtWidgets.QLabel("Count:"))
        self.count_label = QtWidgets.QLabel("0")
        self.count_label.setStyleSheet("font-weight: bold;")
        filter_bar.addWidget(self.count_label)

        main_layout.addLayout(filter_bar)

        # Splitter: tree + details
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        # Tree
        self.package_tree = QtWidgets.QTreeView()
        self.package_tree.setModel(self.model)
        self.package_tree.setRootIsDecorated(False)
        self.package_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.package_tree.setAlternatingRowColors(True)
        self.package_tree.setSortingEnabled(True)
        self.package_tree.setColumnWidth(0, 250)
        self.package_tree.setColumnWidth(1, 120)
        self.package_tree.setColumnWidth(2, 90)
        self.package_tree.setColumnWidth(3, 80)
        self.package_tree.setColumnHidden(4, True)
        self.package_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.splitter.addWidget(self.package_tree)

        # Details panel
        self.details_widget = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(4, 2, 4, 2)

        details_header = QtWidgets.QLabel("Package Details")
        details_header.setStyleSheet("font-weight: bold; font-size: 12px; color: #555;")
        details_layout.addWidget(details_header)

        self.details_text = QtWidgets.QTextBrowser()
        self.details_text.setMaximumHeight(120)
        self.details_text.setStyleSheet("background: #f9f9f9; border: 1px solid #ddd;")
        self.details_text.setOpenExternalLinks(False)
        details_layout.addWidget(self.details_text)

        self.splitter.addWidget(self.details_widget)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter, stretch=1)

        # Status bar
        self.status_bar = QtWidgets.QStatusBar()
        self.total_label = QtWidgets.QLabel("Total: 0")
        self.system_label = QtWidgets.QLabel("System: 0")
        self.user_label = QtWidgets.QLabel("User: 0")
        self.sysinfo_label = QtWidgets.QLabel("")
        for lbl in [self.total_label, self.system_label, self.user_label]:
            lbl.setStyleSheet("padding: 2px 8px;")
            self.status_bar.addWidget(lbl)
        self.status_bar.addPermanentWidget(self.sysinfo_label)
        main_layout.addWidget(self.status_bar)

        # Show system info
        self._show_sysinfo()

    def _connect_signals(self):
        self.install_btn.clicked.connect(self.open_install_dialog)
        self.update_btn.clicked.connect(self.update_all_packages)
        self.export_btn.clicked.connect(self.export_package_list)
        self.check_updates_btn.clicked.connect(self.check_updates)
        self.remove_btn.clicked.connect(self.handle_uninstallation)
        self.package_tree.customContextMenuRequested.connect(self._context_menu)
        self.package_tree.selectionModel().selectionChanged.connect(self._show_details)
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        self.search_input.textChanged.connect(self._apply_filter)

    # ---------- System info ----------
    def _show_sysinfo(self):
        info_parts = []
        try:
            r = subprocess.run(['lsb_release', '-ds'], capture_output=True, text=True)
            os_name = r.stdout.strip()
            if os_name:
                info_parts.append(os_name)
        except Exception:
            pass
        try:
            import platform
            info_parts.append(platform.machine())
        except Exception:
            pass
        if info_parts:
            self.sysinfo_label.setText(" | ".join(info_parts))
            self.sysinfo_label.setStyleSheet("color: #888; padding: 2px 8px;")

    # ---------- Data helpers ----------
    def clear_results(self):
        self.model.removeRows(0, self.model.rowCount())
        self.all_packages.clear()

    def add_package(self, name, source, category, path="", status="Unknown"):
        self.all_packages.append({
            'name': name, 'source': source,
            'category': category, 'path': path,
            'status': status
        })

    def _apply_filter(self):
        cat_filter = self.filter_combo.currentText()
        search_text = self.search_input.text().strip().lower()
        filtered = []
        for pkg in self.all_packages:
            if cat_filter != "All" and pkg['category'] != cat_filter:
                continue
            if search_text and search_text not in pkg['name'].lower():
                continue
            filtered.append(pkg)

        self.model.removeRows(0, self.model.rowCount())
        for pkg in filtered:
            items = [
                QtGui.QStandardItem(pkg['name']),
                QtGui.QStandardItem(pkg['source']),
                QtGui.QStandardItem(pkg.get('status', 'Unknown')),
                QtGui.QStandardItem(pkg['category']),
                QtGui.QStandardItem(pkg.get('path', ''))
            ]
            for it in items:
                it.setEditable(False)
            self.model.appendRow(items)

        self.package_tree.resizeColumnToContents(0)
        self._update_status()

    def _update_status(self):
        total = len(self.all_packages)
        system = sum(1 for p in self.all_packages if p['category'] == 'System')
        user = sum(1 for p in self.all_packages if p['category'] == 'User')
        self.total_label.setText(f"Total: {total}")
        self.system_label.setText(f"System: {system}")
        self.user_label.setText(f"User: {user}")
        self.count_label.setText(str(total))

    def _context_menu(self, pos):
        idx = self.package_tree.indexAt(pos)
        if not idx.isValid():
            return
        menu = QtWidgets.QMenu()
        menu.addAction("Remove Package").triggered.connect(self.handle_uninstallation)
        menu.addAction("Copy Name").triggered.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(
                self.model.item(idx.row(), 0).text()))
        menu.exec(self.package_tree.viewport().mapToGlobal(pos))

    def _show_details(self):
        idx = self.package_tree.selectedIndexes()
        if not idx:
            self.details_text.setHtml("")
            return
        row = idx[0].row()
        name = self.model.item(row, 0).text()
        source = self.model.item(row, 1).text()
        status = self.model.item(row, 2).text()
        category = self.model.item(row, 3).text()
        path = self.model.item(row, 4).text()

        html = f"""<table>
<tr><td><b>Name:</b></td><td>{name}</td></tr>
<tr><td><b>Source:</b></td><td>{source}</td></tr>
<tr><td><b>Status:</b></td><td>{status}</td></tr>
<tr><td><b>Category:</b></td><td>{category}</td></tr>
<tr><td><b>Path:</b></td><td>{path or 'N/A'}</td></tr>
</table>"""
        self.details_text.setHtml(html)

    # ---------- Scanners ----------
    def _scan_apt(self):
        r = subprocess.run(['dpkg', '--get-selections'], capture_output=True, text=True)
        c = 0
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == 'install':
                self.add_package(parts[0], 'APT', 'System')
                c += 1
        return c

    def scan_apt_packages(self):
        try:
            self.clear_results()
            c = self._scan_apt()
            self._apply_filter()
            QtWidgets.QMessageBox.information(self, "APT Scan", f"Found {c} APT packages.")
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(self, "Error", "dpkg command not found.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"APT scan failed: {e}")

    def _scan_snap(self):
        r = subprocess.run(['snap', 'list'], capture_output=True, text=True)
        c = 0
        for line in r.stdout.splitlines():
            if not line.strip() or line.strip().startswith("Name"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                self.add_package(parts[0], 'Snap', 'User')
                c += 1
        return c

    def scan_snap_packages(self):
        try:
            self.clear_results()
            c = self._scan_snap()
            self._apply_filter()
            QtWidgets.QMessageBox.information(self, "Snap Scan", f"Found {c} Snap packages.")
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(self, "Error", "snap command not found.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Snap scan failed: {e}")

    def _scan_flatpak(self):
        r = subprocess.run(['flatpak', 'list', '--columns=application'],
                           capture_output=True, text=True)
        c = 0
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("Application ID") or line.startswith("Name"):
                continue
            self.add_package(line, 'Flatpak', 'User')
            c += 1
        return c

    def scan_flatpak_packages(self):
        try:
            self.clear_results()
            c = self._scan_flatpak()
            self._apply_filter()
            QtWidgets.QMessageBox.information(self, "Flatpak Scan", f"Found {c} Flatpak apps.")
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(self, "Error", "flatpak not found.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Flatpak scan failed: {e}")

    def _scan_desktop(self):
        c = 0
        seen = set()
        for d in ['/usr/share/applications', '/usr/local/share/applications',
                   os.path.expanduser('~/.local/share/applications')]:
            if not os.path.isdir(d):
                continue
            for f in glob.glob(os.path.join(d, '*.desktop')):
                try:
                    with open(f, 'r') as fh:
                        content = fh.read()
                    name = None
                    for line in content.splitlines():
                        if line.startswith('Name='):
                            name = line.split('=', 1)[1].strip()
                            break
                    if name and name not in seen:
                        seen.add(name)
                        self.add_package(name, 'Desktop Entry',
                                         'System' if d.startswith('/usr') else 'User', path=f)
                        c += 1
                except Exception:
                    continue
        return c

    def scan_desktop_apps(self):
        self.clear_results()
        c = self._scan_desktop()
        self._apply_filter()
        QtWidgets.QMessageBox.information(self, "Desktop Scan", f"Found {c} desktop applications.")

    def _scan_appimages(self):
        c = 0
        seen = set()
        for d in [os.path.expanduser('~/Applications'), os.path.expanduser('~/bin'),
                   '/opt', '/usr/local/bin']:
            if not os.path.isdir(d):
                continue
            for root, dirs, files in os.walk(d):
                for f in files:
                    if f.endswith('.AppImage') and f not in seen:
                        seen.add(f)
                        self.add_package(f.replace('.AppImage', ''),
                                         'AppImage', 'User', path=os.path.join(root, f))
                        c += 1
        return c

    def scan_appimages(self):
        self.clear_results()
        c = self._scan_appimages()
        self._apply_filter()
        QtWidgets.QMessageBox.information(self, "AppImage Scan", f"Found {c} AppImages.")

    def _scan_opt(self):
        c = 0
        if not os.path.isdir('/opt'):
            return 0
        for entry in os.listdir('/opt'):
            full = os.path.join('/opt', entry)
            if os.path.isdir(full) and not entry.startswith('.'):
                # Avoid double-counting AppImages already found
                if not any(p['name'] == entry and p['source'] == 'AppImage' for p in self.all_packages):
                    self.add_package(entry, '/opt (Manual)', 'System', path=full)
                    c += 1
        return c

    def scan_opt(self):
        self.clear_results()
        if not os.path.isdir('/opt'):
            QtWidgets.QMessageBox.information(self, "/opt Scan", "/opt does not exist.")
            return
        c = self._scan_opt()
        self._apply_filter()
        QtWidgets.QMessageBox.information(self, "/opt Scan", f"Found {c} apps in /opt.")

    # ---------- Scan All ----------
    def scan_all(self):
        self.clear_results()
        total = 0
        for fn in [self._scan_apt, self._scan_snap, self._scan_flatpak,
                    self._scan_desktop, self._scan_appimages, self._scan_opt]:
            try:
                total += fn()
            except Exception:
                pass
        self._apply_filter()
        QtWidgets.QMessageBox.information(self, "Full Scan", f"Found {total} applications.")

    # ---------- Check Updates ----------
    def check_updates(self):
        if not self.all_packages:
            QtWidgets.QMessageBox.warning(self, "No Packages",
                "Scan for packages first, then check for updates.")
            return

        # Reset all statuses
        for pkg in self.all_packages:
            pkg['status'] = 'Checking...'
        self._apply_filter()

        self.progress_dialog = QtWidgets.QProgressDialog(
            "Checking for updates...", "Cancel", 0, 0, self)
        self.progress_dialog.setWindowTitle("Checking Updates")
        self.progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()
        QtWidgets.QApplication.processEvents()

        self.check_thread = CheckUpdatesThread()
        self.check_thread.progress.connect(
            lambda msg: self.progress_dialog.setLabelText(msg))
        self.check_thread.finished.connect(self._on_updates_checked)
        self.check_thread.start()
        self.check_thread.finished.connect(self.progress_dialog.close)

    def _on_updates_checked(self, apt_updates, snap_updates, flatpak_updates):
        apt_count = 0
        snap_count = 0
        fp_count = 0
        for pkg in self.all_packages:
            src = pkg['source']
            name = pkg['name']
            if 'APT' in src:
                pkg['status'] = 'Update available' if name in apt_updates else 'Up-to-date'
                if name in apt_updates:
                    apt_count += 1
            elif 'Snap' in src:
                pkg['status'] = 'Update available' if name in snap_updates else 'Up-to-date'
                if name in snap_updates:
                    snap_count += 1
            elif 'Flatpak' in src:
                full_id = pkg.get('path', '')
                has_update = name in flatpak_updates or full_id in flatpak_updates
                pkg['status'] = 'Update available' if has_update else 'Up-to-date'
                if has_update:
                    fp_count += 1
            else:
                pkg['status'] = 'N/A'

        self._apply_filter()

        total = apt_count + snap_count + fp_count
        if total > 0:
            QtWidgets.QMessageBox.information(self, "Updates Available",
                f"{total} update(s) available:\n"
                f"  APT: {apt_count}\n  Snap: {snap_count}\n  Flatpak: {fp_count}")
        else:
            QtWidgets.QMessageBox.information(self, "All Up-to-date",
                "All packages are up-to-date.")

    # ---------- New features ----------
    def open_install_dialog(self):
        dialog = InstallDialog(self)
        dialog.exec()

    def update_all_packages(self):
        reply = QtWidgets.QMessageBox.question(
            self, "Update All Packages",
            "This will update APT package lists and upgrade all packages.\n"
            "Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        input_data = None
        if SudoExecutor.has_pkexec():
            cmd = ['pkexec', 'sh', '-c', 'apt update && apt upgrade -y && apt autoremove -y']
        else:
            pw = SudoExecutor.get_password(self, " for system update")
            if pw is None:
                return
            cmd = ['sh', '-c', 'apt update && apt upgrade -y && apt autoremove -y']
            input_data = pw

        self._run_system_update(cmd, input_data)

    def _run_system_update(self, cmd, input_data=None):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Updating System Packages")
        dialog.setMinimumSize(700, 400)
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)

        title = QtWidgets.QLabel("Updating APT packages...")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        status = QtWidgets.QLabel("Running update...")
        status.setStyleSheet("color: #555;")
        layout.addWidget(status)

        prog = QtWidgets.QProgressBar()
        prog.setRange(0, 0)
        layout.addWidget(prog)

        output = QtWidgets.QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumBlockCount(1000)
        output.setStyleSheet(
            "font-family: 'Courier New', monospace; font-size: 11px;"
            "background: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(output, stretch=1)

        close_btn = QtWidgets.QPushButton(" Close")
        close_btn.setEnabled(False)
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(dialog.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.show()

        thread = InstallProcessThread(cmd, input_data=input_data)
        thread.output_line.connect(lambda line: (
            output.appendPlainText(line),
            output.verticalScrollBar().setValue(
                output.verticalScrollBar().maximum())
        ))
        thread.progress_text.connect(status.setText)

        def on_done(success, error):
            prog.setRange(0, 100)
            prog.setValue(100)
            close_btn.setEnabled(True)
            if success:
                status.setText(" Update complete!")
                status.setStyleSheet("color: green; font-weight: bold;")
            else:
                status.setText(" Update failed!")
                status.setStyleSheet("color: red; font-weight: bold;")
                output.appendPlainText(f"\nERROR: {error}")

        thread.finished_with.connect(on_done)
        thread.start()

        loop = QtCore.QEventLoop()
        thread.finished_with.connect(loop.quit)
        loop.exec()

    def export_package_list(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Package List",
            os.path.expanduser(f"~/package-list-{datetime.now().strftime('%Y%m%d')}.txt"),
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)")
        if not path:
            return

        try:
            with open(path, 'w') as f:
                f.write(f"# Linux Application Manager - Package List\n")
                f.write(f"# Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total: {len(self.all_packages)}\n\n")
                f.write(f"{'Package':40} {'Source':20} {'Category':10}\n")
                f.write("-" * 70 + "\n")
                for pkg in sorted(self.all_packages, key=lambda x: x['name'].lower()):
                    f.write(f"{pkg['name']:40} {pkg['source']:20} {pkg['category']:10}\n")
            QtWidgets.QMessageBox.information(self, "Export Complete",
                f"Exported {len(self.all_packages)} packages to:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Failed", str(e))

    # ---------- Uninstall ----------
    def handle_uninstallation(self):
        indexes = self.package_tree.selectedIndexes()
        if not indexes:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select a package first.")
            return

        row = indexes[0].row()
        pkg_name = self.model.item(row, 0).text()
        pkg_source = self.model.item(row, 1).text()
        pkg_path = self.model.item(row, 4).text()

        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Removal",
            f"Permanently remove '{pkg_name}'?\n\n"
            f"Source: {pkg_source}\n\n"
            "This will purge config files, orphaned deps, and cached data.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self.status_bar.showMessage(f"Removing '{pkg_name}'...")
        QtWidgets.QApplication.processEvents()

        try:
            if "APT" in pkg_source:
                self._uninstall_apt(pkg_name)
            elif "Snap" in pkg_source:
                self._uninstall_snap(pkg_name)
            elif "Flatpak" in pkg_source:
                self._uninstall_flatpak(pkg_name)
            elif "Desktop" in pkg_source:
                self._uninstall_desktop(pkg_name, pkg_path)
            elif "AppImage" in pkg_source:
                self._uninstall_appimage(pkg_name, pkg_path)
            elif "/opt" in pkg_source:
                self._uninstall_opt(pkg_name, pkg_path)
            else:
                QtWidgets.QMessageBox.critical(self, "Error", f"No method for {pkg_source}")
                return

            leftovers = self._scan_leftovers(pkg_name, pkg_source)
            if leftovers:
                self._show_leftover_dialog(pkg_name, leftovers)
            else:
                QtWidgets.QMessageBox.information(self, "Success",
                    f"'{pkg_name}' removed. No leftover files found.")
            self.clear_results()
            self.status_bar.showMessage("Ready", 3000)

        except Exception as e:
            self.status_bar.showMessage("Removal failed", 3000)
            QtWidgets.QMessageBox.critical(self, "Removal Failed", str(e))

    # ---------- Leftover scan ----------
    def _scan_leftovers(self, name, source):
        leftovers = []
        common_dirs = [
            os.path.expanduser(f'~/.config/{name}'),
            os.path.expanduser(f'~/.{name}'),
            os.path.expanduser(f'~/.local/share/{name}'),
            os.path.expanduser(f'~/.cache/{name}'),
            os.path.expanduser(f'~/.local/state/{name}'),
            f'/etc/{name}',
            f'/var/log/{name}',
            f'/var/lib/{name}',
        ]
        for d in common_dirs:
            if os.path.exists(d):
                sz = self._dir_size(d) if os.path.isdir(d) else os.path.getsize(d)
                leftovers.append({'path': d, 'size': sz,
                                  'type': 'Directory' if os.path.isdir(d) else 'File'})

        if "Snap" in source:
            snap_user = os.path.expanduser(f'~/snap/{name}')
            if os.path.isdir(snap_user):
                leftovers.append({'path': snap_user, 'size': self._dir_size(snap_user),
                                  'type': 'Directory'})

        if "Flatpak" in source:
            fp = os.path.expanduser(f'~/.var/app/{name}')
            if os.path.isdir(fp):
                leftovers.append({'path': fp, 'size': self._dir_size(fp), 'type': 'Directory'})

        if "APT" in source:
            for d in [f'/etc/{name}', f'/var/log/{name}', f'/var/lib/{name}']:
                if os.path.exists(d) and d not in [x['path'] for x in leftovers]:
                    sz = self._dir_size(d) if os.path.isdir(d) else os.path.getsize(d)
                    leftovers.append({'path': d, 'size': sz,
                                      'type': 'Directory' if os.path.isdir(d) else 'File'})

        leftovers.sort(key=lambda x: x['size'], reverse=True)
        return leftovers

    def _dir_size(self, path):
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += self._dir_size(entry.path)
        except Exception:
            pass
        return total

    def _show_leftover_dialog(self, name, leftovers):
        msg = f"Leftover files found for '{name}':\n\n"
        total_size = 0
        for item in leftovers:
            size_kb = item['size'] / 1024
            total_size += item['size']
            if size_kb > 1024:
                size_str = f"{size_kb/1024:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"
            msg += f"  {item['type']}: {item['path']} ({size_str})\n"

        total_mb = total_size / (1024 * 1024)
        msg += f"\nTotal leftover size: {total_mb:.2f} MB"

        reply = QtWidgets.QMessageBox.question(
            self, "Leftover Files", msg + "\n\nDelete all leftover files?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        deleted = 0
        failed = 0
        for item in leftovers:
            try:
                if item['type'] == 'Directory':
                    if item['path'].startswith(('/usr', '/etc', '/var')):
                        SudoExecutor.run(['rm', '-rf', item['path']], self)
                    else:
                        shutil.rmtree(item['path'])
                else:
                    if item['path'].startswith(('/usr', '/etc', '/var')):
                        SudoExecutor.run(['rm', '-f', item['path']], self)
                    else:
                        os.remove(item['path'])
                deleted += 1
            except Exception:
                failed += 1

        if failed:
            QtWidgets.QMessageBox.warning(self, "Cleanup Partial",
                f"Deleted {deleted} items. Failed to delete {failed} items.")
        else:
            QtWidgets.QMessageBox.information(self, "Cleanup Complete",
                f"All {deleted} leftover items deleted successfully.")

    # ---------- Per-type uninstall ----------
    def _uninstall_apt(self, name):
        SudoExecutor.run(['apt', 'purge', '-y', name], self)
        SudoExecutor.run(['apt', 'autoremove', '-y'], self)
        SudoExecutor.run(['apt', 'autoclean'], self)
        r = subprocess.run(['dpkg', '-l'], capture_output=True, text=True)
        residual = []
        for line in r.stdout.splitlines():
            if line.startswith('rc'):
                parts = line.split()
                if len(parts) >= 2:
                    residual.append(parts[1])
        if residual:
            SudoExecutor.run(['apt', 'purge', '-y'] + residual, self)

    def _uninstall_snap(self, name):
        SudoExecutor.run(['snap', 'remove', name], self)
        SudoExecutor.run(['snap', 'list', '--all'], self)
        r = subprocess.run(['snap', 'saved'], capture_output=True, text=True)
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                try:
                    SudoExecutor.run(['snap', 'forget', parts[0]], self)
                except Exception:
                    pass

    def _uninstall_flatpak(self, name):
        subprocess.run(['flatpak', 'uninstall', '-y', name], capture_output=True, text=True)
        subprocess.run(['flatpak', 'uninstall', '--unused', '-y'],
                       capture_output=True, text=True)

    def _uninstall_desktop(self, name, path):
        target = path
        if not target or not os.path.isfile(target):
            target = self._find_desktop_file(name)
        if target:
            if target.startswith('/usr'):
                SudoExecutor.run(['rm', '-f', target], self)
            else:
                os.remove(target)
        else:
            raise FileNotFoundError(f"No .desktop file found for '{name}'.")

    def _find_desktop_file(self, name):
        for d in ['/usr/share/applications', '/usr/local/share/applications',
                   os.path.expanduser('~/.local/share/applications')]:
            if not os.path.isdir(d):
                continue
            for f in glob.glob(os.path.join(d, '*.desktop')):
                try:
                    with open(f, 'r') as fh:
                        if f'Name={name}' in fh.read():
                            return f
                except Exception:
                    continue
        return None

    def _uninstall_appimage(self, name, path):
        target = path
        if not target or not os.path.isfile(target):
            target = self._find_appimage_file(name)
        if target:
            os.remove(target)
        else:
            raise FileNotFoundError(f"No AppImage file found for '{name}'.")

    def _find_appimage_file(self, name):
        for d in [os.path.expanduser('~/Applications'), os.path.expanduser('~/bin'),
                   '/opt', '/usr/local/bin']:
            if not os.path.isdir(d):
                continue
            for root, dirs, files in os.walk(d):
                for f in files:
                    if f.endswith('.AppImage') and f.replace('.AppImage', '') == name:
                        return os.path.join(root, f)
        return None

    def _uninstall_opt(self, name, path):
        target = path if path and os.path.isdir(path) else f'/opt/{name}'
        if os.path.isdir(target):
            SudoExecutor.run(['rm', '-rf', target], self)
        else:
            raise FileNotFoundError(f"Directory '{target}' not found.")


# ======================================================================
#  Entry point
# ======================================================================
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = AppScannerGUI()
    window.show()
    sys.exit(app.exec())
