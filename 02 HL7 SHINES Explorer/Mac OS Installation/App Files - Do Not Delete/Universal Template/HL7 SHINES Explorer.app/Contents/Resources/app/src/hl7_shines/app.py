from __future__ import annotations

import sys

from hl7_shines.ui import HL7ShinesApp


def main() -> int:
    app = HL7ShinesApp(initial_files=sys.argv[1:])
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
