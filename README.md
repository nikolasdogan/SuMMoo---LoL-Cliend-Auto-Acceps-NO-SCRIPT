<img width="75%" height="75%" alt="image" src="https://github.com/user-attachments/assets/a8e503a2-4db0-4e42-bffe-f3777bac81ce" />

## Downloads
<img width="25%" height="25%" alt="download_image" src="https://github.com/user-attachments/assets/90da2796-f589-4e30-ada1-73b3507791c5" />

| Architecture    | Windows |
|-----------------|---------|
| x86-64 (64-bit) | [EXE]  |

[EXE]: https://github.com/nikolasdogan/SuMMoo---LoL-Cliend-Auto-Acceps-NO-SCRIPT/releases/download/v0.0.1/LoLAutoPilot.exe

# Summoo Bridge

An open-source utility that allows you to remotely manage the **League of Legends** client (LCU) using chat commands (START, STOP, TRANSFER, BAN, ANNOUNCE), auto-accepting when a match is found and auto-picking if your preference list allows.

## Features
- Lobby & DM commands → real LCU operations
- Auto-accept (accept as soon as the window opens)
- Preferential auto-pick (e.g., shaco, teemo, trundle)
- Telegram push + inline approval when you're marked Busy/Away and someone types **BASLAT** in lobby
- Lightweight, single Python process

## Installation
1) Python 3.10+
2) `pip install -r requirements.txt`
3) Run with League Client open: `python main.py`

> **Note:** The optional UI clicker (auto-accept fallback) relies on Windows-only APIs via `pyautogui` and `pygetwindow`. On Linux/macOS these packages are skipped and the feature is automatically disabled.

### Environment variables
- `AUTO_READY=true|false` (default: true)
- `LOG_LEVEL=INFO|DEBUG`
- `TELEGRAM_BOT_TOKEN=<token>` (optional, required for Telegram bridge)
- `TELEGRAM_OWNER_ID=<chat_id>` (Telegram user ID to receive requests; DM @userinfobot to learn yours)
- `TELEGRAM_FORUM_ID=<threaded_chat_id>` (optional forum/channel thread relay)

## Responsible use
This project is for educational/automation purposes. Do not use it for cheating, harassment, or EULA/ToS violations.
All risks are at the user's expense; check Riot's terms.


# Summoo Bridge

Sohbetten gelen komutlarla (BASLAT, DURDUR, DEVRET, BAN, ANONS) **League of Legends** istemcisini (LCU) uzaktan yönetmenizi, maç bulununca **auto-accept**, tercih listeniz uygunsa **auto-pick** yapmanızı sağlayan açık kaynak bir yardımcı.

## Özellikler
- Lobby & DM komutları → gerçek LCU işlemleri
- Auto-accept (pencere açılır açılmaz kabul)
- Tercihli auto-pick (örn. shaco, teemo, trundle)
- Durumun Meşgul/Uzaktayken lobide biri **BASLAT** yazarsa Telegram'dan onay isteği gönderir
- Hafif, tek Python süreci

## Kurulum
1) Python 3.10+
2) `pip install -r requirements.txt`
3) League Client açıkken çalıştır: `python main.py`

> **Not:** Opsiyonel UI tıklayıcı (auto-accept fallback) `pyautogui` ve `pygetwindow` ile Windows API’lerini kullanır. Linux/macOS ortamlarında bu paketler kurulmaz ve özellik otomatik olarak devre dışı kalır.

### Ortam değişkenleri
- `AUTO_READY=true|false` (varsayılan: true)
- `LOG_LEVEL=INFO|DEBUG`
- `TELEGRAM_BOT_TOKEN=<token>` (isteğe bağlı; Telegram köprüsü için zorunlu)
- `TELEGRAM_OWNER_ID=<kullanıcı_id>` (BASLAT bildirimlerini alacak Telegram kullanıcı ID’si; @userinfobot ile öğrenebilirsin)
- `TELEGRAM_FORUM_ID=<kanal_id>` (isteğe bağlı forum/kanal thread’i)

## Sorumlu kullanım
Bu proje eğitim/otomasyon amaçlıdır. Hile, taciz, EULA/ToS ihlali için kullanmayın.
Tüm riskler kullanıcıya aittir; Riot’un şartlarını kontrol edin.


