#!/usr/bin/env python3
"""
Простой чекер ключей: тип + эдишн + статус от Microsoft.
Использует уже готовые модули winkeycheck (keycutter, pkeyconfig)
и тот же live-запрос к licensing.microsoft.com что и keycheck.py.
"""
import sys, os, glob, subprocess, argparse, xml.etree.ElementTree as ET
import hmac, hashlib, base64, html, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from .licensing_stuff.keycutter import ProductKeyDecoder
    from .licensing_stuff.pkeyconfig import PKeyConfig
    from . import keycheck as kc
except ImportError:
    from licensing_stuff.keycutter import ProductKeyDecoder
    from licensing_stuff.pkeyconfig import PKeyConfig
    import keycheck as kc
import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = os.path.dirname(os.path.abspath(__file__))


def _bundle_roots() -> list[str]:
    """Кандидаты корня данных: PyInstaller (_MEIPASS) и dev (winkeycheck/)."""
    roots: list[str] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.append(meipass)
            nested = os.path.join(meipass, "winkeycheck")
            if os.path.isdir(nested):
                roots.append(nested)
    roots.append(HERE)
    seen: set[str] = set()
    out: list[str] = []
    for root in roots:
        norm = os.path.normpath(root)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _bundle_root() -> str:
    return _bundle_roots()[0]


def _pidgenx_tools_dir() -> str:
    if os.environ.get("PIDGENX_TOOLS_DIR"):
        return os.environ["PIDGENX_TOOLS_DIR"]
    for root in _bundle_roots():
        candidate = os.path.join(root, "pidgenx")
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(_bundle_root(), "pidgenx")


WINE_PREFIX = os.path.expanduser("~/.wine32")
IS_WINDOWS = sys.platform.startswith("win")

# HMAC-SHA256 ключ от Cas de Reuver (2017), всё ещё работает в 2026 для BatchActivation
MAK_HMAC_KEY = bytes.fromhex(
    "fe319875fb4884869cf3f1ce99a89064ab571fca470450583024e214628779a0"
)
BATCH_ACT_URL = "https://activation.sls.microsoft.com/BatchActivation/BatchActivation.asmx"


def run_pidgenx(key: str, pkeyconfig_path: str | None = None) -> dict:
    """Запускает pidgenx_caller.exe (на Windows напрямую, на Linux через Wine).
    Возвращает dict с ADVANCED_PID и др.

    Если pkeyconfig_path не указан — используется дефолтный (Windows).
    Чтобы pidgenx справился с Office 2024 ключом — нужен Office pkeyconfig.
    """
    exe = os.path.join(_pidgenx_tools_dir(), "pidgenx_caller.exe")
    pkc = pkeyconfig_path or os.path.join(_pidgenx_tools_dir(), "pkeyconfig.xrm-ms")
    if not os.path.exists(exe):
        return {"error": f"pidgenx_caller.exe not in {_pidgenx_tools_dir()}"}
    if not os.path.exists(pkc):
        return {"error": f"pkeyconfig not found: {pkc}"}

    tools_dir = _pidgenx_tools_dir()
    env = os.environ.copy()
    try:
        if IS_WINDOWS:
            cmd = [exe, key, pkc]
        else:
            # Wine wrapper: путь к pkeyconfig нужен в Windows-формате (Z:\...)
            # Конвертируем абсолютный POSIX-путь.
            pkc_win = "Z:" + pkc.replace("/", "\\")
            env["WINEARCH"] = "win32"
            env["WINEPREFIX"] = WINE_PREFIX
            env["WINEDEBUG"] = "-all"
            cmd = ["wine", "pidgenx_caller.exe", key, pkc_win]

        result = subprocess.run(
            cmd,
            cwd=tools_dir,
            env=env,
            capture_output=True,
            timeout=20,
        )
    except Exception as e:
        return {"error": f"pidgenx call failed: {e}"}

    out = result.stdout.decode(errors="ignore")
    info = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()
        elif ":" in line and line.startswith("HRESULT"):
            info["HRESULT"] = line.split(":", 1)[1].strip()
    return info


def get_mak_count(advanced_pid: str) -> dict:
    """Спрашивает у Microsoft BatchActivation сколько активаций осталось.
    Используется тот же XML/HMAC что в IonBazan/pidgenx GetCount."""
    pid = "12345" + advanced_pid[5:]   # XXXXX → 12345
    inner = (
        '<ActivationRequest xmlns="http://www.microsoft.com/DRM/SL/BatchActivationRequest/1.0">'
        "<VersionNumber>2.0</VersionNumber><RequestType>2</RequestType>"
        f"<Requests><Request><PID>{pid}</PID></Request></Requests>"
        "</ActivationRequest>"
    )
    byte_xml = inner.encode("utf-16-le")
    digest = base64.b64encode(hmac.new(MAK_HMAC_KEY, byte_xml, hashlib.sha256).digest()).decode()
    b64_xml = base64.b64encode(byte_xml).decode()
    soap = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        '<soap:Body><BatchActivate xmlns="http://www.microsoft.com/BatchActivationService">'
        f"<request><Digest>{digest}</Digest><RequestXml>{b64_xml}</RequestXml></request>"
        "</BatchActivate></soap:Body></soap:Envelope>"
    )
    try:
        r = requests.post(
            BATCH_ACT_URL, data=soap, verify=False, timeout=30,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"http://www.microsoft.com/BatchActivationService/BatchActivate"',
                "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; MS Web Services Client Protocol 4.0.30319.1)",
            },
        )
    except Exception as e:
        return {"error": f"BatchActivation call failed: {e}"}
    txt = html.unescape(r.text)
    m_rem = re.search(r"<ActivationRemaining>(-?\d+)</ActivationRemaining>", txt)
    m_err = re.search(r"<ErrorCode>(.*?)</ErrorCode>", txt)
    return {
        "http": r.status_code,
        "remaining": int(m_rem.group(1)) if m_rem else None,
        "error_code": m_err.group(1) if m_err else None,
    }

# HRESULT коды от Microsoft Software Licensing
HRESULT_RU = {
    "0x0":         "Online-valid (ключ принят сервером)",
    "0xC004C001":  "Ключ невалидный (неверный формат/подпись)",
    "0xC004C003":  "Ключ заблокирован Microsoft",
    "0xC004C008":  "Превышен лимит активаций (Activation count exceeded)",
    "0xC004C020":  "MAK-ключ исчерпан (превышено допустимое число использований)",
    "0xC004C060":  "Ключ больше не действителен (отозван)",
    "0xC004C4A1":  "Сервер активации временно недоступен",
    "0xC004C4A2":  "Ключ заблокирован (genuine fail)",
    "0xC004F050":  "Ключ невалидный для данной редакции (Product key is invalid)",
    "0xC004F070":  "Невалидный SLP / отозван",
    "0xC004F074":  "KMS host недоступен",
}


def hresult_human(code: str, fallback_msg: str) -> str:
    """Перевод HRESULT в русский текст. Если не знаем — оригинальный message."""
    code_norm = code.upper().replace("0X", "0x") if code else code
    if code_norm in HRESULT_RU:
        return HRESULT_RU[code_norm]
    return fallback_msg or "(нет описания)"


def load_all_pkeyconfigs():
    """Загружает основной pkeyconfig + все из licensing_stuff/pkeyconfigs/.
    Возвращает список (label, PKeyConfig, путь)."""
    seen_paths: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for root in _bundle_roots():
        main_p = os.path.join(root, "pkeyconfig.xrm-ms")
        if os.path.isfile(main_p):
            norm = os.path.normpath(main_p)
            if norm not in seen_paths:
                candidates.append((os.path.basename(root) or "root", norm))
                seen_paths.add(norm)
        bundle = os.path.join(root, "licensing_stuff", "pkeyconfigs")
        if os.path.isdir(bundle):
            for p in sorted(glob.glob(os.path.join(bundle, "**", "*.xrm-ms"), recursive=True)):
                norm = os.path.normpath(p)
                if norm in seen_paths:
                    continue
                label = os.path.relpath(norm, bundle).replace(os.sep, "/")
                candidates.append((label, norm))
                seen_paths.add(norm)

    out = []
    for label, p in candidates:
        try:
            with open(p, encoding="utf-8-sig") as f:
                out.append((label, PKeyConfig(ET.fromstring(f.read())), p))
        except Exception as e:
            print(f"WARN pkeyconfig skip {label}: {e}", file=sys.stderr)
    if not out:
        print(f"ERROR: no pkeyconfigs loaded; roots={_bundle_roots()}", file=sys.stderr)
    else:
        print(f"Loaded {len(out)} pkeyconfigs from {len(candidates)} files.", file=sys.stderr)
    return out


def decode_local(key: str, pkcs):
    """Перебирает все pkeyconfig, возвращает первый match.
    pkcs — список (label, PKeyConfig, path)."""
    pk = ProductKeyDecoder(key)
    for entry in pkcs:
        # back-compat: иногда передают (label, pkc) без пути
        if len(entry) == 3:
            label, pkc, path = entry
        else:
            label, pkc = entry
            path = None
        try:
            cfg = pkc.config_for_group(pk.group)
        except StopIteration:
            continue

        ranges = pkc.ranges_for_group(pk.group)
        in_range = next(
            (r for r in ranges if r.start <= pk.serial <= r.end),
            ranges[0] if ranges else None,
        )

        return {
            "pkc": pkc,
            "pkc_label": label,
            "pkc_path": path,
            "group": pk.group,
            "serial": pk.serial,
            "edition_id": cfg.edition_id,
            "description": cfg.desc,
            "key_type": cfg.key_type,
            "eula_type": in_range.eula_type if in_range else None,
            "part_number": in_range.part_number if in_range else None,
            "valid_range": in_range.is_valid if in_range else None,
        }
    return None


def check_key(key: str, pkcs=None, do_online=True, do_consume=False, do_mak_count=True,
              allow_consume_retail: bool = False, **_extra) -> dict:
    """Проверка одного ключа. Возвращает dict для JSON-сериализации.
    Используется и CLI и HTTP-сервером.

    allow_consume_retail: если True, разрешает consume даже у Retail/OEM-ключей.
        Нужно когда ключ лежит в Phone-категории — онлайн-активация нам не нужна,
        и потерять её не страшно (часто она и так исчерпана). По умолчанию False —
        защищаем дорогие Online-ключи от случайного слива.
    """
    key = key.strip().upper()
    out = {"key": key, "ok": False}

    if pkcs is None:
        pkcs = load_all_pkeyconfigs()

    try:
        local = decode_local(key, pkcs)
    except Exception as e:
        out["error"] = f"decode failed: {e}"
        return out

    if not local:
        if not pkcs:
            out["error"] = (
                "сервер не загрузил pkeyconfig (0 конфигов). "
                "Удалите KeyCheckerServer.exe из папки, закройте старый сервер в диспетчере задач, "
                "перезапустите только Vault.exe"
            )
            out["pkeyconfigs_loaded"] = 0
        else:
            out["error"] = "ключ не подходит ни к одной группе ни в одном pkeyconfig"
            out["pkeyconfigs_loaded"] = len(pkcs)
        return out

    out["ok"] = True
    out["edition"] = local["edition_id"]
    out["description"] = local["description"]
    out["key_type"] = local["key_type"]
    out["eula_type"] = local["eula_type"]
    out["part_number"] = local["part_number"]
    out["pkeyconfig"] = local["pkc_label"]

    # человеко-читаемая строка типа: "Volume / Volume:MAK" или "Retail"
    eula = local["eula_type"] or "?"
    kt = local["key_type"] or "?"
    out["type_label"] = eula if kt in eula else f"{eula} / {kt}"

    is_mak = "MAK" in (local.get("eula_type") or "") or "MAK" in (local.get("key_type") or "")
    out["is_mak"] = is_mak

    # MAK Count
    if is_mak and do_mak_count:
        # Передаём в pidgenx тот же pkeyconfig что подошёл при декоде, иначе для Office 2024
        # с Windows-pkeyconfig pidgenx вернёт "не моя группа".
        pinfo = run_pidgenx(key, local.get("pkc_path"))
        if pinfo.get("error") or pinfo.get("HRESULT") not in (None, "0x00000000"):
            out["mak_count_error"] = pinfo.get("error") or f"pidgenx HRESULT={pinfo.get('HRESULT')}"
        else:
            adv = pinfo.get("ADVANCED_PID")
            out["advanced_pid"] = adv
            if adv:
                mak = get_mak_count(adv)
                if mak.get("remaining") is not None:
                    out["mak_count"] = mak["remaining"]
                elif mak.get("error_code"):
                    out["mak_count_error"] = f"MS вернул {mak['error_code']}"
                else:
                    out["mak_count_error"] = "нет ActivationRemaining"

    # Online status
    if do_online:
        # Без скрытой защиты: что прислал клиент — то и делаем.
        # Пользователь сам отвечает за расход активаций.
        try:
            if do_consume:
                response, message, success = kc.consume_key(key, kc.PUB_LICENSE, local["pkc"])
                out["online_mode"] = "consume"
            else:
                response, message, success = kc.query_key(key, local["pkc"])
                out["online_mode"] = "query"
            out["online_ok"] = success
            out["online_code"] = response
            out["online_message"] = message
            if not success:
                out["online_human"] = hresult_human(response, message)
        except Exception as e:
            out["online_error"] = str(e)

    return out


def main():
    p = argparse.ArgumentParser(
        description="Чекер ключа Windows/Office: тип + эдишн + онлайн-статус Microsoft.",
        epilog="Без -c MS возвращает только базовый статус. С -c видны все коды ошибок (0xC004C020 и т.п.), НО ТРАТИТСЯ 1 АКТИВАЦИЯ при успехе.",
    )
    p.add_argument("keys", nargs="+", help="Один или несколько ключей XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
    p.add_argument("--no-online", action="store_true", help="Не делать онлайн-запрос к MS")
    p.add_argument("-c", "--consume", action="store_true",
                   help="ПОЛНЫЙ режим: видны все коды ошибок. ВНИМАНИЕ: тратит 1 активацию у MAK-ключа при успехе.")
    p.add_argument("--no-mak-count", action="store_true",
                   help="Не запрашивать MAK count (по умолчанию для Volume:MAK ключей делается доп.запрос).")
    args = p.parse_args()

    pkcs = load_all_pkeyconfigs()
    print(f"# загружено pkeyconfig: {len(pkcs)}", file=sys.stderr)

    for key in args.keys:
        key = key.strip().upper()
        print(f"\n=== {key} ===")
        try:
            local = decode_local(key, pkcs)
        except Exception as e:
            print(f"  Локально:    НЕ удалось декодировать ({e})")
            continue

        if not local:
            print("  Локально:    ключ не подходит ни к одной группе ни в одном pkeyconfig")
            continue

        # Тип
        eula = local["eula_type"] or "?"
        kt = local["key_type"] or "?"
        type_label = eula
        if kt and kt not in eula:
            type_label = f"{eula} / {kt}"

        print(f"  Тип:         {type_label}")
        print(f"  Эдишн:       {local['edition_id']}")
        print(f"  Описание:    {local['description']}")
        if local["part_number"]:
            print(f"  Part №:      {local['part_number']}")
        print(f"  Конфиг:      {local['pkc_label']}")

        # MAK Count: для Volume:MAK ключей через Wine + pidgenx + MS BatchActivation
        is_mak = "MAK" in (local.get("eula_type") or "") or "MAK" in (local.get("key_type") or "")
        if is_mak and not args.no_mak_count:
            pinfo = run_pidgenx(key)
            if pinfo.get("error") or pinfo.get("HRESULT") not in (None, "0x00000000"):
                print(f"  MAK Count:   ? ({pinfo.get('error') or 'pidgenx HRESULT='+str(pinfo.get('HRESULT'))})")
            else:
                adv = pinfo.get("ADVANCED_PID")
                if adv:
                    mak = get_mak_count(adv)
                    if mak.get("remaining") is not None:
                        print(f"  MAK Count:   {mak['remaining']}")
                    elif mak.get("error_code"):
                        print(f"  MAK Count:   ? (MS вернул {mak['error_code']})")
                    else:
                        print(f"  MAK Count:   ? (нет ActivationRemaining в ответе)")
                else:
                    print(f"  MAK Count:   ? (нет ADVANCED_PID)")

        if args.no_online:
            continue

        # Online check from MS. Use SAME pkc that decoded the key locally.
        try:
            if args.consume:
                response, message, success = kc.consume_key(key, kc.PUB_LICENSE, local["pkc"])
                mode_label = "Online (consume)"
            else:
                response, message, success = kc.query_key(key, local["pkc"])
                mode_label = "Online (query)"
        except Exception as e:
            print(f"  Online:      запрос упал ({e})")
            continue

        if success:
            print(f"  {mode_label}:  ✓ Online-valid")
        else:
            human = hresult_human(response, message)
            print(f"  {mode_label}:  ✗ {human}")
            if response and response != "N/A":
                print(f"  Код:         {response}")
            if message and message not in human:
                print(f"  MS msg:      {message}")


if __name__ == "__main__":
    main()
