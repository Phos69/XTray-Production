from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from xtray.backend_jsonrpc import main as backend_main

    return int(backend_main(list(sys.argv[1:] if argv is None else argv)) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
