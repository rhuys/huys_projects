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
in the last row stay black. A versioned binary header stores the UTF-8 filename,
original size, compressed size and SHA-256 checksum. File data is compressed
with zlib, then split into sections if necessary. Each section repeats the
header with its number, total section count and a CRC32 protecting the header
and compressed chunk. Inputs over 10,000,000 bytes print a compression notice.
For graphical output, determine maximum dimensions from the screen before
reading the input. Unspecified dimensions use the screen limits; explicit
-w and -h values remain
upper bounds; the frame, margins and space for window decorations also
count toward the screen limit. The graphical layout prefers a compact,
nearly square grid within these limits. Capacity must fit a header and payload.
Use -O / --output to save a PNG. Otherwise, display the image at native
pixel size in a centered Tkinter window, with scrollbars for larger images.
Multipart PNG outputs use names such as out_01.png, out_02.png. In the window,
Space or Right selects the next section; Left selects the previous section.
Escape closes the window. Section numbering is shown above the bitmap.
This format is not compatible with the earlier single-pixel format.
"""

import argparse
import hashlib
import struct
import sys
import zlib
from math import isqrt
from pathlib import Path

from PIL import Image

BLACK_MARGIN = 15
MAGIC = b"BITENC01"
HEADER = struct.Struct(">8sHQQ32s")
SECTION_MAGIC = b"BITENC02"
SECTION_HEADER = struct.Struct(">8sHQQ32sIIQI")


def pack_file(filename, data):
    """Prefix zlib-compressed data with a binary header and UTF-8 basename."""
    name = filename.encode("utf-8")
    if not name or len(name) > 65535:
        raise ValueError("filename must contain between 1 and 65535 UTF-8 bytes")
    compressed = zlib.compress(data, level=9)
    # Network byte order: magic/version, name length, original byte count,
    # compressed byte count, SHA-256 of the original file, then name and data.
    return (
        HEADER.pack(MAGIC, len(name), len(data), len(compressed), hashlib.sha256(data).digest())
        + name
        + compressed
    )


def pack_sections(filename, data, capacity):
    """Compress once and split into independently checked bitmap packets."""
    name = filename.encode("utf-8")
    if not name or len(name) > 65535:
        raise ValueError("filename must contain between 1 and 65535 UTF-8 bytes")
    chunk_size = capacity - SECTION_HEADER.size - len(name)
    if chunk_size < 1:
        raise ValueError("bitmap capacity must fit a section header, filename and payload")
    if len(data) > 10_000_000:
        print(f"compressing file {filename} with size {len(data)}...", file=sys.stderr, flush=True)
    compressed = zlib.compress(data, level=9)
    checksum = hashlib.sha256(data).digest()
    count = (len(compressed) + chunk_size - 1) // chunk_size
    sections = []
    for index in range(count):
        chunk = compressed[index * chunk_size:(index + 1) * chunk_size]
        # The section CRC also protects metadata: a damaged section number or
        # filename must not poison the receiver's in-progress transfer.
        fields = (SECTION_MAGIC, len(name), len(data), len(compressed), checksum, index + 1, count, len(chunk))
        header = SECTION_HEADER.pack(*fields, 0)
        crc = zlib.crc32(header + name + chunk)
        sections.append(SECTION_HEADER.pack(*fields, crc) + name + chunk)
    return sections


def enable_dpi_awareness():
    """Prevent Windows from bitmap-stretching Tk windows on the system display."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()


def get_screen_size():
    """Query Tk's screen dimensions without leaving a second window open."""
    enable_dpi_awareness()
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


def display_image(image, title, section_count=1, get_section=None):
    """Display native pixels; lazily render sections with Space/arrow navigation."""
    enable_dpi_awareness()
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
        canvas_row = 0
        if section_count > 1:
            status = tk.Label(window, text=f"section 1 of {section_count}, press space for next section")
            status.grid(row=0, column=0, columnspan=2, sticky="ew")
            canvas_row = 1
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
        canvas.grid(row=canvas_row, column=0, sticky="nsew")
        vertical.grid(row=canvas_row, column=1, sticky="ns")
        horizontal.grid(row=canvas_row + 1, column=0, sticky="ew")
        window.rowconfigure(canvas_row, weight=1)
        window.columnconfigure(0, weight=1)
        # Keep the PhotoImage alive until the window closes; Tk does not own
        # its Python reference. Canvas scrolling never resizes the image.
        photo = ImageTk.PhotoImage(image, master=window)
        image_item = canvas.create_image(0, 0, image=photo, anchor="nw")
        current_section = 0

        def select_section(index):
            nonlocal photo, current_section
            if 0 <= index < section_count and index != current_section:
                next_image = get_section(index)
                photo = ImageTk.PhotoImage(next_image, master=window)
                canvas.itemconfigure(image_item, image=photo)
                canvas.configure(scrollregion=(0, 0, next_image.width, next_image.height))
                canvas.xview_moveto(0)
                canvas.yview_moveto(0)
                current_section = index
                status.configure(text=f"section {index + 1} of {section_count}, press space for next section")
            return "break"

        if section_count > 1:
            window.bind("<space>", lambda event: select_section(current_section + 1))
            window.bind("<Right>", lambda event: select_section(current_section + 1))
            window.bind("<Left>", lambda event: select_section(current_section - 1))
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
    parser.add_argument("-h", "--help", action="help", help="show this help message and exit")
    parser.add_argument("filename", type=Path, help="input file to encode")
    parser.add_argument(
        "-O", "--output", type=Path, help="output PNG filename (default: display in Tkinter)"
    )
    parser.add_argument(
        "-p", "--pixel-size", type=int, default=2, metavar="P",
        help="pixels per bit along each axis; positive integer (default: 2)",
    )
    parser.add_argument(
        "-W", "--width", type=int, metavar="PIXELS",
        help="data width limit in pixels; multiple of P (default: screen, or 320 * P with -O)",
    )
    parser.add_argument(
        "-H", "--height", type=int, metavar="PIXELS",
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
        try:
            file_data = args.filename.read_bytes()
        except OSError as error:
            parser.error(f"cannot read input file {str(args.filename)!r}: {error}")
        sections = pack_sections(args.filename.name, file_data, capacity)

        if output is None:
            # Prefer a compact, nearly square grid, but widen it if necessary
            # to fit all bits within the maximum number of data rows.
            bits = max(map(len, sections)) * 8
            max_rows = max_height // block_size
            min_columns = (bits + max_rows - 1) // max_rows
            columns = min(columns, max(min_columns, isqrt(bits - 1) + 1))

        if output is not None:
            paths = [output] if len(sections) == 1 else [
                output.with_name(f"{output.stem}_{index:02d}{output.suffix}")
                for index in range(1, len(sections) + 1)
            ]
            if any(path.resolve() == args.filename.resolve() for path in paths):
                parser.error("output filename must be different from the input filename")
            for packet, path in zip(sections, paths):
                make_image(packet, columns, block_size).save(path, format="PNG")
        else:
            image = make_image(sections[0], columns, block_size)
            title = f"Bit encoder - {args.filename.name}"
            if len(sections) == 1:
                display_image(image, title)
            else:
                display_image(
                    image, title, section_count=len(sections),
                    get_section=lambda index: make_image(sections[index], columns, block_size),
                )
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()