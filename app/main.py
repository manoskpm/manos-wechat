"""프로그램 시작점.

ManosTranslator.exe                → 번역기만 켬
ManosTranslator.exe --with-wechat  → 위챗과 번역기를 같이 켬 ('위챗+번역기' 바탕화면 아이콘)
"""
import sys

from app import win_window


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
        return  # 번역기는 이미 켜져 있음 (위챗만 앞으로 가져옴)
    # 화면 배율(125%·150%) 처리는 Qt 가 알아서 함 (화면 픽셀 좌표로 동작)
    from app.ui_qt import run
    sys.exit(run(ask_wechat_path=with_wechat))


if __name__ == "__main__":
    main()
