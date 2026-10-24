"""
Bit encoder tool

Encode a file into a lossless black-and-white PNG or display it in a window.
PNG output defaults to 320 bits per row unless -w / --width is specified.
Each bit is a solid P x P pixel block: 0 is black and 1 is white.
Set P with -p / --pixel-size (default: 2). The data width is measured in
rendered pixels, excluding the border and margins, and must be a positive
multiple of P. The number of data bits per row is width / P.
Set the maximum data height in pixels with -h / --height (PNG default: 320).
Only complete P-pixel rows fit; capacity is bits per row * floor(height / P)
divided by eight, rounded down to whole bytes. Use --help to display help.
An alternating black/white block border surrounds the data, followed by
a 15-pixel black margin, giving a total width of data width + 2 * P + 30 pixels.
Bits are written most significant first, left to
right, then top to bottom. The height follows the file length; unused bits
in the last row stay black. Inputs exceeding the calculated capacity are rejected.
For graphical output, determine maximum dimensions from the screen before
reading the input. Unspecified dimensions use the screen limits; explicit
-w and -h values remain
upper bounds; the frame, margins and space for window decorations also
count toward the screen limit. The graphical layout prefers a compact,
nearly square grid within these limits. Inputs that still do not fit are rejected.
Use -O / --output to save a PNG. Otherwise, display the image at native
pixel size in a centered Tkinter window, with scrollbars for larger images.
This format is not compatible with the earlier single-pixel format.
"""

import argparse
from math import isqrt
from pathlib import Path

from PIL import Image


BLACK_MARGIN = 15


def get_screen_size():
    """Query Tk's screen dimensions without leaving a second window open."""
    try:
        import tkinter as tk
    except ImportError as error:
        raise ValueError("Tkinter is required to query the screen; use -O to save a PNG") from error
    try:
        window = tk.Tk()
        try:
            window.withdraw()
            return window.winfo_screenwidth(), window.winfo_screenheight()
        finally:
            window.destroy()
    except tk.TclError as error:
        raise ValueError(f"cannot query screen size: {error}") from error


def calculate_max_dimensions(args):
    """Return maximum data width/height in pixels, aligned to complete blocks."""
    block_size = args.pixel_size
    if block_size < 1:
        raise ValueError("pixel size must be a positive integer")
    if args.width is not None and (args.width < 1 or args.width % block_size != 0):
        raise ValueError("width must be a positive multiple of the pixel size")
    if args.height is not None and args.height < block_size:
        raise ValueError("height must fit at least one pixel-size block row")

    if args.output is None:
        screen_width, screen_height = get_screen_size()
        # Match display_image's window allowance, then exclude quiet margins
        # and the dotted frame. Explicit dimensions remain upper bounds.
        width = screen_width - 100 - 2 * BLACK_MARGIN - 2 * block_size
        height = screen_height - 150 - 2 * BLACK_MARGIN - 2 * block_size
        if args.width is not None:
            width = min(width, args.width)
        if args.height is not None:
            height = min(height, args.height)
    else:
        width = args.width if args.width is not None else 320 * block_size
        height = args.height if args.height is not None else 320

    width = width // block_size * block_size
    height = height // block_size * block_size
    if width < block_size or height < block_size:
        raise ValueError("available dimensions are too small to fit the bitmap frame and margins")
    return width, height


def display_image(image, title):
    """Display the image without resampling, allowing large images to scroll."""
    try:
        import tkinter as tk
        from PIL import ImageTk
    except ImportError as error:
        raise ValueError("Tkinter is required to display images; use -O to save a PNG") from error

    try:
        window = tk.Tk()
        window.withdraw()
        window.title(title)
        window.bind("<Escape>", lambda event: window.destroy())
        canvas = tk.Canvas(
            window,
            width=min(image.width, max(1, window.winfo_screenwidth() - 100)),
            height=min(image.height, max(1, window.winfo_screenheight() - 150)),
            background="black", highlightthickness=0,
            scrollregion=(0, 0, image.width, image.height),
        )
        horizontal = tk.Scrollbar(window, orient="horizontal", command=canvas.xview)
        vertical = tk.Scrollbar(window, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        window.rowconfigure(0, weight=1)
        window.columnconfigure(0, weight=1)
        # Keep the PhotoImage alive until the window closes; Tk does not own
        # its Python reference. Canvas scrolling never resizes the image.
        photo = ImageTk.PhotoImage(image, master=window)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        window.update_idletasks()
        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        left = max(0, (window.winfo_screenwidth() - width) // 2)
        top = max(0, (window.winfo_screenheight() - height) // 2)
        window.geometry(f"{width}x{height}+{left}+{top}")
        window.deiconify()
        window.mainloop()
    except tk.TclError as error:
        raise ValueError(f"cannot display image: {error}; use -O to save a PNG") from error


def make_image(data, columns, block_size, margin=BLACK_MARGIN):
    """Build the bit grid, dotted frame and quiet margin as a Pillow image."""
    # Build a logical grid first: one pixel per bit, plus one border cell
    # on each side. Round up to a full row; even an empty file gets one row.
    rows = max(1, (len(data) * 8 + columns - 1) // columns)
    grid = Image.new("1", (columns + 2, rows + 2), 0)
    # White cells have even (column + row) parity around the entire frame.
    # These dots establish the bounds independently of the data, including
    # data rows or columns that are entirely black.
    for column in range(columns + 2):
        grid.putpixel((column, 0), 255 if column % 2 == 0 else 0)
        grid.putpixel((column, rows + 1), 255 if (column + rows + 1) % 2 == 0 else 0)
    for row in range(rows + 2):
        grid.putpixel((0, row), 255 if row % 2 == 0 else 0)
        grid.putpixel((columns + 1, row), 255 if (columns + 1 + row) % 2 == 0 else 0)
    # Write each byte most-significant bit first. Modulo selects its data
    # column, integer division selects its row, and +1 skips the frame.
    # Cells after the last input bit remain black padding.
    for byte_index, byte in enumerate(data):
        for bit_index in range(8):
            pixel_index = byte_index * 8 + bit_index
            position = (
                1 + pixel_index % columns,
                1 + pixel_index // columns,
            )
            grid.putpixel(position, 255 if byte & (1 << (7 - bit_index)) else 0)
    # Nearest-neighbor enlargement repeats each logical cell as a solid
    # P x P square without introducing gray values at the block edges.
    enlarged = grid.resize(
        (grid.width * block_size, grid.height * block_size),
        Image.Resampling.NEAREST,
    )
    # Add the black quiet margin outside the dotted frame.
    # Width: (columns + 2) * P + 2 * margin pixels.
    image = Image.new("1", (enlarged.width + 2 * margin, enlarged.height + 2 * margin), 0)
    image.paste(enlarged, (margin, margin))
    return image


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("--help", action="help", help="show this help message and exit")
    parser.add_argument("filename", type=Path, help="input file to encode")
    parser.add_argument(
        "-O", "--output", type=Path, help="output PNG filename (default: display in Tkinter)"
    )
    parser.add_argument(
        "-p", "--pixel-size", type=int, default=2, metavar="P",
        help="pixels per bit along each axis; positive integer (default: 2)",
    )
    parser.add_argument(
        "-w", "--width", type=int, metavar="PIXELS",
        help="data width limit in pixels; multiple of P (default: screen, or 320 * P with -O)",
    )
    parser.add_argument(
        "-h", "--height", type=int, metavar="PIXELS",
        help="data height limit in pixels, excluding border/margins (default: screen, or 320 with -O)",
    )
    args = parser.parse_args()
    try:
        max_width, max_height = calculate_max_dimensions(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    block_size = args.pixel_size
    # Width is in rendered pixels; divide by P to obtain the logical bit count.
    columns = max_width // block_size
    capacity = columns * (max_height // block_size) // 8
    output = args.output

    try:
        if output is not None and args.filename.resolve() == output.resolve():
            parser.error("output filename must be different from the input filename")
        # Read one extra byte so oversized files are rejected, not silently truncated.
        with args.filename.open("rb") as source:
            data = source.read(capacity + 1)
        if len(data) > capacity:
            parser.error(f"input exceeds the bitmap capacity of {capacity:,} bytes")

        if output is None:
            # Prefer a compact, nearly square grid, but widen it if necessary
            # to fit all bits within the maximum number of data rows.
            bits = max(1, len(data) * 8)
            max_rows = max_height // block_size
            min_columns = (bits + max_rows - 1) // max_rows
            columns = min(columns, max(min_columns, isqrt(bits - 1) + 1))

        image = make_image(data, columns, block_size)
        if output is not None:
            image.save(output, format="PNG")
        else:
            display_image(image, f"Bit encoder - {args.filename.name}")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()