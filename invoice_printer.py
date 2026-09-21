# -*- coding: utf-8 -*-
"""
发票打印助手（A4 纵向，发票置顶）
- 选择目录/文件，批量勾选 PDF 发票
- 选择打印机、每页张数（1 张 / 2 张）、页边距
- 打印预览 / 直接打印
"""
import os
import sys

from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QPainter, QImage, QPixmap, QTransform
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QComboBox, QSpinBox, QCheckBox, QMessageBox, QAbstractItemView, QStatusBar,
    QProgressDialog, QHeaderView,
)
from PyQt5.QtPrintSupport import QPrinter, QPrinterInfo, QPrintPreviewDialog
from PyQt5.QtCore import QMarginsF

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

APP_TITLE = "发票打印助手"
MM_PER_INCH = 25.4

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS


def is_supported_file(path):
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def render_image_file(path):
    """读取图片文件为单页 QImage"""
    img = QImage(path)
    if img.isNull():
        raise ValueError("无法读取图片文件")
    return img.convertToFormat(QImage.Format_RGB888)


def render_pdf_pages(path, dpi=200):
    """把 PDF 的每一页渲染成 QImage，返回 list[QImage]"""
    pages = []
    pdf = pdfium.PdfDocument(path)
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=dpi / 72)
        pil = bitmap.to_pil().convert("RGB")
        data = pil.tobytes("raw", "RGB")
        img = QImage(data, pil.width, pil.height, pil.width * 3, QImage.Format_RGB888)
        pages.append(img.copy())  # copy 脱离原始缓冲区
        page.close()
    pdf.close()
    return pages


def load_document_pages(path, dpi=200):
    """统一入口：PDF 逐页渲染，图片作为单页，返回 list[QImage]"""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return [render_image_file(path)]
    return render_pdf_pages(path, dpi)


def rotate_image_left(img, deg):
    """把图像逆时针（左转）旋转 deg 度，deg 为 90 的倍数"""
    deg = deg % 360
    if deg == 0:
        return img
    # Qt 中 transform.rotate(正角度) 视觉上为顺时针，所以左转用负角度
    return img.transformed(QTransform().rotate(-deg))


# 列表项数据键：UserRole=文件路径，UserRole+1=左转累计角度
ROT_KEY = Qt.UserRole + 1


class InvoicePrinterWindow(QMainWindow):
    def __init__(self, start_dir=None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(760, 620)
        self._pages_cache = []  # list[list[QImage]] 每个文件一页或多页

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ---- 第一行：目录选择 ----
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("发票目录:"))
        self.dir_edit = QLineEdit(start_dir or "")
        row1.addWidget(self.dir_edit, 1)
        self.btn_browse_dir = QPushButton("浏览…")
        self.btn_browse_dir.clicked.connect(self.browse_dir)
        row1.addWidget(self.btn_browse_dir)
        self.chk_recursive = QCheckBox("包含子目录")
        self.chk_recursive.setChecked(True)
        row1.addWidget(self.chk_recursive)
        self.btn_refresh = QPushButton("扫描文件")
        self.btn_refresh.setToolTip("扫描目录下的 PDF 与图片文件")
        self.btn_refresh.clicked.connect(self.scan_pdfs)
        row1.addWidget(self.btn_refresh)
        layout.addLayout(row1)

        # ---- 文件表格：勾选 / 文件名 / 旋转 ----
        layout.addWidget(QLabel("发票文件（勾选要打印的）:"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["打印", "发票文件", "旋转"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(2, 110)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        row_btns = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件…")
        self.btn_add_files.clicked.connect(self.add_files)
        row_btns.addWidget(self.btn_add_files)
        self.btn_sel_all = QPushButton("全选")
        self.btn_sel_all.clicked.connect(lambda: self.set_all_checked(True))
        row_btns.addWidget(self.btn_sel_all)
        self.btn_sel_none = QPushButton("全不选")
        self.btn_sel_none.clicked.connect(lambda: self.set_all_checked(False))
        row_btns.addWidget(self.btn_sel_none)
        self.btn_rot_left = QPushButton("左转 90°")
        self.btn_rot_left.setToolTip("对选中的文件逆时针旋转 90°（可多次点击累计）")
        self.btn_rot_left.clicked.connect(self.rotate_selected_left)
        row_btns.addWidget(self.btn_rot_left)
        self.btn_rot_reset = QPushButton("重置旋转")
        self.btn_rot_reset.clicked.connect(self.reset_selected_rotation)
        row_btns.addWidget(self.btn_rot_reset)
        row_btns.addStretch(1)
        layout.addLayout(row_btns)

        # ---- 打印设置 ----
        grid = QGridLayout()
        grid.addWidget(QLabel("打印机:"), 0, 0)
        self.printer_combo = QComboBox()
        self.printer_combo.setMinimumWidth(280)
        grid.addWidget(self.printer_combo, 0, 1)
        self.btn_refresh_printers = QPushButton("刷新打印机")
        self.btn_refresh_printers.clicked.connect(self.load_printers)
        grid.addWidget(self.btn_refresh_printers, 0, 2)

        grid.addWidget(QLabel("每页发票数:"), 1, 0)
        self.per_page_combo = QComboBox()
        self.per_page_combo.addItem("1 张（发票置顶）", 1)
        self.per_page_combo.addItem("2 张（上下排列）", 2)
        grid.addWidget(self.per_page_combo, 1, 1)

        grid.addWidget(QLabel("页边距 (mm):"), 1, 2)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 30)
        self.margin_spin.setValue(10)
        self.margin_spin.setSuffix(" mm")
        grid.addWidget(self.margin_spin, 1, 3)
        layout.addLayout(grid)

        # ---- 操作按钮 ----
        row_ops = QHBoxLayout()
        row_ops.addStretch(1)
        self.btn_preview = QPushButton("打印预览")
        self.btn_preview.setMinimumHeight(36)
        self.btn_preview.clicked.connect(self.show_preview)
        row_ops.addWidget(self.btn_preview)
        self.btn_print = QPushButton("打  印")
        self.btn_print.setMinimumHeight(36)
        self.btn_print.setDefault(True)
        self.btn_print.clicked.connect(self.do_print)
        row_ops.addWidget(self.btn_print)
        layout.addLayout(row_ops)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.load_printers()
        if start_dir:
            self.scan_pdfs()

    # ---------- 目录与文件 ----------
    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择发票目录", self.dir_edit.text() or os.path.expanduser("~"))
        if d:
            self.dir_edit.setText(d)
            self.scan_pdfs()

    def _rot_of_row(self, row):
        return self.table.item(row, 0).data(ROT_KEY) or 0

    def _set_rot_of_row(self, row, rot):
        rot = rot % 360
        self.table.item(row, 0).setData(ROT_KEY, rot)
        btn = self.table.cellWidget(row, 2)
        if btn:
            btn.setText(f"⟲ {rot}°" if rot else "0°")

    def _append_file_row(self, path):
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        chk.setCheckState(Qt.Checked)
        chk.setData(Qt.UserRole, path)
        chk.setData(ROT_KEY, 0)
        self.table.setItem(row, 0, chk)

        name = QTableWidgetItem(os.path.basename(path))
        name.setToolTip(path)
        self.table.setItem(row, 1, name)

        btn = QPushButton("0°")
        btn.setToolTip("点击将该发票逆时针旋转 90°（可多次点击累计，转 4 次还原）")
        btn.clicked.connect(lambda _=False, r=row: self.rotate_row_left(r))
        self.table.setCellWidget(row, 2, btn)

    def rotate_row_left(self, row):
        self._set_rot_of_row(row, self._rot_of_row(row) + 90)

    def scan_pdfs(self):
        self.table.setRowCount(0)
        root = self.dir_edit.text().strip()
        if not root or not os.path.isdir(root):
            self.status.showMessage("目录无效")
            return
        pdfs = []
        if self.chk_recursive.isChecked():
            for dirpath, _, files in os.walk(root):
                for f in files:
                    if is_supported_file(f):
                        pdfs.append(os.path.join(dirpath, f))
        else:
            for f in os.listdir(root):
                p = os.path.join(root, f)
                if is_supported_file(f) and os.path.isfile(p):
                    pdfs.append(p)
        pdfs.sort(key=lambda p: os.path.basename(p).lower())
        for p in pdfs:
            self._append_file_row(p)
        self.status.showMessage(f"共找到 {len(pdfs)} 个文件，已勾选 {len(pdfs)} 个")

    def add_files(self):
        filters = "支持的文件 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;所有文件 (*)"
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择发票文件", self.dir_edit.text() or os.path.expanduser("~"), filters)
        existing = {p for p, _ in self.checked_files()} | \
                   {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())}
        for p in files:
            if p not in existing:
                self._append_file_row(p)

    def rotate_selected_left(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.status.showMessage("请先在表格中选中要旋转的行")
            return
        for r in rows:
            self.rotate_row_left(r)

    def reset_selected_rotation(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.status.showMessage("请先在表格中选中要重置的行")
            return
        for r in rows:
            self._set_rot_of_row(r, 0)

    def set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def checked_files(self):
        """返回 [(路径, 左转角度), ...]，按表格行顺序"""
        files = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.checkState() == Qt.Checked:
                files.append((item.data(Qt.UserRole), item.data(ROT_KEY) or 0))
        return files

    # ---------- 打印机 ----------
    def load_printers(self):
        self.printer_combo.clear()
        names = QPrinterInfo.availablePrinterNames()
        default = QPrinterInfo.defaultPrinterName()
        for n in names:
            self.printer_combo.addItem(n)
        idx = self.printer_combo.findText(default)
        if idx >= 0:
            self.printer_combo.setCurrentIndex(idx)
        self.status.showMessage(f"发现 {len(names)} 台打印机")

    # ---------- 排版与绘制 ----------
    def collect_pages(self, progress=None):
        """返回所有勾选发票的页图像（展平成一维列表，已按文件应用旋转），失败则弹窗"""
        if pdfium is None:
            QMessageBox.critical(self, APP_TITLE, "缺少 pypdfium2 库，无法读取 PDF。")
            return None
        files = self.checked_files()
        if not files:
            QMessageBox.information(self, APP_TITLE, "请先勾选要打印的发票文件。")
            return None
        pages = []
        errors = []
        if progress:
            progress.setLabelText("正在读取发票文件…")
            progress.setMaximum(len(files))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, (p, rot) in enumerate(files):
                try:
                    for img in load_document_pages(p):
                        pages.append(rotate_image_left(img, rot))
                except Exception as e:
                    errors.append(f"{os.path.basename(p)}: {e}")
                if progress:
                    progress.setValue(i + 1)
                    if progress.wasCanceled():
                        return None
        finally:
            QApplication.restoreOverrideCursor()
        if not pages:
            QMessageBox.warning(self, APP_TITLE, "没有可打印的页面。\n" + "\n".join(errors))
            return None
        if errors:
            QMessageBox.warning(self, APP_TITLE, "以下文件读取失败：\n" + "\n".join(errors))
        return pages

    def paint_invoices(self, printer, pages, progress=None):
        """把发票页按 A4 纵向绘制到 printer 上，发票置顶、等比缩放适配宽度。
        progress 非空时逐张更新进度，用户取消则中止并返回 False。"""
        per_page = self.per_page_combo.currentData()
        margin_mm = self.margin_spin.value()

        a4_w_mm, a4_h_mm = 210.0, 297.0
        # 打印机物理坐标单位：像素
        res = printer.resolution()  # DPI
        pw_px = printer.pageRect(QPrinter.DevicePixel).width()
        ph_px = printer.pageRect(QPrinter.DevicePixel).height()

        mm_to_px = res / MM_PER_INCH
        margin_px = margin_mm * mm_to_px
        paper_w_px = a4_w_mm * mm_to_px
        paper_h_px = a4_h_mm * mm_to_px

        # 每个发票位子的可用区域（置顶；2张时上下各一个位子）
        slot_h = (paper_h_px - margin_px * (per_page + 1)) / per_page
        avail_w = paper_w_px - margin_px * 2
        avail_h = slot_h

        if progress:
            progress.setLabelText("正在打印…")
            progress.setMaximum(len(pages))

        painter = QPainter(printer)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        canceled = False
        for idx, img in enumerate(pages):
            if progress and progress.wasCanceled():
                canceled = True
                break
            slot = idx % per_page
            scale = min(avail_w / img.width(), avail_h / img.height())
            w = img.width() * scale
            h = img.height() * scale
            x = (paper_w_px - w) / 2.0
            y = margin_px + slot * (slot_h + margin_px)
            painter.drawImage(QRectF(x, y, w, h), img)
            if idx % per_page == per_page - 1 and idx != len(pages) - 1:
                printer.newPage()
            if progress:
                progress.setLabelText(f"正在打印 第 {idx + 1}/{len(pages)} 张…")
                progress.setValue(idx + 1)
        painter.end()
        return not canceled

    # ---------- 预览 / 打印 ----------
    def make_printer(self):
        name = self.printer_combo.currentText()
        printer = QPrinter(QPrinter.HighResolution)
        if name:
            printer.setPrinterName(name)
        printer.setPaperSize(QPrinter.A4)
        printer.setOrientation(QPrinter.Portrait)
        printer.setFullPage(True)
        return printer

    def show_preview(self):
        pages = self.collect_pages()
        if pages is None:
            return
        printer = self.make_printer()
        dlg = QPrintPreviewDialog(printer, self)
        dlg.paintRequested.connect(lambda pr: self.paint_invoices(pr, pages))
        dlg.exec_()

    def do_print(self):
        progress = QProgressDialog("正在准备…", "取消打印", 0, 1, self)
        progress.setWindowTitle(APP_TITLE)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        pages = self.collect_pages(progress)
        if pages is None:
            progress.close()
            if progress.wasCanceled():
                self.status.showMessage("已取消打印")
            return

        progress.setLabelText(f"正在打印 第 1/{len(pages)} 张…")
        progress.setValue(0)
        printer = self.make_printer()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self.paint_invoices(printer, pages, progress)
        except Exception as e:
            QMessageBox.critical(self, APP_TITLE, f"打印失败：{e}")
            ok = False
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
        if ok is False and progress.wasCanceled():
            self.status.showMessage("打印已取消（部分页面可能已送出）", 10000)
        elif ok is not False:
            self.status.showMessage(f"已发送到打印机：{printer.printerName()}，共 {len(pages)} 张发票", 10000)


def main():
    if pdfium is None:
        print("缺少 pypdfium2 库")
    app = QApplication(sys.argv)
    start_dir = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
    win = InvoicePrinterWindow(start_dir)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
