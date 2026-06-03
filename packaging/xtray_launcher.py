from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--cli" in args:
        cli_args = [arg for arg in args if arg != "--cli"]
        from xtray.cli import main as cli_main

        cli_main(args=cli_args, prog_name="xtray", standalone_mode=True)
        return

    from xtray.tray import main as tray_main

    tray_main(args)


if __name__ == "__main__":
    main()
