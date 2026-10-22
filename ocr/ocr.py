"""Perform OCR on an image from the clipboard using RapidOCR."""

import numpy as np
from PIL import Image, ImageGrab
from rapidocr_onnxruntime import RapidOCR  # pip install rapidocr_onnxruntime


def copy_to_clipboard(text):
    """Copy text to the system clipboard using Tkinter."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()


def merge_same_line_results(result):
    """Combine adjacent OCR detections whose text sits on the same visual line."""
    if not result:
        return []

    items = []
    for box, text, *_ in result:
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        center_y = sum(ys) / len(ys)
        left = min(xs)
        items.append((center_y, left, text))

    items.sort(key=lambda item: (item[0], item[1]))

    lines = []
    for center_y, left, text in items:
        if not lines or abs(center_y - lines[-1]["y"]) > 12:
            lines.append({"y": center_y, "parts": [(left, text)]})
        else:
            lines[-1]["parts"].append((left, text))

    merged_lines = []
    for line in lines:
        line["parts"].sort(key=lambda entry: entry[0])
        merged_lines.append(" ".join(text for _, text in line["parts"]))

    return merged_lines


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
    text = "\n".join(merge_same_line_results(result))
    print(text)
    copy_to_clipboard(text)

 
if __name__ == "__main__":
    main()
