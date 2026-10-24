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
The header and compressed payload must fit the selected bitmap dimensions.

```sh
bitenc input.bin -O encoded.png
bitdec encoded.png
bitdec encoded.png -O restored.bin
```

Without `-O`, `bitenc` displays a centered Tkinter window, while `bitdec` saves
the validated file under its received basename in the current directory.
Automatic saves refuse to overwrite existing files; `-O` explicitly chooses
an output path and permits replacement, except for the input bitmap itself.
Running `bitdec` without an input image waits for a bitmap on the clipboard.

Successful decoding prints `received file <filename> , <size> bytes`.
Corrupt file packets print `checksum failure, please try again` and are not
saved. Original byte counts remove row padding without stripping real zero
bytes from the file. Older bitmaps without this header must be re-encoded.

Use `bitenc --help` and `bitdec --help` for options.

