#!/usr/bin/env python3
import sys
import os
import subprocess
import glob
import shutil
from PySide6 import QtCore, QtWidgets, QtGui

class SudoExecutor:
    """Handles privilege elevation for system commands."""

    @staticmethod
    def has_pkexec():
        return shutil.which('pkexec') is not None

    @staticmethod
    def run(cmd, parent=None):
        """Run a command that needs root. Uses pkexec if available, else sudo with password dialog."""
        if SudoExecutor.has_pkexec():
            full_cmd = ['pkexec'] + cmd
            result = subprocess.run(full_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or f"Command failed with code {result.returncode}")
            return result
        else:
            return SudoExecutor._run_with_password_dialog(cmd, parent)

    @staticmethod
    def _run_with_password_dialog(cmd, parent):
        password, ok = QtWidgets.QInputDialog.getText(
            parent, "Sudo Password",
            f"Root access required for:\n{' '.join(cmd)}\n\nEnter sudo password:",
            QtWidgets.QLineEdit.Password
        )
        if not ok or not password:
            raise RuntimeError("Password entry cancelled.")

        full_cmd = ['sudo', '-S'] + cmd
        result = subprocess.run(full_cmd, input=password + '\n',
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or f"Command failed with code {result.returncode}")
        return result


class InstallThread(QtCore.QThread):
    completed = QtCore.Signal(bool, str)

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd

    def run(self):
        try:
            result = subprocess.run(self.cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                self.completed.emit(True, "")
            else:
                self.completed.emit(False, result.stderr or f"Exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            self.completed.emit(False, "Installation timed out.")
        except Exception as e:
            self.completed.emit(False, str(e))


class InstallDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Install Software")
        self.setMinimumSize(800, 580)
        self.search_results = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Tab bar: Search / Local Install ---
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_search_tab(), "Search Repositories")
        self.tabs.addTab(self._build_local_tab(), "Install Local Package")
        layout.addWidget(self.tabs, stretch=1)

    # ======================== TAB 1: SEARCH ========================
    def _build_search_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(8)

        # Source selector + search row
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

        # Results table
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

        # Progress + status
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)

        # Install button
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

        # Connections
        self.search_btn.clicked.connect(self.do_search)
        self.search_input.returnPressed.connect(self.do_search)
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        self.results_table.selectionModel().selectionChanged.connect(
            lambda: self.install_btn.setEnabled(
                len(self.results_table.selectedIndexes()) > 0))
        self.install_btn.clicked.connect(self.do_install)

        return tab

    # ======================== TAB 2: LOCAL .deb ========================
    def _build_local_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(15)

        info = QtWidgets.QLabel(
            "Install a downloaded .deb package file.\n"
            "Dependencies will be resolved automatically.")
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

        layout.addSpacing(10)

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

    # ======================== SEARCH METHODS ========================
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
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Searching {source} for '{query}'...")
        self.install_btn.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        try:
            if source == "APT":
                self._search_apt(query)
            elif source == "Snap":
                self._search_snap(query)
            elif source == "Flatpak":
                self._search_flatpak(query)

            self.status_label.setText(
                f"Found {len(self.search_results)} result(s) in {source}.")
        except Exception as e:
            self.status_label.setText("Search failed.")
            QtWidgets.QMessageBox.critical(self, "Search Failed", str(e))
        finally:
            self.progress_bar.setVisible(False)

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
        # apt-cache search gives "name - description"
        r = subprocess.run(['apt-cache', 'search', query], capture_output=True, text=True)
        name_map = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if ' - ' in line:
                name, desc = line.split(' - ', 1)
                name_map[name.strip()] = desc.strip()

        # Get versions for top results using apt-cache policy
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
        # Skip header lines
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

    # ======================== INSTALL METHODS ========================
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

        # Build command
        if source == "APT":
            base = ['apt', 'install', '-y', install_target]
            cmd = ['pkexec'] + base if SudoExecutor.has_pkexec() else ['sudo', '-S'] + base
        elif source == "Snap":
            base = ['snap', 'install', install_target]
            cmd = ['pkexec'] + base if SudoExecutor.has_pkexec() else ['sudo', '-S'] + base
        elif source == "Flatpak":
            cmd = ['flatpak', 'install', '-y', install_target]
        else:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unknown source: {source}")
            return

        self._run_install_threaded(cmd, install_target)

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

        base = ['apt', 'install', '-y', path]
        cmd = ['pkexec'] + base if SudoExecutor.has_pkexec() else ['sudo', '-S'] + base

        self._run_install_threaded(cmd, fname, is_deb=True)

    def _run_install_threaded(self, cmd, display_name, is_deb=False):
        progress = QtWidgets.QProgressDialog(
            f"Installing '{display_name}'...\nPlease wait.", "Cancel", 0, 0, self)
        progress.setWindowTitle("Installing")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        QtWidgets.QApplication.processEvents()

        self.thread = InstallThread(cmd, self)

        def on_complete(success, error):
            progress.close()
            if success:
                QtWidgets.QMessageBox.information(self, "Success",
                    f"'{display_name}' installed successfully.")
                if is_deb:
                    self.deb_path.clear()
                    self.deb_info_label.clear()
                    self.install_deb_btn.setEnabled(False)
                self.accept()
            else:
                QtWidgets.QMessageBox.critical(self, "Install Failed",
                    f"Failed to install '{display_name}'.\nError: {error}")

        self.thread.completed.connect(on_complete)
        self.thread.start()

        while self.thread.isRunning():
            QtWidgets.QApplication.processEvents()
            self.thread.wait(100)


class AppScannerGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux Application Manager")
        self.setGeometry(100, 100, 1200, 700)

        self.all_packages = []
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Name", "Source", "Category", "Path"])

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)

        title = QtWidgets.QLabel("Linux Application Manager")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px;")
        main_layout.addWidget(title)

        # Scan buttons
        btn_frame = QtWidgets.QGroupBox("Scan Sources")
        btn_layout = QtWidgets.QHBoxLayout(btn_frame)

        self.scan_apt_btn = QtWidgets.QPushButton(" APT")
        self.scan_snap_btn = QtWidgets.QPushButton(" Snap")
        self.scan_flatpak_btn = QtWidgets.QPushButton(" Flatpak")
        self.scan_desktop_btn = QtWidgets.QPushButton(" Desktop")
        self.scan_appimage_btn = QtWidgets.QPushButton(" AppImage")
        self.scan_opt_btn = QtWidgets.QPushButton(" /opt")
        for btn in [self.scan_apt_btn, self.scan_snap_btn, self.scan_flatpak_btn,
                     self.scan_desktop_btn, self.scan_appimage_btn, self.scan_opt_btn]:
            btn.setMinimumHeight(32)
            btn_layout.addWidget(btn)

        self.scan_all_btn = QtWidgets.QPushButton(" Scan All")
        self.scan_all_btn.setStyleSheet("background-color: #4a90d9; color: white; font-weight: bold;")
        self.scan_all_btn.setMinimumHeight(32)
        btn_layout.addWidget(self.scan_all_btn)

        self.install_btn = QtWidgets.QPushButton(" Install Packages")
        self.install_btn.setToolTip("Search and install packages from APT or Flatpak repositories")
        self.install_btn.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
        self.install_btn.setMinimumHeight(32)
        btn_layout.addWidget(self.install_btn)

        main_layout.addWidget(btn_frame)

        # Filter & search
        filter_frame = QtWidgets.QWidget()
        filter_layout = QtWidgets.QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(0, 5, 0, 5)

        filter_layout.addWidget(QtWidgets.QLabel("Category:"))
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItems(["All", "System", "User"])
        self.filter_combo.setMinimumWidth(100)
        filter_layout.addWidget(self.filter_combo)

        filter_layout.addWidget(QtWidgets.QLabel("  Search:"))
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Type to filter packages...")
        self.search_input.setMinimumWidth(250)
        filter_layout.addWidget(self.search_input)

        self.remove_btn = QtWidgets.QPushButton(" Remove Selected")
        self.remove_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
        self.remove_btn.setMinimumHeight(30)
        filter_layout.addWidget(self.remove_btn)

        main_layout.addWidget(filter_frame)

        # Tree
        self.package_tree = QtWidgets.QTreeView()
        self.package_tree.setModel(self.model)
        self.package_tree.setRootIsDecorated(False)
        self.package_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.package_tree.setAlternatingRowColors(True)
        self.package_tree.setSortingEnabled(True)
        self.package_tree.setColumnWidth(0, 250)
        self.package_tree.setColumnWidth(1, 120)
        self.package_tree.setColumnWidth(2, 80)
        self.package_tree.setColumnHidden(3, True)
        self.package_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        main_layout.addWidget(self.package_tree, stretch=1)

        # Status bar
        self.status_bar = QtWidgets.QStatusBar()
        self.total_label = QtWidgets.QLabel("Total: 0")
        self.system_label = QtWidgets.QLabel("System: 0")
        self.user_label = QtWidgets.QLabel("User: 0")
        for lbl in [self.total_label, self.system_label, self.user_label]:
            lbl.setStyleSheet("padding: 2px 10px;")
            self.status_bar.addWidget(lbl)
        main_layout.addWidget(self.status_bar)

    def _connect_signals(self):
        self.scan_apt_btn.clicked.connect(self.scan_apt_packages)
        self.scan_snap_btn.clicked.connect(self.scan_snap_packages)
        self.scan_flatpak_btn.clicked.connect(self.scan_flatpak_packages)
        self.scan_desktop_btn.clicked.connect(self.scan_desktop_apps)
        self.scan_appimage_btn.clicked.connect(self.scan_appimages)
        self.scan_opt_btn.clicked.connect(self.scan_opt)
        self.scan_all_btn.clicked.connect(self.scan_all)
        self.install_btn.clicked.connect(self.open_install_dialog)
        self.remove_btn.clicked.connect(self.handle_uninstallation)
        self.package_tree.customContextMenuRequested.connect(self._context_menu)
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        self.search_input.textChanged.connect(self._apply_filter)

    def clear_results(self):
        self.model.removeRows(0, self.model.rowCount())
        self.all_packages.clear()

    def add_package(self, name, source, category, path=""):
        self.all_packages.append({
            'name': name, 'source': source,
            'category': category, 'path': path
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

    def _context_menu(self, pos):
        idx = self.package_tree.indexAt(pos)
        if not idx.isValid():
            return
        menu = QtWidgets.QMenu()
        menu.addAction("Remove Package").triggered.connect(self.handle_uninstallation)
        menu.exec(self.package_tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    #  Scanners
    # ------------------------------------------------------------------
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
                                         'System' if d.startswith('/usr') else 'User',
                                         path=f)
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

    # ------------------------------------------------------------------
    #  Scan All
    # ------------------------------------------------------------------
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

    def open_install_dialog(self):
        dialog = InstallDialog(self)
        dialog.exec()

    # ------------------------------------------------------------------
    #  Clean Uninstall
    # ------------------------------------------------------------------
    def handle_uninstallation(self):
        indexes = self.package_tree.selectedIndexes()
        if not indexes:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select a package first.")
            return

        row = indexes[0].row()
        pkg_name = self.model.item(row, 0).text()
        pkg_source = self.model.item(row, 1).text()
        pkg_path = self.model.item(row, 3).text()

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

    # ------------------------------------------------------------------
    #  Leftover scan after uninstall
    # ------------------------------------------------------------------
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
                leftovers.append({'path': d, 'size': sz, 'type': 'Directory' if os.path.isdir(d) else 'File'})

        if "Snap" in source:
            snap_user = os.path.expanduser(f'~/snap/{name}')
            if os.path.isdir(snap_user):
                leftovers.append({'path': snap_user, 'size': self._dir_size(snap_user), 'type': 'Directory'})

        if "Flatpak" in source:
            flatpak_data = os.path.expanduser(f'~/.var/app/{name}')
            if os.path.isdir(flatpak_data):
                leftovers.append({'path': flatpak_data, 'size': self._dir_size(flatpak_data), 'type': 'Directory'})

        if "APT" in source:
            for d in [f'/etc/{name}', f'/var/log/{name}', f'/var/lib/{name}']:
                if os.path.exists(d) and d not in [x['path'] for x in leftovers]:
                    sz = self._dir_size(d) if os.path.isdir(d) else os.path.getsize(d)
                    leftovers.append({'path': d, 'size': sz, 'type': 'Directory' if os.path.isdir(d) else 'File'})

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
            self, "Leftover Files",
            msg + "\n\nDelete all leftover files?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes)

        if reply != QtWidgets.QMessageBox.Yes:
            return

        deleted = 0
        failed = 0
        for item in leftovers:
            try:
                if item['type'] == 'Directory':
                    if item['path'].startswith('/usr') or item['path'].startswith('/etc') or item['path'].startswith('/var'):
                        SudoExecutor.run(['rm', '-rf', item['path']], self)
                    else:
                        shutil.rmtree(item['path'])
                else:
                    if item['path'].startswith('/usr') or item['path'].startswith('/etc') or item['path'].startswith('/var'):
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

    # ------------------------------------------------------------------
    #  Per-type uninstall with full cleanup
    # ------------------------------------------------------------------
    def _uninstall_apt(self, name):
        SudoExecutor.run(['apt', 'purge', '-y', name], self)
        SudoExecutor.run(['apt', 'autoremove', '-y'], self)
        SudoExecutor.run(['apt', 'autoclean'], self)
        # Remove any residual config packages
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
        # Clean up old snap revisions to free space
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

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = AppScannerGUI()
    window.show()
    sys.exit(app.exec())
