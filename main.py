"""Spurwerk — MKV Remuxer & Audio-Studio. Einstiegspunkt."""

from app import SpurwerkApp


def main() -> None:
    SpurwerkApp().mainloop()


if __name__ == "__main__":
    main()
