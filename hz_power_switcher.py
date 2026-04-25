from __future__ import annotations

# =========================================================
# Hz Power Switcher
# App Windows para alternar a frequência do ecrã consoante
# o estado da alimentação (bateria / corrente).
# =========================================================

import ctypes
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

try:
    import pystray
except Exception:  # pragma: no cover
    pystray = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFont = None


# =========================================================
# Constantes e caminhos
# =========================================================

APP_NAME = "Hz Power Switcher"  
APP_FOLDER = "HzPowerSwitcher"
CONFIG_FILENAME = "config.json"
CACHE_FILENAME = "cache.json"
LOG_FILENAME = "app.log"
STARTUP_VALUE_NAME = APP_NAME.replace(" ", "")

# Intervalo de polling de segurança (o evento WM_POWERBROADCAST é o mecanismo principal)
CHECK_INTERVAL_SECONDS = 30.0
# Janela de debounce para colapsar pedidos de reavaliação muito próximos (ms)
RECHECK_DEBOUNCE_MS = 300
# Cooldown após apply: polling ignora re-triggers neste período (segundos)
RECHECK_COOLDOWN_S  = 4.0
STARTUP_INITIAL_SYNC_DELAY_SECONDS = 1.2
STARTUP_SECOND_VERIFICATION_DELAY_SECONDS = 2.8

ENUM_CURRENT_SETTINGS = -1
ENUM_REGISTRY_SETTINGS = -2

DM_DISPLAYFREQUENCY = 0x400000
DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_UPDATEREGISTRY = 0x00000001
CDS_GLOBAL = 0x00000008

CDS_TEST = 0x00000002                      # testa modo sem aplicar
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS        = 0x00000020
WM_POWERBROADCAST            = 0x0218
PBT_APMPOWERSTATUSCHANGE     = 0x000A      # mudança AC/bateria
GWLP_WNDPROC                 = -4
EDS_RAWMODE                  = 0x00000002  # modos raw do driver

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

WM_DELETE_WINDOW = "WM_DELETE_WINDOW"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

SINGLE_INSTANCE_MUTEX_NAME = r"Local\HzPowerSwitcherSingleInstance"
_SINGLE_INSTANCE_MUTEX_HANDLE = None


# =========================================================
# Estruturas Win32
# =========================================================

CCHDEVICENAME = 32
CCHFORMNAME = 32


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_uint32),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * CCHDEVICENAME),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_uint32),
        ("dmPositionX", ctypes.c_int32),
        ("dmPositionY", ctypes.c_int32),
        ("dmDisplayOrientation", ctypes.c_uint32),
        ("dmDisplayFixedOutput", ctypes.c_uint32),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * CCHFORMNAME),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_uint32),
        ("dmPelsWidth", ctypes.c_uint32),
        ("dmPelsHeight", ctypes.c_uint32),
        ("dmDisplayFlags", ctypes.c_uint32),
        ("dmDisplayFrequency", ctypes.c_uint32),
        ("dmICMMethod", ctypes.c_uint32),
        ("dmICMIntent", ctypes.c_uint32),
        ("dmMediaType", ctypes.c_uint32),
        ("dmDitherType", ctypes.c_uint32),
        ("dmReserved1", ctypes.c_uint32),
        ("dmReserved2", ctypes.c_uint32),
        ("dmPanningWidth", ctypes.c_uint32),
        ("dmPanningHeight", ctypes.c_uint32),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_uint32),
        ("BatteryFullLifeTime", ctypes.c_uint32),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumDisplayDevicesW = user32.EnumDisplayDevicesW    
EnumDisplayDevicesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(DISPLAY_DEVICEW), ctypes.c_uint32]
EnumDisplayDevicesW.restype = ctypes.c_int

EnumDisplaySettingsExW = user32.EnumDisplaySettingsExW
EnumDisplaySettingsExW.argtypes = [ctypes.c_wchar_p, ctypes.c_int32, ctypes.POINTER(DEVMODEW), ctypes.c_uint32]
EnumDisplaySettingsExW.restype = ctypes.c_int

ChangeDisplaySettingsExW = user32.ChangeDisplaySettingsExW
ChangeDisplaySettingsExW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(DEVMODEW), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
ChangeDisplaySettingsExW.restype = ctypes.c_int

GetSystemPowerStatus = kernel32.GetSystemPowerStatus
GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
GetSystemPowerStatus.restype = ctypes.c_int

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.argtypes = []
GetCurrentProcess.restype = ctypes.c_void_p

SetPriorityClass = kernel32.SetPriorityClass
SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
SetPriorityClass.restype = ctypes.c_int

GetProcessAffinityMask = kernel32.GetProcessAffinityMask
GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
GetProcessAffinityMask.restype = ctypes.c_int

SetProcessAffinityMask = kernel32.SetProcessAffinityMask
SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
SetProcessAffinityMask.restype = ctypes.c_int

CreateMutexW = kernel32.CreateMutexW
CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
CreateMutexW.restype = ctypes.c_void_p

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.c_void_p]
CloseHandle.restype = ctypes.c_int

FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
FindWindowW.restype = ctypes.c_void_p

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
ShowWindow.restype = ctypes.c_int

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [ctypes.c_void_p]
SetForegroundWindow.restype = ctypes.c_int

# WndProc subclassing para WM_POWERBROADCAST (64-bit; fallback 32-bit)
_CallWindowProcW = user32.CallWindowProcW
_CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
_CallWindowProcW.restype = ctypes.c_ssize_t

try:
    _SetWindowLongPtrW = ctypes.windll.user32.SetWindowLongPtrW
except AttributeError:
    _SetWindowLongPtrW = ctypes.windll.user32.SetWindowLongW
_SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_SetWindowLongPtrW.restype = ctypes.c_void_p


# =========================================================
# Modelos de dados
# =========================================================

@dataclass
class DisplayInfo:
    device_name: str
    device_label: str
    width: int
    height: int
    bits_per_pixel: int
    current_hz: int
    is_primary: bool

    @property
    def title(self) -> str:
        tag = "Primário" if self.is_primary else "Secundário"
        return f"{self.device_label} | {self.width}x{self.height} | {self.current_hz} Hz | {tag}"


@dataclass
class AppConfig:
    selected_display: str = ""
    ac_hz: int = 0
    battery_hz: int = 0
    autostart_enabled: bool = False
    start_minimized: bool = True
    monitoring_enabled: bool = True
    minimize_to_tray_on_close: bool = True
    # custom_hz_map: frequências custom validadas por contexto (device + resolução).
    # Chave: "<device_name>||<WxH>"  (ex: "\\.\\DISPLAY1||1920x1080")
    # Valor: lista ordenada de Hz validados (CDS_TEST confirmado) para esse contexto.
    # Não contaminam outros ecrãs nem outras resoluções.
    custom_hz_map: dict = field(default_factory=dict)
    low_priority: bool = True          # prioridade BELOW_NORMAL por defeito
    single_core_affinity: bool = True  # afinidade a 1 núcleo por defeito


@dataclass
class RefreshRateVerificationResult:
    """Resultado detalhado da aplicação e verificação de frequência."""
    requested_hz: int
    resolved_hz: int
    effective_before: int
    effective_after: int
    win32_result: int
    verified: bool
    verification_attempts: int
    readings: list[int] = field(default_factory=list)  # Hz lidos em cada verificação
    attempted_retry: bool = False
    fallback_applied: bool = False
    error_message: str = ""

    def is_success(self) -> bool:
        """Sucesso real: aplicado E confirmado."""
        return self.win32_result in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART) and self.verified

    def is_applied_unconfirmed(self) -> bool:
        """Aplicado segundo Win32, mas não confirmado pela leitura."""
        return self.win32_result in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART) and not self.verified

    def short_status(self) -> str:
        if self.is_success():
            return "aplicado e confirmado"
        elif self.is_applied_unconfirmed():
            return "aplicado mas não confirmado"
        elif self.fallback_applied:
            return "fallback aplicado"
        else:
            return "falha real"


@dataclass
class RuntimeCache:
    selected_display: str = ""
    ac_hz: int = 0
    battery_hz: int = 0
    last_power_source: str = ""
    requested_hz: int = 0
    resolved_hz: int = 0
    effective_hz: int = 0
    last_applied_hz: int = 0
    last_app_status: str = ""
    last_diagnostic: str = ""
    last_verification_status: str = ""  # novo: status de verificação (aplicado/confirmado/fallback/falha)
    last_update_iso: str = ""


# =========================================================
# Chave de contexto para frequências custom
# =========================================================

def _custom_context_key(device_name: str, width: int, height: int) -> str:
    """Gera a chave de contexto para custom_hz_map: device + resolução.

    Duas entradas são o mesmo contexto se e só se o device_name,
    a largura e a altura coincidirem. O bpp não é incluído porque
    a enumeração de modos suportados também ignora bpp por defeito,
    o que maximiza a compatibilidade.
    """
    return f"{device_name}||{width}x{height}"


# =========================================================
# Utilitários
# =========================================================

def get_app_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    Path(path / CONFIG_FILENAME).touch(exist_ok=True)
    Path(path / CACHE_FILENAME).touch(exist_ok=True)
    Path(path / LOG_FILENAME).touch(exist_ok=True)
    return path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / CONFIG_FILENAME
CACHE_PATH = APP_DIR / CACHE_FILENAME
LOG_PATH = APP_DIR / LOG_FILENAME
ICON_PATH = get_base_dir() / "hz_power_switcher.ico"

# Guarda a máscara de afinidade observada antes de qualquer restrição explícita.
_PROCESS_ALLOWED_AFFINITY_MASK: int | None = None


logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def log_info(message: str) -> None:
    logging.info(message)


def log_error(message: str) -> None:
    logging.error(message)


def acquire_single_instance_lock(reveal_existing: bool) -> bool:
    """Garante uma única instância ativa."""
    global _SINGLE_INSTANCE_MUTEX_HANDLE

    handle = CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if not handle:
        log_error("Instância única: falha ao criar mutex.")
        return True

    _SINGLE_INSTANCE_MUTEX_HANDLE = handle
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        log_info("Instância única: mutex adquirido.")
        return True

    log_info("Instância duplicada detetada.")
    if reveal_existing:
        try:
            hwnd = FindWindowW(None, APP_NAME)
            if hwnd:
                ShowWindow(hwnd, SW_RESTORE)
                SetForegroundWindow(hwnd)
                log_info("Instância existente restaurada.")
            else:
                log_info("Instância existente não encontrada para restaurar.")
        except Exception as exc:
            log_error(f"Falha ao restaurar instância existente: {exc}")

    try:
        CloseHandle(handle)
    except Exception:
        pass
    _SINGLE_INSTANCE_MUTEX_HANDLE = None
    return False


def release_single_instance_lock() -> None:
    global _SINGLE_INSTANCE_MUTEX_HANDLE

    if _SINGLE_INSTANCE_MUTEX_HANDLE is None:
        return
    try:
        CloseHandle(_SINGLE_INSTANCE_MUTEX_HANDLE)
    except Exception:
        pass
    _SINGLE_INSTANCE_MUTEX_HANDLE = None


def _write_json_if_changed(path: Path, data: dict) -> bool:
    """Escreve JSON apenas quando o conteúdo muda para reduzir I/O e desgaste."""
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        current = ""

    if current == serialized:
        return False

    path.write_text(serialized, encoding="utf-8")
    return True


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            config = AppConfig()
            save_config(config)
            return config
        data = json.loads(raw)
        # Filtra chaves desconhecidas para compatibilidade com configs antigas/novas
        known = {f.name for f in fields(AppConfig)}
        filtered = {k: v for k, v in data.items() if k in known}
        return AppConfig(**filtered)
    except Exception as exc:
        log_error(f"Falha ao ler configuração: {exc}")
        config = AppConfig()
        save_config(config)
        return config


def save_config(config: AppConfig) -> None:
    _write_json_if_changed(CONFIG_PATH, asdict(config))


def load_cache() -> RuntimeCache:
    if not CACHE_PATH.exists():
        cache = RuntimeCache()
        save_cache(cache)
        return cache
    try:
        raw = CACHE_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            cache = RuntimeCache()
            save_cache(cache)
            return cache
        data = json.loads(raw)
        known = {f.name for f in fields(RuntimeCache)}
        filtered = {k: v for k, v in data.items() if k in known}
        if "effective_hz" not in filtered and "last_current_hz" in data:
            filtered["effective_hz"] = data.get("last_current_hz", 0)
        return RuntimeCache(**filtered)
    except Exception as exc:
        log_error(f"Falha ao ler cache: {exc}")
        cache = RuntimeCache()
        save_cache(cache)
        return cache


def save_cache(cache: RuntimeCache) -> None:
    _write_json_if_changed(CACHE_PATH, asdict(cache))


def build_startup_command(start_minimized: bool) -> str:
    args = ["--autostart"]
    if start_minimized:
        args.append("--minimized")

    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {" ".join(args)}'

    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if pythonw.exists():
        interpreter = pythonw

    return f'"{interpreter}" "{Path(__file__).resolve()}" {" ".join(args)}'


def set_startup_enabled(enabled: bool, start_minimized: bool) -> None:
    if winreg is None:
        raise RuntimeError("winreg não está disponível neste sistema.")

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    command = build_startup_command(start_minimized)

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)
            log_info(f"Arranque com Windows ativado: {command}")
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
                log_info("Arranque com Windows desativado.")
            except FileNotFoundError:
                pass


def is_startup_enabled() -> bool:
    if winreg is None:
        return False

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def create_fallback_icon(size: int = 256):
    if Image is None or ImageDraw is None:
        return None

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * 0.08)
    draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=int(size * 0.22),
        fill=(25, 31, 52, 255),
        outline=(86, 166, 255, 255),
        width=max(4, size // 32),
    )

    mid_y = size * 0.42
    wave_points = []
    for x in range(int(size * 0.16), int(size * 0.84), 4):
        phase = (x - size * 0.16) / (size * 0.68)
        y = mid_y + (size * 0.09) * __import__("math").sin(phase * 2 * __import__("math").pi * 1.5)
        wave_points.append((x, int(y)))
    draw.line(wave_points, fill=(86, 166, 255, 255), width=max(5, size // 34))

    h_left = int(size * 0.20)
    h_top = int(size * 0.56)
    h_bottom = int(size * 0.82)
    stroke = max(8, size // 22)
    draw.line((h_left, h_top, h_left, h_bottom), fill=(240, 244, 255, 255), width=stroke)
    draw.line((h_left + int(size * 0.13), h_top, h_left + int(size * 0.13), h_bottom), fill=(240, 244, 255, 255), width=stroke)
    draw.line((h_left, int(size * 0.69), h_left + int(size * 0.13), int(size * 0.69)), fill=(240, 244, 255, 255), width=stroke)

    z_x1 = int(size * 0.53)
    z_x2 = int(size * 0.80)
    z_top = int(size * 0.58)
    z_bottom = int(size * 0.82)
    draw.line((z_x1, z_top, z_x2, z_top), fill=(240, 244, 255, 255), width=stroke)
    draw.line((z_x2, z_top, z_x1, z_bottom), fill=(240, 244, 255, 255), width=stroke)
    draw.line((z_x1, z_bottom, z_x2, z_bottom), fill=(240, 244, 255, 255), width=stroke)

    return img


def create_tray_status_icon(power_source: str, refresh_rate: int, size: int = 64):
    if Image is None or ImageDraw is None:
        return None

    is_ac = power_source == "AC"
    accent = (64, 153, 255, 255) if is_ac else (64, 210, 112, 255)
    bg = (0, 0, 0, 255)

    img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)

    label = str(int(refresh_rate))
    font = None

    # Ajusta automaticamente o tamanho para caber bem com 2 ou 3 dígitos (ex.: 120, 165).
    if ImageFont is not None:
        margin_x = max(4, size // 10)
        margin_y = max(4, size // 10)
        max_w = size - (2 * margin_x)
        max_h = size - (2 * margin_y)

        for font_name in ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
            for candidate_size in range(int(size * 0.95), 11, -1):
                try:
                    candidate = ImageFont.truetype(font_name, candidate_size)
                except Exception:
                    continue

                bb = draw.textbbox((0, 0), label, font=candidate)
                w = bb[2] - bb[0]
                h = bb[3] - bb[1]
                if w <= max_w and h <= max_h:
                    font = candidate
                    break
            if font is not None:
                break

        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    x = (size - text_w) // 2 - text_bbox[0]
    y = (size - text_h) // 2 - text_bbox[1]

    # Pequena sombra para melhor legibilidade sobre qualquer escala da bandeja.
    draw.text((x + 1, y + 1), label, fill=(0, 0, 0, 255), font=font)
    draw.text((x, y), label, fill=accent, font=font)

    return img


# =========================================================
# Gestão de ecrãs e frequências
# =========================================================

class DisplayManager:
    @staticmethod
    def get_displays() -> list[DisplayInfo]:
        displays: list[DisplayInfo] = []
        index = 0

        while True:
            device = DISPLAY_DEVICEW()
            device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            result = EnumDisplayDevicesW(None, index, ctypes.byref(device), 0)
            if not result:
                break

            attached = bool(device.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP)
            if attached and device.DeviceName:
                mode = DEVMODEW()
                mode.dmSize = ctypes.sizeof(DEVMODEW)

                if EnumDisplaySettingsExW(device.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.byref(mode), 0):
                    displays.append(
                        DisplayInfo(
                            device_name=device.DeviceName,
                            device_label=device.DeviceString or device.DeviceName,
                            width=int(mode.dmPelsWidth),
                            height=int(mode.dmPelsHeight),
                            bits_per_pixel=int(mode.dmBitsPerPel),
                            current_hz=int(mode.dmDisplayFrequency),
                            is_primary=bool(device.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
                        )
                    )
            index += 1

        displays.sort(key=lambda d: (not d.is_primary, d.device_name))
        return displays

    @staticmethod
    def get_current_mode(device_name: str) -> DEVMODEW:
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        ok = EnumDisplaySettingsExW(device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(mode), 0)
        if not ok:
            raise RuntimeError(f"Não foi possível ler o modo atual do ecrã {device_name}.")
        return mode

    @staticmethod
    def get_supported_refresh_rates(device_name: str) -> list[int]:
        """Recolhe todas as frequências expostas pelo driver para a resolução atual.
        Usa enumeração por índice (normal + raw), ENUM_CURRENT_SETTINGS e
        ENUM_REGISTRY_SETTINGS para maximizar frequências detetadas (ex.: 165 Hz)."""
        current = DisplayManager.get_current_mode(device_name)
        rates: set[int] = set()

        def _add_if_same_res(mode: DEVMODEW) -> None:
            # Filtra por resolução; ignora bpp para apanhar modos de profundidade diferente
            if (int(mode.dmPelsWidth) == int(current.dmPelsWidth)
                    and int(mode.dmPelsHeight) == int(current.dmPelsHeight)
                    and int(mode.dmDisplayFrequency) > 1):
                rates.add(int(mode.dmDisplayFrequency))

        # Enumeração por índice: flags normal e EDS_RAWMODE (modos raw do driver)
        for flags in (0, EDS_RAWMODE):
            index = 0
            while True:
                mode = DEVMODEW()
                mode.dmSize = ctypes.sizeof(DEVMODEW)
                if not EnumDisplaySettingsExW(device_name, index, ctypes.byref(mode), flags):
                    break
                _add_if_same_res(mode)
                index += 1

        # Modos especiais: atual e registo (podem revelar frequências custom do driver)
        for special in (ENUM_CURRENT_SETTINGS, ENUM_REGISTRY_SETTINGS):
            for flags in (0, EDS_RAWMODE):
                mode = DEVMODEW()
                mode.dmSize = ctypes.sizeof(DEVMODEW)
                if EnumDisplaySettingsExW(device_name, special, ctypes.byref(mode), flags):
                    _add_if_same_res(mode)

        return sorted(rates)

    @staticmethod
    def get_current_refresh_rate(device_name: str) -> int:
        mode = DisplayManager.get_current_mode(device_name)
        return int(mode.dmDisplayFrequency)

    @staticmethod
    def validate_custom_hz(device_name: str, hz: int) -> bool:
        """Testa com CDS_TEST se o driver aceita o modo sem o aplicar."""
        try:
            current = DisplayManager.get_current_mode(device_name)
            test_mode = DEVMODEW()
            ctypes.memmove(ctypes.byref(test_mode), ctypes.byref(current), ctypes.sizeof(DEVMODEW))
            test_mode.dmDisplayFrequency = hz
            test_mode.dmFields = DM_DISPLAYFREQUENCY | DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
            result = ChangeDisplaySettingsExW(device_name, ctypes.byref(test_mode), None, CDS_TEST, None)
            return int(result) in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART)
        except Exception:
            return False

    @staticmethod
    def set_refresh_rate(device_name: str, refresh_rate: int) -> int:
        current = DisplayManager.get_current_mode(device_name)

        # Procura um modo completo compatível (resolução/bpp atuais + Hz pedido).
        selected_mode = None
        index = 0
        while True:
            mode = DEVMODEW()
            mode.dmSize = ctypes.sizeof(DEVMODEW)
            ok = EnumDisplaySettingsExW(device_name, index, ctypes.byref(mode), 0)
            if not ok:
                break

            same_resolution = (
                int(mode.dmPelsWidth) == int(current.dmPelsWidth)
                and int(mode.dmPelsHeight) == int(current.dmPelsHeight)
                and int(mode.dmBitsPerPel) == int(current.dmBitsPerPel)
            )
            same_hz = int(mode.dmDisplayFrequency) == int(refresh_rate)
            if same_resolution and same_hz:
                selected_mode = mode
                break
            index += 1

        # Fallback: tenta com o modo atual, alterando apenas o Hz.
        if selected_mode is None:
            selected_mode = current
            selected_mode.dmDisplayFrequency = int(refresh_rate)

        # Em alguns drivers, apenas certas combinações de fields/flags funcionam.
        field_strategies = [
            DM_DISPLAYFREQUENCY | DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL,
            DM_DISPLAYFREQUENCY,
        ]
        flag_strategies = [
            0,
            CDS_UPDATEREGISTRY,
            CDS_UPDATEREGISTRY | CDS_GLOBAL,
        ]

        # Para ecrã primário, alguns sistemas aceitam melhor lpszDeviceName=None.
        primary_name = next((d.device_name for d in DisplayManager.get_displays() if d.is_primary), "")
        device_targets = [device_name]
        if device_name == primary_name:
            device_targets.append(None)

        last_result = DISP_CHANGE_SUCCESSFUL
        for fields in field_strategies:
            for flags in flag_strategies:
                test_mode = DEVMODEW()
                ctypes.memmove(ctypes.byref(test_mode), ctypes.byref(selected_mode), ctypes.sizeof(DEVMODEW))
                test_mode.dmFields = fields

                for dev_target in device_targets:
                    result = ChangeDisplaySettingsExW(
                        dev_target,
                        ctypes.byref(test_mode),
                        None,
                        flags,
                        None,
                    )
                    result = int(result)
                    last_result = result
                    if result in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART):
                        return result

        return int(last_result)

    @staticmethod
    def apply_and_verify_refresh_rate(
        device_name: str,
        requested_hz: int,
        resolved_hz: int,
    ) -> RefreshRateVerificationResult:
        """
        Aplica Hz com verificação real através de leitura pós-aplicação.
        
        Fluxo:
        1. Lê Hz efetivo antes da aplicação
        2. Aplica o Hz com DisplayManager.set_refresh_rate()
        3. Espera settle delay (500ms)
        4. Relê o Hz 2-3 vezes com 100ms entre leituras
        5. Valida se estabilizou no valor esperado
        6. Retorna diagnóstico estruturado
        
        Returns:
            RefreshRateVerificationResult com todos os detalhes
        """
        result = RefreshRateVerificationResult(
            requested_hz=int(requested_hz),
            resolved_hz=int(resolved_hz),
            effective_before=0,
            effective_after=0,
            win32_result=0,
            verified=False,
            verification_attempts=0,
            readings=[],
            attempted_retry=False,
            fallback_applied=False,
            error_message="",
        )
        
        try:
            # 1. Lê Hz efetivo antes
            result.effective_before = int(DisplayManager.get_current_refresh_rate(device_name))
            
            # 2. Aplica o Hz
            win32_result = DisplayManager.set_refresh_rate(device_name, int(resolved_hz))
            result.win32_result = int(win32_result)
            
            # Se Win32 falhou, retorna já com falha
            if int(win32_result) not in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART):
                result.effective_after = int(DisplayManager.get_current_refresh_rate(device_name))
                result.verified = False
                result.error_message = f"Win32 retornou {int(win32_result)}"
                return result
            
            # 3. Settle delay (500ms)
            time.sleep(0.5)
            
            # 4. Relê o Hz 3 vezes com 100ms entre leituras
            verify_attempts = 3
            settle_delay = 0.1
            for attempt in range(verify_attempts):
                try:
                    current = int(DisplayManager.get_current_refresh_rate(device_name))
                    result.readings.append(current)
                    result.verification_attempts += 1
                except Exception:
                    result.readings.append(-1)
                    result.verification_attempts += 1
                
                if attempt < verify_attempts - 1:
                    time.sleep(settle_delay)
            
            # 5. Valida estabilização
            valid_readings = [r for r in result.readings if r > 0]
            if not valid_readings:
                result.effective_after = result.effective_before
                result.verified = False
                result.error_message = "Não foi possível ler Hz após aplicação"
                return result
            
            # Considera verificado se todas as leituras válidas coincidem com o valor esperado
            # ou se pelo menos 2 de 3 leituras estão corretas (tolerância para variações temporárias)
            matching = sum(1 for r in valid_readings if r == int(resolved_hz))
            result.effective_after = valid_readings[-1]  # última leitura válida
            result.verified = matching >= len(valid_readings) or matching >= 2
            
            if not result.verified:
                result.error_message = f"Leituras instáveis: {result.readings}"
            
        except Exception as exc:
            result.effective_after = result.effective_before
            result.verified = False
            result.error_message = str(exc)
        
        return result


# =========================================================
# Monitorização do estado de energia
# =========================================================

def get_power_source() -> str:
    status = SYSTEM_POWER_STATUS()
    ok = GetSystemPowerStatus(ctypes.byref(status))
    if not ok:
        raise RuntimeError("Não foi possível obter o estado de alimentação.")

    if status.ACLineStatus == 1:
        return "AC"
    if status.ACLineStatus == 0:
        return "Battery"
    return "Unknown"


# =========================================================
# App principal
# =========================================================


def apply_process_settings(config: "AppConfig") -> None:
    """Aplica prioridade e afinidade de CPU conforme configuração."""
    global _PROCESS_ALLOWED_AFFINITY_MASK

    handle = GetCurrentProcess()

    # Prioridade do processo
    target_priority = BELOW_NORMAL_PRIORITY_CLASS if config.low_priority else NORMAL_PRIORITY_CLASS
    ok = SetPriorityClass(handle, target_priority)
    if ok:
        label = "BELOW_NORMAL" if config.low_priority else "NORMAL"
        log_info(f"Prioridade do processo definida: {label}.")
    else:
        log_error("Falha ao definir prioridade do processo.")

    # Afinidade de CPU
    proc_mask = ctypes.c_size_t(0)
    sys_mask = ctypes.c_size_t(0)
    ok = GetProcessAffinityMask(handle, ctypes.byref(proc_mask), ctypes.byref(sys_mask))
    if not ok:
        log_error("Falha ao ler máscara de afinidade de CPU.")
        return

    current_mask = int(proc_mask.value)
    system_mask = int(sys_mask.value)
    allowed_mask = current_mask if current_mask else system_mask

    if allowed_mask <= 0:
        log_error("Máscara de afinidade inválida; afinidade não alterada.")
        return

    # Captura máscara de referência antes de aplicar restrições permanentes.
    if _PROCESS_ALLOWED_AFFINITY_MASK is None or (current_mask & (current_mask - 1)) != 0:
        _PROCESS_ALLOWED_AFFINITY_MASK = allowed_mask

    if config.single_core_affinity:
        first_core = allowed_mask & (-allowed_mask)  # bit mais baixo disponível
        if first_core <= 0:
            log_error("Nenhum núcleo disponível para afinidade a 1 núcleo.")
            return

        ok2 = SetProcessAffinityMask(handle, ctypes.c_size_t(first_core))
        if ok2:
            log_info(f"Afinidade de CPU: núcleo {first_core.bit_length() - 1}.")
        else:
            # Fallback limpo: mantém máscara atual e regista falha sem interromper a app.
            log_error("Falha ao definir afinidade de CPU (1 núcleo). Mantida afinidade atual.")
        return

    restore_candidates = [
        _PROCESS_ALLOWED_AFFINITY_MASK,
        allowed_mask,
        system_mask,
    ]
    for candidate in restore_candidates:
        if not candidate:
            continue
        if SetProcessAffinityMask(handle, ctypes.c_size_t(int(candidate))):
            log_info("Afinidade de CPU restaurada para máscara completa permitida.")
            return

    log_error("Falha ao restaurar afinidade de CPU; mantida máscara atual.")

class HzPowerSwitcherApp:
    def __init__(self, root: tk.Tk, config: AppConfig | None = None, start_hidden: bool = False):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x560")
        self.root.minsize(760, 560)

        self.config = config if config is not None else load_config()
        self.cache = load_cache()
        self._startup_hidden_requested = start_hidden
        self._window_hidden_to_tray = False

        if not self.config.selected_display and self.cache.selected_display:
            self.config.selected_display = self.cache.selected_display
        if self.config.ac_hz == 0 and self.cache.ac_hz > 0:
            self.config.ac_hz = self.cache.ac_hz
        if self.config.battery_hz == 0 and self.cache.battery_hz > 0:
            self.config.battery_hz = self.cache.battery_hz

        self.config.autostart_enabled = is_startup_enabled()
        log_info(
            "Configuração carregada | "
            f"autostart={self.config.autostart_enabled} | "
            f"start_minimized={self.config.start_minimized} | "
            f"minimize_to_tray={self.config.minimize_to_tray_on_close}"
        )

        self.displays: list[DisplayInfo] = []
        self.supported_rates: list[int] = []

        # Aplica imediatamente prioridade e afinidade conforme config
        apply_process_settings(self.config)

        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.last_power_source: str | None = None

        self.tray_icon = None
        self.tray_thread = None
        self.tray_ready = False
        self._last_tray_state: tuple[str, int] | None = None
        self._last_cache_save_ts: float = 0.0
        self._recognized_rates_cache: dict[str, tuple[float, list[int]]] = {}
        self._recognized_rates_cache_ttl_s: float = 8.0
        self.requested_hz: int | None = self.cache.requested_hz if self.cache.requested_hz > 0 else None
        self.resolved_hz: int | None = self.cache.resolved_hz if self.cache.resolved_hz > 0 else None
        self.effective_hz: int | None = self.cache.effective_hz if self.cache.effective_hz > 0 else None
        self.last_applied_hz: int | None = self.cache.last_applied_hz if self.cache.last_applied_hz > 0 else None
        self.startup_phase_active: bool = True
        self.startup_first_read_snapshot: dict | None = None
        self.startup_second_read_snapshot: dict | None = None

        # --- Unified recheck state (lock + debounce + reentrância) ---
        self._apply_lock = threading.Lock()
        self._apply_in_progress: bool = False
        self._last_execute_ts: float = 0.0
        self._pending_after_lock = threading.Lock()
        self._recheck_request_id: int = 0
        self._ui_event_queue: queue.SimpleQueue[tuple] = queue.SimpleQueue()

        self.display_var = tk.StringVar()
        self.ac_var = tk.StringVar()
        self.battery_var = tk.StringVar()
        self.autostart_var = tk.BooleanVar(value=self.config.autostart_enabled)
        self.start_minimized_var = tk.BooleanVar(value=self.config.start_minimized)
        self.monitoring_var = tk.BooleanVar(value=self.config.monitoring_enabled)
        self.minimize_to_tray_var = tk.BooleanVar(value=self.config.minimize_to_tray_on_close)
        self.custom_hz_var = tk.StringVar()
        self.custom_hz_status_var = tk.StringVar()
        self.low_priority_var = tk.BooleanVar(value=self.config.low_priority)
        self.single_core_var = tk.BooleanVar(value=self.config.single_core_affinity)
        self._orig_wnd_proc = None   # referência ao WndProc original do Tk
        self._wnd_proc_cb = None     # mantém o callback vivo (evita GC)

        cached_power = self.cache.last_power_source if self.cache.last_power_source else "a verificar..."
        cached_status = self.cache.last_app_status if self.cache.last_app_status else "pronta"
        cached_diag = self.cache.last_diagnostic if self.cache.last_diagnostic else "sem diagnóstico ainda"

        self.power_status_var = tk.StringVar(value=f"Estado de alimentação: {cached_power}")
        self.current_hz_var = tk.StringVar(value="Frequência atual: a verificar...")
        self.app_status_var = tk.StringVar(value=f"Estado da app: {cached_status}")
        self.diagnostic_var = tk.StringVar(value=f"Diagnóstico: {cached_diag}")

        self._build_ui()
        self._ensure_min_window_size()
        self._set_window_icon()
        self._schedule_ui_queue_drain()
        self._load_displays()
        self._sync_config_to_ui()

        self.root.protocol(WM_DELETE_WINDOW, self.on_close_requested)

        if pystray is not None:
            self._start_tray()
        else:
            log_error("Bandeja indisponível: pystray não carregado.")

        self._start_monitoring()

        if start_hidden:
            self._hide_on_startup()
        else:
            self.show_main_window("startup")

    def show_main_window(self, reason: str = "manual") -> None:
        self._window_hidden_to_tray = False
        self.root.deiconify()
        if reason != "startup":
            self.root.lift()
            try:
                self.root.focus_force()
            except Exception:
                pass
        log_info(f"Janela mostrada | reason={reason}")

    def _hide_on_startup(self) -> None:
        log_info("Arranque minimizado ativo: janela mantida oculta.")
        self.root.withdraw()
        self._window_hidden_to_tray = True
        self._set_status("App iniciada minimizada na bandeja.")

        if pystray is None or Image is None:
            self.root.after(200, self._fallback_startup_without_tray)
            return

        # Pequeno atraso para a área de notificação do Windows ficar pronta.
        self.root.after(1800, self._confirm_startup_tray_ready)

    def _confirm_startup_tray_ready(self) -> None:
        if not self._startup_hidden_requested or not self._window_hidden_to_tray:
            return
        if self.tray_ready:
            log_info("Bandeja pronta: arranque continua oculto.")
            return
        self._fallback_startup_without_tray()

    def _fallback_startup_without_tray(self) -> None:
        if not self._startup_hidden_requested or not self._window_hidden_to_tray:
            return
        log_error("Bandeja indisponível no arranque; janela minimizada na barra de tarefas.")
        self._window_hidden_to_tray = False
        self.root.deiconify()
        self.root.iconify()
        self._set_status("Bandeja indisponível; app minimizada na barra de tarefas.")

    # -----------------------------------------------------
    # Interface
    # -----------------------------------------------------

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        title = ttk.Label(main, text=APP_NAME, font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            main,
            text="Alterna automaticamente a frequência do ecrã entre bateria e corrente.",
        )
        subtitle.pack(anchor="w", pady=(2, 14))

        form = ttk.LabelFrame(main, text="Configuração", padding=12)
        form.pack(fill="x")

        ttk.Label(form, text="Ecrã alvo").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        self.display_combo = ttk.Combobox(form, textvariable=self.display_var, state="readonly", width=60)
        self.display_combo.grid(row=0, column=1, sticky="ew", pady=6)
        self.display_combo.bind("<<ComboboxSelected>>", self.on_display_changed)

        ttk.Label(form, text="Frequência em corrente").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        self.ac_combo = ttk.Combobox(form, textvariable=self.ac_var, state="readonly", width=20)
        self.ac_combo.grid(row=1, column=1, sticky="w", pady=6)

        ttk.Label(form, text="Frequência em bateria").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        self.battery_combo = ttk.Combobox(form, textvariable=self.battery_var, state="readonly", width=20)
        self.battery_combo.grid(row=2, column=1, sticky="w", pady=6)

        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Hz extra / custom").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=6)
        custom_frame = ttk.Frame(form)
        custom_frame.grid(row=3, column=1, sticky="w", pady=6)
        ttk.Entry(custom_frame, textvariable=self.custom_hz_var, width=8).pack(side="left")
        ttk.Button(custom_frame, text="Validar", command=self.on_validate_custom_hz).pack(side="left", padx=(6, 0))
        ttk.Label(custom_frame, textvariable=self.custom_hz_status_var, foreground="#555555").pack(side="left", padx=(8, 0))

        options = ttk.LabelFrame(main, text="Comportamento", padding=12)
        options.pack(fill="x", pady=(12, 0))

        ttk.Checkbutton(
            options,
            text="Ativar arranque com o Windows",
            variable=self.autostart_var,
            command=self.on_autostart_toggled,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options,
            text="Arrancar minimizado",
            variable=self.start_minimized_var,
            command=self.on_start_minimized_toggled,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options,
            text="Monitorização ativa",
            variable=self.monitoring_var,
            command=self.on_monitoring_toggled,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options,
            text="Ao fechar, minimizar para a bandeja",
            variable=self.minimize_to_tray_var,
            command=self.on_minimize_to_tray_toggled,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options,
            text="Prioridade baixa do processo (BELOW_NORMAL)",
            variable=self.low_priority_var,
            command=self.on_low_priority_toggled,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options,
            text="Afinidade a 1 núcleo de CPU",
            variable=self.single_core_var,
            command=self.on_single_core_toggled,
        ).pack(anchor="w", pady=3)

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(12, 0))

        ttk.Button(actions, text="Guardar", command=self.save_from_ui).pack(side="left")
        ttk.Button(actions, text="Aplicar agora", command=self.apply_now).pack(side="left", padx=8)
        ttk.Button(actions, text="Atualizar frequências", command=self.refresh_displays_and_rates).pack(side="left")
        ttk.Button(actions, text="Abrir pasta da app", command=self.open_app_folder).pack(side="right")
        ttk.Button(actions, text="Minimizar", command=self.minimize_to_tray).pack(side="right", padx=(0, 8))

        status = ttk.LabelFrame(main, text="Estado", padding=12)
        status.pack(fill="both", expand=True, pady=(12, 0))

        ttk.Label(status, textvariable=self.power_status_var).pack(anchor="w", pady=2)
        ttk.Label(status, textvariable=self.current_hz_var).pack(anchor="w", pady=2)
        ttk.Label(status, textvariable=self.app_status_var, wraplength=560).pack(anchor="w", pady=2)
        ttk.Label(status, textvariable=self.diagnostic_var, wraplength=560, foreground="#444444").pack(anchor="w", pady=2)

        note = ttk.Label(
            status,
            text="Nota: a lista de Hz inclui frequências nativas do driver e frequências custom validadas para este ecrã e resolução. Hz custom de outros ecrãs ou resoluções não aparecem aqui.",
            wraplength=560,
        )
        note.pack(anchor="w", pady=(12, 0))

    def _set_window_icon(self) -> None:
        try:
            if ICON_PATH.exists():
                # Em Windows, .ico deve ser aplicado com iconbitmap para ser o ícone principal.
                self.root.iconbitmap(default=str(ICON_PATH))
        except Exception:
            pass

    def _ensure_min_window_size(self) -> None:
        self.root.update_idletasks()

        required_w = self.root.winfo_reqwidth() + 24
        required_h = self.root.winfo_reqheight() + 24

        min_w = max(760, required_w)
        min_h = max(560, required_h)
        self.root.minsize(min_w, min_h)

        current_w = self.root.winfo_width()
        current_h = self.root.winfo_height()
        if current_w < min_w or current_h < min_h:
            self.root.geometry(f"{min_w}x{min_h}")

    # -----------------------------------------------------
    # Sincronização de config e UI
    # -----------------------------------------------------

    def _sync_config_to_ui(self) -> None:
        self.start_minimized_var.set(self.config.start_minimized)
        self.monitoring_var.set(self.config.monitoring_enabled)
        self.minimize_to_tray_var.set(self.config.minimize_to_tray_on_close)

    def _load_displays(self) -> None:
        self.displays = DisplayManager.get_displays()
        if not self.displays:
            messagebox.showerror(APP_NAME, "Não foi encontrado nenhum ecrã ativo.")
            self.root.after(250, self.root.destroy)
            return

        titles = [d.title for d in self.displays]
        self.display_combo["values"] = titles

        selected = None
        if self.config.selected_display:
            selected = next((d for d in self.displays if d.device_name == self.config.selected_display), None)

        if selected is None:
            selected = next((d for d in self.displays if d.is_primary), self.displays[0])

        self.display_var.set(selected.title)
        self.config.selected_display = selected.device_name
        self._load_rates_for_display(selected.device_name)
        self._update_status_labels()

    def _load_rates_for_display(self, device_name: str) -> None:
        self.supported_rates = self._get_recognized_refresh_rates(device_name, bypass_cache=True)
        all_rates = self._get_recognized_refresh_rates(device_name)
        sticky_rates = {int(rate) for rate in (self.config.ac_hz, self.config.battery_hz) if int(rate) > 0}
        values = [str(rate) for rate in sorted(set(all_rates) | sticky_rates)]

        self.ac_combo["values"] = values
        self.battery_combo["values"] = values

        current_rate = DisplayManager.get_current_refresh_rate(device_name)

        ac_value = int(self.config.ac_hz) if int(self.config.ac_hz) > 0 else int(current_rate)
        battery_value = int(self.config.battery_hz) if int(self.config.battery_hz) > 0 else int(current_rate)

        self.ac_var.set(str(ac_value))
        self.battery_var.set(str(battery_value))

        # Não degradar config por enumeração temporária incompleta no arranque.
        if self.config.ac_hz <= 0:
            self.config.ac_hz = int(ac_value)
        if self.config.battery_hz <= 0:
            self.config.battery_hz = int(battery_value)
        self.config.selected_display = device_name
        save_config(self.config)

    def _get_selected_display(self) -> DisplayInfo:
        for display in self.displays:
            if display.title == self.display_var.get():
                return display
        return next((d for d in self.displays if d.device_name == self.config.selected_display), self.displays[0])

    def _invalidate_rates_cache(self, device_name: str | None = None) -> None:
        if device_name is None:
            self._recognized_rates_cache.clear()
            return

        prefix = f"{device_name}||"
        stale_keys = [key for key in self._recognized_rates_cache if key.startswith(prefix)]
        for key in stale_keys:
            self._recognized_rates_cache.pop(key, None)

    def _get_recognized_refresh_rates(self, device_name: str, bypass_cache: bool = False) -> list[int]:
        """Junta frequências nativas/raw do driver com as custom validadas para o contexto
        atual (device + resolução). Nunca mistura customs de outros ecrãs/resoluções."""
        custom_validated: set[int] = set()
        cache_key = ""
        try:
            mode = DisplayManager.get_current_mode(device_name)
            cache_key = _custom_context_key(
                device_name, int(mode.dmPelsWidth), int(mode.dmPelsHeight)
            )
            custom_validated = {
                int(hz)
                for hz in self.config.custom_hz_map.get(cache_key, [])
                if int(hz) > 0
            }
        except Exception:
            cache_key = f"{device_name}||unknown"

        now = time.time()
        cached = self._recognized_rates_cache.get(cache_key)
        if not bypass_cache and cached and (now - cached[0]) < self._recognized_rates_cache_ttl_s:
            return list(cached[1])

        native_and_raw = DisplayManager.get_supported_refresh_rates(device_name)
        merged = sorted(set(native_and_raw) | custom_validated)
        self._recognized_rates_cache[cache_key] = (now, merged)
        return list(merged)

    def _update_runtime_refresh_state(
        self,
        *,
        requested_hz: int | None = None,
        resolved_hz: int | None = None,
        effective_hz: int | None = None,
        last_applied_hz: int | None = None,
        power: str | None = None,
        device_name: str | None = None,
        force_save: bool = False,
    ) -> None:
        before_snapshot = asdict(self.cache)

        if requested_hz is not None:
            self.requested_hz = int(requested_hz)
        if resolved_hz is not None:
            self.resolved_hz = int(resolved_hz)
        if effective_hz is not None:
            self.effective_hz = int(effective_hz)
        if last_applied_hz is not None:
            self.last_applied_hz = int(last_applied_hz)
        if power is not None:
            self.cache.last_power_source = power
        if device_name is not None:
            self.cache.selected_display = device_name

        self.cache.ac_hz = self.config.ac_hz
        self.cache.battery_hz = self.config.battery_hz
        self.cache.requested_hz = int(self.requested_hz or 0)
        self.cache.resolved_hz = int(self.resolved_hz or 0)
        self.cache.effective_hz = int(self.effective_hz or 0)
        self.cache.last_applied_hz = int(self.last_applied_hz or 0)
        self.cache.last_update_iso = datetime.now().isoformat(timespec="seconds")
        changed = before_snapshot != asdict(self.cache)
        if changed or force_save:
            self._save_runtime_cache(force=force_save)

    def _resolve_valid_target_hz(self, device_name: str, requested_hz: int) -> tuple[int, bool]:
        available = self._get_recognized_refresh_rates(device_name)
        if not available:
            # Em alguns equipamentos/drivers, a enumeração pode falhar temporariamente.
            # Nesses casos, tenta aplicar o valor pedido diretamente.
            return int(requested_hz), False

        if requested_hz in available:
            return requested_hz, False

        # Fallback para a frequência mais próxima quando o valor guardado deixa de estar disponível.
        fallback = min(available, key=lambda hz: (abs(hz - requested_hz), hz))
        return int(fallback), True

    def _capture_startup_snapshot(self, power: str) -> dict:
        """Captura o estado observado sem consolidar config/cache."""
        device_name = self.config.selected_display
        current_displays = DisplayManager.get_displays()
        known_devices = {d.device_name for d in current_displays}
        if device_name not in known_devices and current_displays:
            device_name = next((d.device_name for d in current_displays if d.is_primary), current_displays[0].device_name)

        requested_hz = self.config.ac_hz if power == "AC" else self.config.battery_hz
        available_now = self._get_recognized_refresh_rates(device_name)
        effective_hz = DisplayManager.get_current_refresh_rate(device_name)
        return {
            "power": power,
            "device_name": device_name,
            "requested_hz": int(requested_hz),
            "available_now": list(available_now),
            "effective_hz": int(effective_hz),
        }

    def _format_startup_snapshot(self, label: str, snapshot: dict) -> str:
        available = snapshot.get("available_now", [])
        preview = ", ".join(str(hz) for hz in available[:8]) if available else "lista indisponível"
        return (
            f"startup_{label} | power={snapshot.get('power')}"
            f" | requested_hz={snapshot.get('requested_hz')}"
            f" | effective={snapshot.get('effective_hz')}"
            f" | available={preview}"
        )

    def _start_startup_phase(self) -> None:
        self.startup_phase_active = True
        self.startup_first_read_snapshot = None
        self.startup_second_read_snapshot = None
        self._set_diagnostic("startup_phase_active=true | a aguardar primeira leitura")
        self._set_status("Fase de arranque ativa: a estabilizar displays/frequências.")
        self.root.after(
            int(STARTUP_INITIAL_SYNC_DELAY_SECONDS * 1000),
            self._run_startup_first_read,
        )

    def _run_startup_first_read(self) -> None:
        if not self.startup_phase_active:
            return
        try:
            power = get_power_source()
            snapshot = self._capture_startup_snapshot(power)
            self.startup_first_read_snapshot = snapshot
            self._set_diagnostic(self._format_startup_snapshot("first_read", snapshot))
        except Exception as exc:
            self._set_diagnostic(f"startup_first_read_error={exc}")

        self.root.after(
            int(STARTUP_SECOND_VERIFICATION_DELAY_SECONDS * 1000),
            self._run_startup_second_read_and_finalize,
        )

    def _run_startup_second_read_and_finalize(self) -> None:
        if not self.startup_phase_active:
            return
        try:
            power = get_power_source()
            snapshot = self._capture_startup_snapshot(power)
            self.startup_second_read_snapshot = snapshot
            self._set_diagnostic(self._format_startup_snapshot("second_read", snapshot))

            # Aplica frequência via método centralizado com proteção de lock
            self._execute_startup_apply()
        except Exception as exc:
            self._set_diagnostic(f"startup_second_read_error={exc}")
            self._set_status(f"Erro na fase de arranque: {exc}")
        finally:
            self.startup_phase_active = False

    # -----------------------------------------------------
    # Eventos da UI
    # -----------------------------------------------------

    def on_display_changed(self, event=None) -> None:
        display = self._get_selected_display()
        self._invalidate_rates_cache(display.device_name)
        self._load_rates_for_display(display.device_name)
        self._set_status(f"Ecrã selecionado: {display.device_label}")

    def on_autostart_toggled(self) -> None:
        enabled = self.autostart_var.get()
        try:
            set_startup_enabled(enabled, self.start_minimized_var.get())
            self.config.autostart_enabled = enabled
            save_config(self.config)
            self._set_status("Arranque com Windows atualizado.")
        except Exception as exc:
            self.autostart_var.set(not enabled)
            messagebox.showerror(APP_NAME, f"Falha ao atualizar arranque com o Windows:\n{exc}")
            log_error(f"Falha no arranque com Windows: {exc}")

    def on_start_minimized_toggled(self) -> None:
        self.config.start_minimized = self.start_minimized_var.get()
        save_config(self.config)

        if self.autostart_var.get():
            try:
                set_startup_enabled(True, self.start_minimized_var.get())
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Falha ao atualizar o comando de arranque:\n{exc}")
                log_error(f"Falha ao atualizar comando de arranque: {exc}")

        self._set_status("Opção de arranque minimizado atualizada.")

    def on_monitoring_toggled(self) -> None:
        self.config.monitoring_enabled = self.monitoring_var.get()
        save_config(self.config)
        state_text = "ativa" if self.config.monitoring_enabled else "desativada"
        self._set_status(f"Monitorização {state_text}.")

    def on_minimize_to_tray_toggled(self) -> None:
        self.config.minimize_to_tray_on_close = self.minimize_to_tray_var.get()
        save_config(self.config)
        self._set_status("Comportamento de fecho atualizado.")

    def on_low_priority_toggled(self) -> None:
        self.config.low_priority = self.low_priority_var.get()
        save_config(self.config)
        apply_process_settings(self.config)
        self._set_status("Prioridade do processo atualizada.")

    def on_single_core_toggled(self) -> None:
        self.config.single_core_affinity = self.single_core_var.get()
        save_config(self.config)
        apply_process_settings(self.config)
        self._set_status("Afinidade de CPU atualizada.")

    def on_validate_custom_hz(self) -> None:
        """Valida frequência custom com CDS_TEST e guarda no contexto correto
        (device + resolução atual). Não contamina outros ecrãs nem resoluções."""
        raw = self.custom_hz_var.get().strip()
        if not raw:
            self.custom_hz_status_var.set("Introduz um valor.")
            return
        try:
            hz = int(raw)
        except ValueError:
            self.custom_hz_status_var.set("Valor inválido.")
            return
        if hz < 1 or hz > 500:
            self.custom_hz_status_var.set("Fora do intervalo (1–500).")
            return

        display = self._get_selected_display()
        self.custom_hz_status_var.set("A validar...")
        self.root.update_idletasks()

        accepted = DisplayManager.validate_custom_hz(display.device_name, hz)
        if accepted:
            # Determina o contexto exato: device + resolução atual
            try:
                mode = DisplayManager.get_current_mode(display.device_name)
                w, h = int(mode.dmPelsWidth), int(mode.dmPelsHeight)
            except Exception:
                w, h = display.width, display.height
            key = _custom_context_key(display.device_name, w, h)

            bucket = list(self.config.custom_hz_map.get(key, []))
            if hz not in bucket:
                bucket.append(hz)
                bucket.sort()
                self.config.custom_hz_map[key] = bucket
                save_config(self.config)
                self._invalidate_rates_cache(display.device_name)
            self._load_rates_for_display(display.device_name)
            self.custom_hz_status_var.set(f"{hz} Hz aceite para {w}x{h}.")
            log_info(
                f"Hz custom validado: {hz} Hz | contexto={key}."
            )
        else:
            self.custom_hz_status_var.set(f"{hz} Hz não aceite pelo driver.")
            log_info(f"Hz custom rejeitado: {hz} Hz em {display.device_name}.")

    def _setup_power_notification(self) -> None:
        """Instala WndProc para receber WM_POWERBROADCAST sem polling agressivo."""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.c_void_p(self.root.winfo_id())

            WndProcType = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,
                ctypes.c_void_p, ctypes.c_uint,
                ctypes.c_size_t, ctypes.c_ssize_t,
            )

            def _proc(h, msg, wp, lp):
                if msg == WM_POWERBROADCAST and wp == PBT_APMPOWERSTATUSCHANGE:
                    # Sinaliza mudança de energia; agendamento centralizado com debounce
                    self.root.after(
                        0,
                        lambda: self.request_refresh_recheck("wm_powerbroadcast", delay_ms=200),
                    )
                return _CallWindowProcW(self._orig_wnd_proc, ctypes.c_void_p(h), msg, wp, lp)

            self._wnd_proc_cb = WndProcType(_proc)
            orig = _SetWindowLongPtrW(hwnd, GWLP_WNDPROC, self._wnd_proc_cb)
            self._orig_wnd_proc = orig  # inteiro (c_void_p retorna int)
            log_info("Notificação de energia WM_POWERBROADCAST instalada.")
        except Exception as exc:
            self._orig_wnd_proc = None
            log_error(f"Falha ao instalar notificação de energia: {exc}. Polling ativo como fallback.")

    def save_from_ui(self) -> None:
        display = self._get_selected_display()

        try:
            ac_hz = int(self.ac_var.get())
            battery_hz = int(self.battery_var.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "Seleciona valores válidos de frequência.")
            return

        all_valid = set(self._get_recognized_refresh_rates(display.device_name))
        if ac_hz not in all_valid or battery_hz not in all_valid:
            messagebox.showerror(APP_NAME, "Os valores selecionados não constam na lista reconhecida pelo sistema.")
            return

        self.config.selected_display = display.device_name
        self.config.ac_hz = ac_hz
        self.config.battery_hz = battery_hz
        self.config.start_minimized = self.start_minimized_var.get()
        self.config.monitoring_enabled = self.monitoring_var.get()
        self.config.minimize_to_tray_on_close = self.minimize_to_tray_var.get()
        self.config.autostart_enabled = self.autostart_var.get()

        save_config(self.config)
        self.cache.selected_display = self.config.selected_display
        self.cache.ac_hz = self.config.ac_hz
        self.cache.battery_hz = self.config.battery_hz
        self.cache.last_update_iso = datetime.now().isoformat(timespec="seconds")
        self._save_runtime_cache(force=True)
        self._set_status("Configuração guardada com sucesso.")
        log_info(f"Configuração guardada: {self.config}")

    def refresh_displays_and_rates(self) -> None:
        self._invalidate_rates_cache()
        self._load_displays()
        self._set_status("Lista de ecrãs e frequências atualizada.")

    def open_app_folder(self) -> None:
        os.startfile(APP_DIR)  # type: ignore[attr-defined]

    def apply_now(self) -> None:
        self.save_from_ui()
        self.request_refresh_recheck("manual", delay_ms=0)

    # -----------------------------------------------------
    # Estado e monitorização
    # -----------------------------------------------------

    def _update_status_labels(self) -> None:
        try:
            power = get_power_source()
            effective_hz = DisplayManager.get_current_refresh_rate(self.config.selected_display)
            self.power_status_var.set(f"Estado de alimentação: {power}")
            self.current_hz_var.set(f"Frequência atual: {effective_hz} Hz")
            self._update_tray_status_indicator(power, effective_hz)
            self._update_runtime_refresh_state(
                effective_hz=effective_hz,
                power=power,
                device_name=self.config.selected_display,
            )
        except Exception as exc:
            self.power_status_var.set("Estado de alimentação: erro")
            self.current_hz_var.set("Frequência atual: erro")
            log_error(f"Falha ao atualizar estado: {exc}")

    def _set_status(self, text: str) -> None:
        formatted = f"Estado da app: {text}"
        if self.app_status_var.get() == formatted and self.cache.last_app_status == text:
            return

        self.app_status_var.set(formatted)
        log_info(text)
        self.cache.last_app_status = text
        self.cache.last_update_iso = datetime.now().isoformat(timespec="seconds")
        self._save_runtime_cache()

    def _set_diagnostic(self, text: str, force_save: bool = False) -> None:
        formatted = f"Diagnóstico: {text}"
        if self.diagnostic_var.get() == formatted and self.cache.last_diagnostic == text and not force_save:
            return

        self.diagnostic_var.set(formatted)
        self.cache.last_diagnostic = text
        self.cache.last_update_iso = datetime.now().isoformat(timespec="seconds")
        self._save_runtime_cache(force=force_save)
        log_info(f"Diagnóstico: {text}")

    def _save_runtime_cache(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_cache_save_ts) < 10.0:
            return
        try:
            save_cache(self.cache)
            self._last_cache_save_ts = now
        except Exception as exc:
            log_error(f"Falha ao gravar cache: {exc}")

    def _post_ui_call(self, callback, *args) -> None:
        self._ui_event_queue.put((callback, args))

    def _schedule_ui_queue_drain(self) -> None:
        self.root.after(100, self._drain_ui_event_queue)

    def _drain_ui_event_queue(self) -> None:
        while True:
            try:
                callback, args = self._ui_event_queue.get_nowait()
            except queue.Empty:
                break

            try:
                callback(*args)
            except Exception as exc:
                log_error(f"Falha ao processar evento de UI: {exc}")

        if not self.stop_event.is_set():
            self._schedule_ui_queue_drain()

    # -----------------------------------------------------
    # Reavaliação centralizada (debounce + lock + reentrância)
    # -----------------------------------------------------

    def request_refresh_recheck(self, reason: str, delay_ms: int = RECHECK_DEBOUNCE_MS) -> None:
        """Ponto de entrada único para pedir reavaliação do Hz.

        Pode ser chamado de qualquer thread (WM_POWERBROADCAST, polling, startup, manual).
        Garante:
          - sem applies concorrentes (lock)
          - colapso de pedidos duplicados próximos (debounce por request_id)
          - cooldown: polling não re-dispara logo após WM_POWERBROADCAST já ter aplicado

        Diagnóstico emitido:
          source=<reason> | skipped_duplicate=true/false | apply_in_progress=true/false
        """
        now = time.time()
        with self._apply_lock:
            in_progress = self._apply_in_progress
            since_last = now - self._last_execute_ts

        if in_progress:
            log_info(
                f"recheck_request | source={reason} | skipped_duplicate=true | apply_in_progress=true"
            )
            self._set_diagnostic(
                f"source={reason} | skipped_duplicate=true | apply_in_progress=true"
            )
            return

        # Polling respeita cooldown: evita re-apply redundante logo após WM ter actuado
        if reason == "polling" and since_last < RECHECK_COOLDOWN_S:
            log_info(
                f"recheck_request | source=polling | skipped_duplicate=true"
                f" | apply_in_progress=false | since_last={since_last:.1f}s"
            )
            return

        with self._pending_after_lock:
            self._recheck_request_id += 1
            current_id = self._recheck_request_id

        log_info(
            f"recheck_scheduled | source={reason} | delay_ms={delay_ms} | request_id={current_id}"
        )
        self.root.after(delay_ms, lambda: self._execute_refresh_recheck(reason, current_id))

    def _execute_refresh_recheck(self, reason: str, request_id: int) -> None:
        """Executado na thread Tk após o delay de debounce.

        Só prossegue se ainda for o pedido mais recente (debounce) e se não houver
        apply em curso (reentrância).
        """
        # Debounce: pedido suplantado por outro mais recente?
        with self._pending_after_lock:
            is_latest = (request_id == self._recheck_request_id)

        if not is_latest:
            log_info(
                f"recheck_debounced | source={reason} | skipped_duplicate=true | apply_in_progress=false"
            )
            return

        # Proteção contra reentrância
        with self._apply_lock:
            if self._apply_in_progress:
                log_info(
                    f"recheck_blocked | source={reason} | skipped_duplicate=false | apply_in_progress=true"
                )
                return
            self._apply_in_progress = True

        try:
            log_info(
                f"recheck_execute | source={reason} | skipped_duplicate=false | apply_in_progress=true"
            )
            self._set_diagnostic(
                f"source={reason} | skipped_duplicate=false | apply_in_progress=true"
            )
            self.apply_refresh_for_current_power(force=True)
        finally:
            with self._apply_lock:
                self._apply_in_progress = False
                self._last_execute_ts = time.time()

    def _execute_startup_apply(self) -> None:
        """Aplica frequência na fase de arranque com proteção contra reentrância.

        Usa os mesmos parâmetros especiais de arranque (preserve/defer) mas partilha
        o mesmo lock que request_refresh_recheck, impedindo applies simultâneos.
        """
        with self._apply_lock:
            if self._apply_in_progress:
                log_info("startup_apply_skipped | source=startup | apply_in_progress=true")
                return
            self._apply_in_progress = True

        try:
            log_info(
                "recheck_execute | source=startup | skipped_duplicate=false | apply_in_progress=true"
            )
            self._set_diagnostic(
                "source=startup | skipped_duplicate=false | apply_in_progress=true"
            )
            self.apply_refresh_for_current_power(
                force=True,
                preserve_requested_if_missing=True,
                allow_persistent_fallback=True,
                defer_runtime_consolidation=True,
            )
        finally:
            with self._apply_lock:
                self._apply_in_progress = False
                self._last_execute_ts = time.time()

    def _start_monitoring(self) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.stop_event.clear()
        self.last_power_source = None
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

        # Instala notificação event-driven de mudança AC/bateria via WndProc
        self._setup_power_notification()
        self._set_status("Monitorização iniciada.")
        self._start_startup_phase()

    def _monitor_loop(self) -> None:
        """Watchdog leve: deteta mudanças de energia perdidas pelo WM_POWERBROADCAST.

        Não é o motor principal de aplicação — delega sempre em request_refresh_recheck,
        que aplica debounce, lock e cooldown para evitar applies redundantes com o WM.
        """
        while not self.stop_event.is_set():
            try:
                power = get_power_source()

                if self.last_power_source is None:
                    self.last_power_source = power
                    # Primeira iteração: apenas dispara se a fase de arranque já terminou
                    if self.config.monitoring_enabled and not self.startup_phase_active:
                        self._post_ui_call(self.request_refresh_recheck, "polling", 0)
                elif power != self.last_power_source:
                    captured_power = power
                    self.last_power_source = power
                    if self.config.monitoring_enabled:
                        # Usa delay maior que o WM (200ms) para deixar WM ganhar a corrida;
                        # o debounce/cooldown absorve o duplicado se WM já tiver actuado.
                        self._post_ui_call(self.request_refresh_recheck, "polling", 500)
                    else:
                        self._post_ui_call(
                            self._set_status,
                            f"Alimentação mudou para {captured_power}, mas a monitorização está desativada.",
                        )

                self._post_ui_call(self._update_status_labels)
            except Exception as exc:
                log_error(f"Erro na monitorização: {exc}")
                err_msg = str(exc)
                self._post_ui_call(self._set_status, f"Erro na monitorização: {err_msg}")

            # Usa wait com timeout: mais eficiente que sleep e para imediatamente no exit
            self.stop_event.wait(CHECK_INTERVAL_SECONDS)

    def apply_refresh_for_current_power(
        self,
        force: bool = False,
        preserve_requested_if_missing: bool = False,
        allow_persistent_fallback: bool = True,
        defer_runtime_consolidation: bool = False,
    ) -> None:
        if not defer_runtime_consolidation:
            self.save_from_ui()

        if not self.config.monitoring_enabled and not force:
            return

        try:
            power = get_power_source()
            requested_hz = self.config.ac_hz if power == "AC" else self.config.battery_hz
            device_name = self.config.selected_display
            available_now: list[int] = []

            # Se o ecrã guardado já não existir, usa o primário como fallback.
            current_displays = DisplayManager.get_displays()
            known_devices = {d.device_name for d in current_displays}
            if device_name not in known_devices:
                replacement = next((d for d in current_displays if d.is_primary), None)
                if replacement is None:
                    raise RuntimeError("Nenhum ecrã ativo disponível para aplicar frequência.")
                device_name = replacement.device_name
                self.config.selected_display = replacement.device_name
                self.display_var.set(replacement.title)
                save_config(self.config)

            available_now = self._get_recognized_refresh_rates(device_name)
            if preserve_requested_if_missing and requested_hz not in available_now:
                resolved_hz, used_fallback = int(requested_hz), False
            else:
                resolved_hz, used_fallback = self._resolve_valid_target_hz(device_name, int(requested_hz))

            if used_fallback and allow_persistent_fallback:
                if power == "AC":
                    self.config.ac_hz = resolved_hz
                    self.ac_var.set(str(resolved_hz))
                else:
                    self.config.battery_hz = resolved_hz
                    self.battery_var.set(str(resolved_hz))
                save_config(self.config)
                log_info(
                    f"Fallback de frequência em {power}: requested_hz={requested_hz} | resolved_hz={resolved_hz} | display={device_name}"
                )
            elif used_fallback and not allow_persistent_fallback:
                log_info(
                    f"Fallback apenas transitório em {power}: requested_hz={requested_hz} | resolved_hz={resolved_hz} | display={device_name}"
                )

            effective_hz_before = DisplayManager.get_current_refresh_rate(device_name)
            if not defer_runtime_consolidation:
                self._update_runtime_refresh_state(
                    requested_hz=requested_hz,
                    resolved_hz=resolved_hz,
                    effective_hz=effective_hz_before,
                    power=power,
                    device_name=device_name,
                    force_save=True,
                )
            available_text = ", ".join(str(rate) for rate in available_now[:8]) if available_now else "lista indisponível"
            self._set_diagnostic(
                f"Energia={power} | requested_hz={requested_hz} | resolved_hz={resolved_hz} | effective_before={effective_hz_before} | Disponíveis={available_text}"
            )

            # Verifica se já está no valor esperado
            if effective_hz_before == resolved_hz and not force:
                self.cache.last_verification_status = "sem alteração necessária"
                self._set_status(
                    f"Sem alteração necessária. {power} | pedido={requested_hz} Hz | resolvido={resolved_hz} Hz | efetivo={effective_hz_before} Hz"
                )
                return

            # ===== NOVO: Aplica e verifica com confirmação real =====
            verification = DisplayManager.apply_and_verify_refresh_rate(
                device_name=device_name,
                requested_hz=requested_hz,
                resolved_hz=resolved_hz,
            )
            
            # Atualiza cache com resultado de verificação
            self.cache.last_verification_status = verification.short_status()
            self._update_runtime_refresh_state(
                requested_hz=verification.requested_hz,
                resolved_hz=verification.resolved_hz,
                effective_hz=verification.effective_after,
                last_applied_hz=verification.effective_after if verification.is_success() else None,
                power=power,
                device_name=device_name,
                force_save=True,
            )
            
            # Diagnóstico detalhado com leituras
            readings_str = ", ".join(str(r) for r in verification.readings) if verification.readings else "n/d"
            diag_verified_text = "confirmado" if verification.verified else "NÃO confirmado"
            diag_fallback_text = " | fallback=sim" if verification.fallback_applied else ""
            
            self._set_diagnostic(
                f"Energia={power} | req={requested_hz} Hz | res={resolved_hz} Hz "
                f"| before={verification.effective_before} Hz | after={verification.effective_after} Hz "
                f"| win32={verification.win32_result} | verificado={diag_verified_text} "
                f"| tentativas={verification.verification_attempts} | leituras=[{readings_str}]"
                f"{diag_fallback_text}"
            )

            if defer_runtime_consolidation and self.startup_phase_active:
                first_desc = self._format_startup_snapshot("first_read", self.startup_first_read_snapshot) if self.startup_first_read_snapshot else "startup_first_read=indisponível"
                second_desc = self._format_startup_snapshot("second_read", self.startup_second_read_snapshot) if self.startup_second_read_snapshot else "startup_second_read=indisponível"
                final_desc = (
                    f"startup_final_confirmed_state | req={requested_hz} | res={resolved_hz} "
                    f"| effective={verification.effective_after} | verified={verification.verified}"
                )
                self._set_diagnostic(f"{first_desc} || {second_desc} || {final_desc}")
            
            # Determina mensagem de estado conforme resultado
            if verification.is_success():
                self._set_status(
                    f"✓ Frequência aplicada E confirmada em {power}. "
                    f"Pedido={requested_hz} Hz | Efetivo={verification.effective_after} Hz"
                )
            elif verification.is_applied_unconfirmed():
                self._set_status(
                    f"⚠ Frequência aplicada MAS NÃO CONFIRMADA em {power}. "
                    f"Pedido={requested_hz} Hz | Efetivo lido={verification.effective_after} Hz | "
                    f"Leituras={readings_str}. Verifica a frequência manualmente no Windows."
                )
            else:
                self._set_status(
                    f"✗ Falha ao aplicar frequência em {power}. "
                    f"Pedido={requested_hz} Hz. Erro: {verification.error_message}"
                )

        except Exception as exc:
            self._set_diagnostic(f"Erro ao aplicar frequência: {exc}")
            self._set_status(f"Erro ao aplicar frequência: {exc}")
            log_error(f"Erro ao aplicar frequência: {exc}")

    # -----------------------------------------------------
    # Bandeja do sistema
    # -----------------------------------------------------

    def _start_tray(self) -> None:
        if pystray is None or Image is None:
            log_error("Bandeja não iniciada: dependências indisponíveis.")
            return
        if self.tray_thread and self.tray_thread.is_alive():
            return

        def setup_tray():
            try:
                tray_image = self._build_tray_icon_image()
                tray_title = self._build_tray_title_text()

                menu = pystray.Menu(
                    pystray.MenuItem("Abrir", self._tray_show_window),
                    pystray.MenuItem("Aplicar agora", self._tray_apply_now),
                    pystray.MenuItem("Sair", self._tray_exit_app),
                )
                self.tray_icon = pystray.Icon(APP_NAME, tray_image, tray_title, menu)
                self.tray_ready = True
                log_info("Bandeja criada com sucesso.")
                self.tray_icon.run()
            except Exception as exc:
                self.tray_ready = False
                self.tray_icon = None
                log_error(f"Falha a iniciar bandeja do sistema: {exc}")

        self.tray_thread = threading.Thread(target=setup_tray, daemon=True)
        self.tray_thread.start()

    def _tray_show_window(self, icon=None, item=None) -> None:
        self.root.after(0, self.restore_from_tray)

    def _tray_apply_now(self, icon=None, item=None) -> None:
        self.root.after(0, self.apply_now)

    def _tray_exit_app(self, icon=None, item=None) -> None:
        self.root.after(0, self.exit_app)

    def minimize_to_tray(self) -> None:
        if pystray is None or not self.tray_ready:
            self.root.iconify()
            self._window_hidden_to_tray = False
            log_info("Janela minimizada na barra de tarefas: bandeja indisponível.")
            self._set_status("Janela minimizada.")
            return

        self.root.withdraw()
        self._window_hidden_to_tray = True
        self._update_status_labels()
        log_info("Janela ocultada na bandeja.")
        self._set_status("App minimizada para a bandeja.")

    def _build_tray_title_text(self) -> str:
        try:
            power = get_power_source()
            current_hz = DisplayManager.get_current_refresh_rate(self.config.selected_display)
            return f"{APP_NAME} | {power} | {current_hz} Hz"
        except Exception:
            return APP_NAME

    def _build_tray_icon_image(self):
        try:
            power = get_power_source()
            current_hz = DisplayManager.get_current_refresh_rate(self.config.selected_display)
            status_image = create_tray_status_icon(power, current_hz, size=64)
            if status_image is not None:
                return status_image
        except Exception:
            pass

        try:
            if ICON_PATH.exists() and Image is not None:
                return Image.open(ICON_PATH)
        except Exception:
            pass

        return create_fallback_icon(256)

    def _update_tray_status_indicator(self, power: str, current_hz: int) -> None:
        if self.tray_icon is None:
            return

        current_state = (power, int(current_hz))
        if self._last_tray_state == current_state:
            return

        try:
            status_image = create_tray_status_icon(power, current_hz, size=64)
            if status_image is not None:
                self.tray_icon.icon = status_image
            self.tray_icon.title = f"{APP_NAME} | {power} | {current_hz} Hz"
            self._last_tray_state = current_state
        except Exception as exc:
            log_error(f"Falha ao atualizar ícone da bandeja: {exc}")

    def restore_from_tray(self) -> None:
        self.show_main_window("tray")
        self._set_status("Janela restaurada.")

    def on_close_requested(self) -> None:
        if self.minimize_to_tray_var.get():
            self.minimize_to_tray()
        else:
            self.exit_app()

    def exit_app(self) -> None:
        self.stop_event.set()
        self._save_runtime_cache(force=True)
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    # -----------------------------------------------------
    # Ciclo final
    # -----------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


# =========================================================
# Entrada
# =========================================================

def main() -> None:
    args = set(sys.argv[1:])
    launched_by_windows = "--autostart" in args
    config = load_config()
    start_hidden = "--minimized" in args or (launched_by_windows and config.start_minimized)

    log_info(
        "Startup phase | "
        f"args={list(args)} | autostart={launched_by_windows} | "
        f"start_minimized={config.start_minimized} | start_hidden={start_hidden}"
    )

    if not acquire_single_instance_lock(reveal_existing=not launched_by_windows):
        return

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass

        app = HzPowerSwitcherApp(root=root, config=config, start_hidden=start_hidden)
        app.run()
    except Exception as exc:
        log_error(f"Erro real no arranque: {exc}")
        if root is not None:
            try:
                root.deiconify()
                messagebox.showerror(APP_NAME, f"Falha ao iniciar a app:\n{exc}")
            except Exception:
                pass
        raise
    finally:
        release_single_instance_lock()


if __name__ == "__main__":
    main()
