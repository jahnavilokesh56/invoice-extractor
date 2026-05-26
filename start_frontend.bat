@echo off
echo ============================================
echo  Invoice OCR Extractor - Starting Frontend  
echo ============================================
echo.
cd /d "%~dp0\frontend"
echo Installing npm packages...
call npm install
echo.
echo Starting frontend on http://localhost:3000
echo Press Ctrl+C to stop.
echo.
call npm run dev
pause
