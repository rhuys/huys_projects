# HUYS_PROJECTS 

My small python projects
Created by Roeland Huys 2024 
Find me on GIT: `https://github.com/rhuys/huys_projects.git`


# INSTALLATION FOR DEVELOPMENT

* Extract from Gitlab: `git clone git@github.com:rhuys/huys_projects.git` 
* Activate your local venv (see below)
* Inside the folder, install the package in editing mode: `pip install -e .`  
* You also need to install **pyhuys**: see `https://imec.ghe.com/huys100/pyhuys/blob/main/README.md` for installation
* Fore more, see [Installation and usage instructions](INSTALLATION.md) 

After installation, activate the same virtual environment to use `ocr`, `enc64`, and `image_viewer` from any working directory. `ocr` reads an image from the clipboard; `enc64 --help` shows the file encoder options.

## Bitmap File Transfer

`bitenc` compresses a file with zlib and adds a binary header containing its
UTF-8 basename, original byte count, compressed byte count and SHA-256 checksum.
The compressed stream is split when it exceeds the bitmap capacity. Every
section repeats the header with its section number and total count, and a
CRC32 covering that section's header, filename and compressed chunk. The final
SHA-256 verifies the original file after all sections are reassembled.
Inputs over 10,000,000 bytes print a notice before compression.

```sh
bitenc input.bin -O encoded.png
bitdec encoded.png
bitdec encoded.png -O restored.bin
bitenc input.bin -w 320 -h 320 -O part.png
bitdec "part_*.png" -O restored.bin
```

Without `-O`, `bitenc` displays a centered Tkinter window, while `bitdec` saves
the validated file under its received basename in the current directory.
All saves ask `Overwrite file <filename>?  Y / n` before replacing an existing
file: Enter or Y confirms, and n cancels. `-O` chooses an output path but still
asks before replacement. The input bitmap itself can never be overwritten.
Running `bitdec` without an input image waits for a bitmap on the clipboard.
Multipart output uses `part_01.png`, `part_02.png`, etc.; a single section keeps
the requested filename. In the Tkinter window, Space or Right advances,
Left goes back, and Escape closes the window. A section counter appears above
the bitmap. Sections render on demand rather than opening separate windows.

The decoder accepts explicit filenames, shell-expanded filenames or quoted
glob patterns on Windows/Linux. Sections can arrive in any order; duplicate
sections are ignored. Only one original file is accepted per invocation.
Missing file inputs report `only received N of M sections, please provide all
sections in the input files`. Clipboard mode keeps waiting for new images,
reports progress, and saves automatically when the transfer is complete.

Successful decoding prints `received file <filename> , <size> bytes`.
A corrupt section prints a warning and can be retried without discarding good
sections. A final file checksum failure prints `checksum failure, please try
again`; no partial file is saved. Original byte counts remove row padding
without stripping real zero bytes. Existing BITENC01 single-image transfers
remain supported; older headerless bitmaps must be re-encoded.

Use `bitenc --help` and `bitdec --help` for options.

