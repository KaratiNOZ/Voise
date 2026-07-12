@echo off
echo ===================================
echo Voise - Установка зависимостей
echo ===================================
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден!
    echo Установите Python 3.8 или выше с https://www.python.org/
    pause
    exit /b 1
)

echo Python найден!
python --version
echo.

REM Создаем виртуальное окружение
if exist "venv" (
    echo Виртуальное окружение уже существует.
    echo Хотите пересоздать? (Y/N)
    choice /c YN /n
    if errorlevel 2 goto skip_venv
    echo Удаление старого окружения...
    rmdir /s /q venv
)

echo Создание виртуального окружения...
python -m venv venv

:skip_venv

REM Активируем виртуальное окружение
echo Активация виртуального окружения...
call venv\Scripts\activate.bat

REM Обновляем pip и setuptools
echo.
echo Обновление pip и setuptools...
python -m pip install --upgrade pip setuptools wheel

if errorlevel 1 (
    echo ВНИМАНИЕ: Не удалось обновить pip
    echo Продолжаем установку...
)

REM Устанавливаем зависимости
echo.
echo Установка зависимостей...
echo.
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ===================================
    echo ОШИБКА при установке зависимостей!
    echo ===================================
    echo.
    echo Попробуйте установить зависимости вручную:
    echo.
    echo   venv\Scripts\activate
    echo   pip install numpy scipy librosa sounddevice PyQt5 matplotlib
    echo.
    pause
    exit /b 1
)

echo.
echo ===================================
echo Установка завершена успешно!
echo ===================================
echo.
echo Установленные пакеты:
pip list
echo.
echo ===================================
echo Для запуска приложения:
echo ===================================
echo.
echo   Запустите: run.bat
echo   или
echo   1. venv\Scripts\activate
echo   2. python main.py
echo.
pause
