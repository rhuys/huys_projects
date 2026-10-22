"""Perform OCR on an image from the clipboard using RapidOCR."""

import numpy as np
from PIL import Image, ImageGrab
from rapidocr_onnxruntime import RapidOCR  # pip install rapidocr_onnxruntime

def main():
    clip = ImageGrab.grabclipboard()
    if isinstance(clip, Image.Image):
        img = clip
    elif isinstance(clip, list) and clip:
        # Files copied in Explorer come through as a list of paths
        img = Image.open(clip[0])
    else:
        raise SystemExit("No image on the clipboard")

    engine = RapidOCR()
    result, _ = engine(np.array(img.convert("RGB")))
    print("\n".join(line[1] for line in result or []))


if __name__ == "__main__":
    main()

