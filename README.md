# PDFTools

![Python](https://img.shields.io/badge/Python-3.9+-blue?style=flat-square&logo=python)
![CustomTkinter](https://img.shields.io/badge/CustomTkinter-5.x-orange?style=flat-square&logo=python)
![qpdf](https://img.shields.io/badge/qpdf-11%2B-lightgrey?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows)

A simple desktop app to **split** and **merge** PDF files. Drag and drop your documents, choose how you want them cut or combined, and click one button. Built with CustomTkinter for a clean dark interface, and powered by [qpdf](https://qpdf.sourceforge.io/) so your pages are never re-rendered: text, images and quality stay exactly the same.

![PDF Splitter](assets/split.png)

## ✨ Features

### ✂️ Split
- **By page count**: e.g. one file every 30 pages.
- **By maximum size (KB)**: perfect for email or upload limits. The app finds the largest page range that stays under the limit for every part.
- **Clear file names**: `part_1_pages_1-30.pdf`, `part_2_pages_31-60.pdf`, …

### 🔗 Merge
- **Add many PDFs at once**: drag and drop files, or a whole folder (sorted in natural order: `file2` before `file10`).
- **Reorder easily**: Move up / Move down buttons, or `Alt + ↑ / ↓`. Remove with `Delete`.
- **Lossless size optimization** (optional).
- **Handles large batches**: very long file lists are merged in several passes automatically.

### 🛡️ Everyday comfort
- **Drag and drop** everywhere.
- **No console windows**: qpdf runs silently in the background.
- **Responsive UI**: work happens in a background thread with a progress bar.
- **Safety checks**: invalid names, overwriting an input file, existing output folders, unreadable PDFs (the faulty file is named in the error).

![PDF Merger](assets/merge.png)

## 📋 Requirements

- **Python 3.9+**: download it from the [official website](https://www.python.org/).
- **qpdf**: the PDF engine used under the hood.
  ```bash
  winget install qpdf
  ```
  or download it from the [qpdf releases](https://github.com/qpdf/qpdf/releases).
- **Python libraries**: `customtkinter` and `tkinterdnd2`.

## 🛠️ Installation

1. **Clone this repository**:
    ```bash
    git clone https://github.com/darrengls/PDFTools
    cd PDFTools
    ```

2. **Install the required libraries**:
    ```bash
    pip install -r requirements.txt
    ```

3. **Run the program**:
    ```bash
    python pdf_tools.py
    ```

The app finds qpdf automatically (bundled `qpdf_bin` folder, `PATH`, `Program Files` or WinGet).

## 📦 Build a standalone .exe

Create a single `PDF Tools.exe` that works on any Windows PC, **without Python or qpdf installed**.

1. Create a `qpdf_bin` folder next to `pdf_tools.py`.
2. Copy **everything** from `C:\Program Files\qpdf X.Y.Z\bin\` into it (`qpdf.exe` **and** all the `.dll` files).
3. Double-click `build_exe.bat`, or run:
    ```bash
    pyinstaller --noconfirm --onefile --windowed --name "PDF Tools" --collect-all customtkinter --collect-all tkinterdnd2 --add-data "qpdf_bin;qpdf_bin" pdf_tools.py
    ```
4. Your app is ready in `dist\PDF Tools.exe` 🎉

> 💡 If the `.exe` starts slowly or your antivirus complains, replace `--onefile` with `--onedir` and share the whole `dist\PDF Tools\` folder.

## 📂 Project Structure

- `pdf_tools.py`: The main application (interface + split / merge logic).
- `requirements.txt`: Python dependencies.
- `build_exe.bat`: One-click script to build the Windows executable.
- `assets/`: Screenshots used in this README.
- `README.md`: Instructions and documentation for the project.

## 📖 How It Works

1. **Split by pages**: the PDF is cut into fixed ranges, each one extracted with `qpdf --pages`.
2. **Split by size**: for each part, the app first tries all remaining pages, then uses a **binary search** to find the biggest page range whose output stays under the maximum size.
3. **Merge**: every file is checked first (page count), then qpdf combines them in the order shown in the list.
4. **Optimization**: object streams are generated and Flate streams recompressed. This is **lossless**: JPEG images are never recompressed, so quality is preserved.

> ⚠️ Bookmarks (outlines) from the source files are not carried over when merging. Pages, links and form fields are kept.

## ⚡ Technologies Used

- **Python**: The programming language used for this project.
- **CustomTkinter**: Modern-looking widgets on top of Tkinter.
- **tkinterdnd2**: Native drag and drop support.
- **qpdf**: Fast, lossless PDF manipulation.
- **PyInstaller**: Packaging into a standalone Windows executable.

## 🔗 License

This project is open-source and available under the MIT License. Feel free to fork, modify, and use it in your projects.

---

Enjoy splitting and merging your PDFs in a couple of clicks! 📄✂️🔗
