"""프로그램 시작점.

ManosTranslator.exe                → 번역기만 켬
ManosTranslator.exe --with-wechat  → 위챗과 번역기를 같이 켬 ('위챗+번역기' 바탕화면 아이콘)
"""
import sys
import time
import traceback

from app import win_window


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "발주 번역기", 0x40)


def main():
    with_wechat = "--with-wechat" in sys.argv
    if with_wechat:
        from app import config as C
        from app import wechat_launcher
        cfg = C.load_config()
        path = wechat_launcher.find_wechat_exe(cfg.get("wechat_path"))
        if path:
            wechat_launcher.launch(path)
            if path != cfg.get("wechat_path"):
                cfg["wechat_path"] = path
                C.save_config(cfg)
    if not win_window.acquire_single_instance():
        if not with_wechat:
            _message("번역기가 이미 켜져 있습니다.\n화면에 안 보이면 작업 관리자(Ctrl+Shift+Esc)에서 "
                     "ManosTranslator 를 끝낸 뒤 다시 켜 주세요.")
        return
    try:
        # 화면 배율(125%·150%) 처리는 Qt 가 알아서 함 (화면 픽셀 좌표로 동작)
        from app.ui_qt import run
        code = run(ask_wechat_path=with_wechat)
    except Exception:
        try:
            from app import config as C
            with open(C.data_dir() / "log.txt", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "시작 오류\n" + traceback.format_exc() + "\n")
        except OSError:
            pass
        _message("번역기를 켜다가 오류가 났습니다.\n⚙ 데이터 폴더의 log.txt 를 비서실장에게 보내 주세요.\n"
                 "(폴더 위치: %APPDATA%\\ManosWeChatTranslator)")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
