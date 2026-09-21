@echo off
REM 打包成单文件 exe（无控制台窗口）
REM 用法: 先 pip install -r requirements.txt，然后双击本脚本
cd /d "%~dp0"
pyinstaller --noconsole --onefile --name "InvoicePrinter" --clean invoice_printer.py
echo.
echo 打包完成: dist\InvoicePrinter.exe
pause
