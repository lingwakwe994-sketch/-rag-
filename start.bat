@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [RAG] 项目目录: %CD%

set "PYTHON=python"
if exist "..\venv\Scripts\python.exe" (
    set "PYTHON=..\venv\Scripts\python.exe"
    echo [RAG] 使用虚拟环境: %~dp0..\venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
    echo [RAG] 使用虚拟环境: %CD%\venv
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [RAG] 错误: 未找到 Python，请先安装 Python 3.10+ 或创建 venv
        goto :fail
    )
    echo [RAG] 使用系统 Python
)

if not exist "requirements.txt" (
    echo [RAG] 错误: 请在 rag 项目根目录运行此脚本
    goto :fail
)

if not exist "config.json" (
    echo [RAG] 未找到 config.json，从 config.example.json 复制...
    copy /Y "config.example.json" "config.json" >nul
)

if not exist "docs" (
    mkdir "docs" >nul 2>&1
    echo [RAG] 已创建 docs/ 目录
)

"%PYTHON%" -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [RAG] 正在安装 Python 依赖...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [RAG] 依赖安装失败
        goto :fail
    )
)

if not exist "static\index.html" (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [RAG] 错误: 缺少 static/ 前端构建，且未找到 npm
        echo       请安装 Node.js 后执行: cd frontend ^&^& npm install ^&^& npm run build
        goto :fail
    )
    echo [RAG] 正在构建前端...
    pushd frontend
    if not exist "node_modules" (
        call npm install
        if errorlevel 1 goto :pop_fail
    )
    call npm run build
    if errorlevel 1 goto :pop_fail
    popd
    echo [RAG] 前端已输出到 static/
)

echo.
echo [RAG] 启动后端 http://127.0.0.1:8000
echo [RAG] 浏览器访问: http://127.0.0.1:8000
echo [RAG] 按 Ctrl+C 停止服务
echo.

"%PYTHON%" ap.py
if errorlevel 1 (
    echo.
    echo [RAG] 启动失败，请检查上方错误信息
    goto :fail
)
goto :end

:pop_fail
popd
echo [RAG] 前端构建失败
goto :fail

:fail
echo.
pause
exit /b 1

:end
endlocal