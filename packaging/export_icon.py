from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import umbra


def main() -> None:
    output = Path("assets") / "umbra_pdf.ico"
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(io.BytesIO(base64.b64decode(umbra.APP_ICON_PNG_BASE64))).convert("RGBA")
    image.save(
        output,
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icon generated: {output}")


if __name__ == "__main__":
    main()
