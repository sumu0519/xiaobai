"""看门狗：监测 bot.py 的 WebUI 端口，无响应时自动拉起进程。
用法：python watchdog.py  （可长期挂后台）
"""
import os
import sys
import time
import httpx
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
CHECK_INTERVAL = 30          # 每次检查间隔（秒）
FAIL_THRESHOLD = 3           # 连续失败 N 次判定为宕机


def bot_alive(port: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def start_bot() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "bot.py"],
        cwd=ROOT,
        stdout=open(os.path.join(ROOT, "boot.log"), "ab"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
    )


def main():
    import config
    cfg = config.load()
    port = int(cfg["ws_host"] and cfg["ws_port"] or 8080)
    print(f"[watchdog] 启动，每 {CHECK_INTERVAL}s 检查 http://127.0.0.1:{port}，"
          f"连续 {FAIL_THRESHOLD} 次无响应则重启 bot.py")
    fails = 0
    proc = None
    while True:
        if bot_alive(port):
            fails = 0
        else:
            fails += 1
            print(f"[watchdog] bot 无响应（{fails}/{FAIL_THRESHOLD}）")
            if fails >= FAIL_THRESHOLD:
                print("[watchdog] 判定宕机，重启 bot.py ...")
                try:
                    if proc and proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                proc = start_bot()
                fails = 0
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
