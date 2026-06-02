@echo off
chcp 65001 >nul
echo ========================================
echo  科研文献智能综述系统 - 打包构建
echo ========================================
echo.

REM 检查 PyInstaller 是否安装
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo [安装] PyInstaller...
    pip install pyinstaller
)

REM 安装依赖
echo [安装] 依赖包...
pip install -r ..\requirements.txt -q
pip install -r requirements.txt -q

echo [打包] 开始构建 EXE...
echo.

pyinstaller --onefile --windowed ^
    --name "LiteratureReview" ^
    --add-data "app.html;." ^
    --add-data "..\.env;." ^
    --add-data "..\config;config" ^
    --add-data "..\src;src" ^
    --hidden-import "src" ^
    --hidden-import "src.config" ^
    --hidden-import "src.graph" ^
    --hidden-import "src.agents" ^
    --hidden-import "src.retrieval" ^
    --hidden-import "src.retrieval.sources" ^
    --hidden-import "src.extraction" ^
    --hidden-import "src.analysis" ^
    --hidden-import "src.generation" ^
    --hidden-import "src.storage" ^
    --hidden-import "src.api" ^
    --hidden-import "src.ui" ^
    --hidden-import "sentence_transformers" ^
    --hidden-import "chromadb" ^
    --hidden-import "jieba" ^
    --hidden-import "rank_bm25" ^
    --hidden-import "arxiv" ^
    --hidden-import "pydantic" ^
    --hidden-import "pydantic_settings" ^
    --hidden-import "langchain" ^
    --hidden-import "langchain_openai" ^
    --hidden-import "langchain_core" ^
    --hidden-import "dotenv" ^
    --collect-all "chromadb" ^
    --collect-all "sentence_transformers" ^
    --collect-all "jieba" ^
    --noconsole ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo  构建成功！
    echo  输出: dist\LiteratureReview.exe
    echo ========================================
) else (
    echo.
    echo 构建失败，请检查错误信息
)

pause
