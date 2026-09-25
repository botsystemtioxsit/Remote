#!/usr/bin/env bash
# Installs phonecast dependencies into a local virtualenv (.venv) and
# downloads scrcpy-server. Run once: ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

missing=()
command -v adb >/dev/null || missing+=("adb")
command -v python3 >/dev/null || missing+=("python3")
python3 -c 'import venv, ensurepip' 2>/dev/null || missing+=("python3-venv")

if ((${#missing[@]})); then
    echo "Не хватает: ${missing[*]}"
    if command -v apt >/dev/null; then
        echo "Установите: sudo apt install adb python3 python3-venv pulseaudio-utils"
    elif command -v dnf >/dev/null; then
        echo "Установите: sudo dnf install android-tools python3 pulseaudio-utils"
    elif command -v pacman >/dev/null; then
        echo "Установите: sudo pacman -S android-tools python libpulse"
    fi
    exit 1
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

# Download and verify scrcpy-server now, so the first launch works offline.
.venv/bin/python -c 'from phonecast.session import ensure_server_file; print("scrcpy-server:", ensure_server_file())'

if ! command -v pacat >/dev/null && ! command -v pw-cat >/dev/null && ! command -v aplay >/dev/null; then
    echo "Внимание: не найден pacat/pw-cat/aplay — звук с телефона воспроизводиться не будет."
fi
if ! command -v wl-paste >/dev/null && ! command -v xclip >/dev/null && ! command -v xsel >/dev/null; then
    echo "Подсказка: установите wl-clipboard (Wayland) или xclip (X11), чтобы работал Ctrl+V."
fi

echo
echo "Готово. Подключите телефон кабелем и запустите: ./phonecast"
