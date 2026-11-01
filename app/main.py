"""프로그램 시작점."""
from app import win_window


def main():
    win_window.enable_dpi_awareness()  # 창을 만들기 전에 해야 좌표가 정확함
    from app.ui import App
    App().run()


if __name__ == "__main__":
    main()
