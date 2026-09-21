# -*- coding: utf-8 -*-
"""离线自测：旋转方向、逐文件旋转、进度回调、排版输出"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QProgressDialog
from PyQt5.QtGui import QImage, QPainter, QColor
from PyQt5.QtCore import Qt
from PyQt5.QtPrintSupport import QPrinter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from invoice_printer import InvoicePrinterWindow, rotate_image_left, ROT_KEY  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
INVOICE_DIR = os.path.join(ROOT, "invoice")

app = QApplication([])

# ---- 1. 旋转方向：100x50 图, 左上角标记红色, 左转90°后应在左下角 ----
src = QImage(100, 50, QImage.Format_RGB32)
src.fill(QColor("white"))
p = QPainter(src)
p.fillRect(0, 0, 10, 10, QColor("red"))     # 左上角
p.fillRect(90, 40, 10, 10, QColor("blue"))  # 右下角
p.end()
rot = rotate_image_left(src, 90)
assert rot.width() == 50 and rot.height() == 100, f"尺寸错误 {rot.width()}x{rot.height()}"
# 逆时针90°: 原左上(0,0) -> 新左下; 原右下 -> 新右上
c = QColor(rot.pixel(3, 97))
assert c.red() > 200 and c.green() < 50, f"旋转方向不对: {c.red()},{c.green()}"
c2 = QColor(rot.pixel(47, 3))
assert c2.blue() > 200 and c2.red() < 50, f"右下->右上验证失败: {c2.red()},{c2.blue()}"
assert rotate_image_left(src, 360).width() == 100, "360° 应还原"
print("PASS 旋转方向: 左上->左下, 右下->右上 (逆时针正确)")

# ---- 2. 窗口: 表格扫描、行旋转按钮、带进度收集页面 ----
win = InvoicePrinterWindow(start_dir=INVOICE_DIR)
assert win.table.rowCount() >= 6, f"应扫描到 PDF 和图片, 实际 {win.table.rowCount()}"
# 图片文件也要能加载
from invoice_printer import load_document_pages  # noqa: E402
png_pages = load_document_pages(os.path.join(INVOICE_DIR, "print_a4_300dpi.png"))
assert len(png_pages) == 1 and not png_pages[0].isNull()
print(f"PASS 图片加载: {png_pages[0].width()}x{png_pages[0].height()}")

win._set_rot_of_row(0, 90)
assert win._rot_of_row(0) == 90
assert win.table.cellWidget(0, 2).text() == "⟲ 90°", win.table.cellWidget(0, 2).text()
win.rotate_row_left(0)          # 90 -> 180
win.rotate_row_left(0)          # 180 -> 270
assert win._rot_of_row(0) == 270
win.rotate_row_left(0)          # 270 -> 0 (转4次还原)
assert win._rot_of_row(0) == 0
assert win.table.cellWidget(0, 2).text() == "0°"
win._set_rot_of_row(0, 90)      # 最终第一个文件左转90°
print("PASS 表格旋转按钮: 0->90->180->270->0 循环正确")

progress = QProgressDialog()
progress.setAutoClose(False)
progress.setAutoReset(False)
pages = win.collect_pages(progress)
assert pages, "collect_pages 返回空"
assert pages[0].height() > pages[0].width(), "旋转后的第一页应为纵向"
checked = win.checked_files()
assert len(checked) == win.table.rowCount() and checked[0][1] == 90
print(f"PASS 勾选收集: {len(checked)} 个文件, 第一个旋转 {checked[0][1]}°, 共 {len(pages)} 页")

# ---- 3. 带进度打印到 PDF ----
printer = QPrinter(QPrinter.HighResolution)
printer.setOutputFormat(QPrinter.PdfFormat)
printer.setOutputFileName(os.path.join(ROOT, "gui_test_rotated.pdf"))
printer.setPaperSize(QPrinter.A4)
printer.setOrientation(QPrinter.Portrait)
printer.setFullPage(True)
ok = win.paint_invoices(printer, pages, progress)
assert ok is True, "paint_invoices 应返回 True"
print("PASS 进度打印: ok =", ok, " progress =", progress.value(), "/", progress.maximum())

print("SELFTEST PASS")
