# PDFTools

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat-square&logo=python)
![CustomTkinter](https://img.shields.io/badge/CustomTkinter-5.x-orange?style=flat-square&logo=python)

A simple desktop app to split and merge PDF files. Drag and drop your documents, choose how you want them cut or combined, and click one button. The interface is built with CustomTkinter, and the PDF work is done by qpdf, so pages are never re-rendered: text, images and quality stay exactly the same.

## ✨ Features

- **Split by Pages**: Cut a PDF into files with a fixed number of pages (e.g. one file every 30 pages).
- **Split by Size**: Cut a PDF into files that stay under a maximum size in KB, perfect for email or upload limits.
- **Merge PDFs**: Combine several PDFs into one, in the order you choose (Move up / Move down, or `Alt + ↑ / ↓`).
- **Drag and Drop**: Drop files, or a whole folder, directly into the app.
- **Lossless Optimization**: Reduces file size without touching image quality.

## 🚀 Download

The ready-to-use Windows app is available in the `dist` folder: [PDF_Splitter.exe](https://github.com/darrengls/PDFTools/raw/main/dist/PDF_Splitter.exe)

Just download it and double-click. No Python or qpdf installation is needed, everything is bundled inside.

## 📋 Requirements

To run or build the app from the source code:

- **Python 3.x**: Ensure you have Python installed. You can download it from the [official website](https://www.python.org/).
- **qpdf**: The PDF engine used by the app. Install it with `winget install qpdf` or from the [qpdf releases](https://github.com/qpdf/qpdf/releases).
- **CustomTkinter and tkinterdnd2**: Used for the interface and drag and drop.

## 🛠️ Installation

1. **Clone this repository**:
    ```bash
    git clone https://github.com/darrengls/PDFTools
    cd PDFTools
    ```

2. **Install the required libraries**:
    ```bash
    pip install customtkinter tkinterdnd2
    ```

3. **Run the program**:
    ```bash
    python split.py
    ```

## 📦 Build the .exe

1. **Install PyInstaller**:
    ```bash
    pip install pyinstaller
    ```

2. **Build the app** (qpdf is bundled inside the .exe):
    ```bash
    pyinstaller --noconfirm --onefile --windowed --name "PDF_Splitter" --collect-all customtkinter --collect-all tkinterdnd2 --add-binary "C:\Program Files\qpdf 12.4.2\bin\*;qpdf_bin" split.py
    ```
    If you have another qpdf version, change `qpdf 12.4.2` to match your folder in `C:\Program Files`.

3. **Get your app** in `dist\PDF_Splitter.exe`.

## 📂 Project Structure

- `split.py`: The main Python script that runs the app.
- `dist/PDF_Splitter.exe`: The compiled Windows app, ready to use.
- `assets/`: Screenshots used in this README.
- `README.md`: Instructions and documentation for the project.

## 📖 How It Works

1. **Split**: The PDF is cut into page ranges with qpdf. In size mode, the app searches for the biggest range of pages that stays under the maximum size.
2. **Merge**: Each file is checked first, then qpdf combines them in the order shown in the list.
3. **Optimization**: The PDF structure is rebuilt and compressed without recompressing images, so the quality is preserved.

## ⚡ Technologies Used

- **Python**: The programming language used for this project.
- **CustomTkinter**: A library that provides modern-looking widgets for Tkinter.
- **qpdf**: A command-line tool for fast and lossless PDF manipulation.
- **PyInstaller**: A tool that packages the app into a standalone Windows executable.

## 📸 Screenshot

![PDF Splitter](assets/split.png)

## 🔗 License

This project is open-source and available under the MIT License. Feel free to fork, modify, and use it in your projects.

---

Enjoy splitting and merging your PDFs in just a few clicks!

![PDF Merger](assets/merge.png)
