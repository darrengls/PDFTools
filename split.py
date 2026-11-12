import os
import re
import sys
import queue
import shutil
import tempfile
import threading
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD


# ============================================================
# COLORS
# ============================================================

BACKGROUND = "#0B0B0B"
SURFACE = "#151515"
SURFACE_2 = "#1D1D1D"
SURFACE_3 = "#252525"

BORDER = "#393939"
BORDER_LIGHT = "#565656"

WHITE = "#FFFFFF"
TEXT_MUTED = "#B8B8B8"
TEXT_DIM = "#8F8F8F"

ORANGE = "#FF7900"
ORANGE_HOVER = "#E66D00"

DARK_BUTTON = "#303030"
DARK_BUTTON_HOVER = "#474747"
DISABLED_BUTTON = "#5A5A5A"

SUCCESS = "#68D391"
ERROR = "#FF5A5F"


# ============================================================
# QPDF SETTINGS
# ============================================================

# Lossless optimization: rebuilds the PDF structure and recompresses
# Flate streams. JPEG images are never recompressed.
QPDF_OPTIMIZE_ARGS = [
    "--object-streams=generate",
    "--compress-streams=y",
    "--recompress-flate",
    "--decode-level=generalized",
]

# Windows command lines are limited to 32,767 characters.
# Large merges are done in several qpdf passes below this limit.
MAX_COMMAND_LENGTH = 24000

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


# Must be set before the main window is created.
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class QPDFError(Exception):
    pass


class RequestedSizeImpossibleError(Exception):
    pass


def natural_sort_key(path):
    """Sorts 'file2.pdf' before 'file10.pdf'."""
    name = os.path.basename(path).lower()
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", name)
    ]


def format_size(size_bytes):
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


class PDFToolsApp(TkinterDnD.DnDWrapper, ctk.CTk):
    def __init__(self):
        ctk.CTk.__init__(self)
        self.TkdndVersion = TkinterDnD._require(self)

        # Shared state
        self.qpdf_path = self.find_qpdf()
        self.is_processing = False
        self.current_mode = "split"

        # Worker threads never touch widgets directly. They put callbacks
        # in this queue and the main thread runs them.
        self.ui_queue = queue.Queue()

        # Split state
        self.selected_pdf = None
        self.split_output_folder = None
        self.split_output_var = ctk.StringVar(
            value="Same location as selected PDF"
        )

        # Merge state
        self.merge_files = []
        self.merge_output_folder = None
        self.merge_output_var = ctk.StringVar(
            value="Same location as first PDF"
        )
        self.merge_optimize_var = ctk.BooleanVar(value=True)

        self.title("PDF Tools")
        self.geometry("1120x720")
        self.minsize(1000, 660)
        self.configure(fg_color=BACKGROUND)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.create_interface()
        self.switch_mode("Split")

        self.after(50, self.process_ui_queue)

    # ============================================================
    # THREAD-SAFE UI UPDATES
    # ============================================================

    def ui(self, callback, *args):
        """Schedules a callback on the main (Tk) thread."""
        self.ui_queue.put((callback, args))

    def process_ui_queue(self):
        try:
            while True:
                callback, args = self.ui_queue.get_nowait()
                callback(*args)
        except queue.Empty:
            pass

        self.after(50, self.process_ui_queue)

    # ============================================================
    # WINDOWS SUBPROCESS SETTINGS
    # Prevent qpdf from opening CMD windows.
    # ============================================================

    @staticmethod
    def get_hidden_subprocess_options():
        """
        Returns subprocess settings that prevent console / CMD windows
        from appearing when qpdf.exe is executed on Windows.
        """

        options = {
            "capture_output": True,
            # Required in a --windowed PyInstaller EXE: there is no
            # console, so stdin must be redirected explicitly or
            # subprocess fails with "The handle is invalid".
            "stdin": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }

        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            options["startupinfo"] = startupinfo
            options["creationflags"] = subprocess.CREATE_NO_WINDOW

        return options

    def run_qpdf_command(self, command):
        """Runs qpdf without showing a terminal window."""
        return subprocess.run(
            command,
            **self.get_hidden_subprocess_options()
        )

    # ============================================================
    # QPDF DETECTION
    # ============================================================

    @staticmethod
    def resource_path(relative_path):
        """
        Works both:
        - while running the .py file directly;
        - while running the PyInstaller EXE.
        """

        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        return os.path.join(base_path, relative_path)

    def find_qpdf(self):
        """
        Finds qpdf from:
        1. qpdf packaged inside the EXE (qpdf_bin folder);
        2. PATH;
        3. standard Program Files locations;
        4. qpdf version folders in Program Files;
        5. WinGet package folders.
        """

        executable = "qpdf.exe" if sys.platform.startswith("win") else "qpdf"

        bundled_qpdf = self.resource_path(
            os.path.join("qpdf_bin", executable)
        )

        if os.path.isfile(bundled_qpdf):
            return bundled_qpdf

        qpdf_in_path = shutil.which("qpdf")

        if qpdf_in_path:
            return qpdf_in_path

        if not sys.platform.startswith("win"):
            return None

        common_paths = [
            r"C:\Program Files\qpdf 12.4.2\bin\qpdf.exe",
            r"C:\Program Files\qpdf\bin\qpdf.exe",
            r"C:\Program Files\QPDF\bin\qpdf.exe",
            r"C:\Program Files (x86)\qpdf\bin\qpdf.exe",
            r"C:\Program Files (x86)\QPDF\bin\qpdf.exe",
        ]

        for path in common_paths:
            if os.path.isfile(path):
                return path

        for program_files in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            if not os.path.isdir(program_files):
                continue

            try:
                # Newest version first, e.g. "qpdf 12.4.2" before "qpdf 11.9.0".
                folders = sorted(
                    os.listdir(program_files),
                    key=natural_sort_key,
                    reverse=True
                )

                for folder_name in folders:
                    if folder_name.lower().startswith("qpdf"):
                        possible_path = os.path.join(
                            program_files,
                            folder_name,
                            "bin",
                            "qpdf.exe"
                        )

                        if os.path.isfile(possible_path):
                            return possible_path
            except OSError:
                pass

        local_app_data = os.environ.get("LOCALAPPDATA", "")

        winget_folder = os.path.join(
            local_app_data,
            "Microsoft",
            "WinGet",
            "Packages"
        )

        if local_app_data and os.path.isdir(winget_folder):
            try:
                for root, _, files in os.walk(winget_folder):
                    if "qpdf.exe" in files:
                        return os.path.join(root, "qpdf.exe")
            except OSError:
                pass

        return None

    # ============================================================
    # REUSABLE WIDGETS
    # ============================================================

    @staticmethod
    def font(size, bold=False):
        return ctk.CTkFont(
            family="Arial",
            size=size,
            weight="bold" if bold else "normal"
        )

    def create_primary_button(self, parent, text, command, width=190, height=42):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=0,
            fg_color=ORANGE,
            hover_color=ORANGE_HOVER,
            text_color=BACKGROUND,
            font=self.font(14, bold=True)
        )

    def create_secondary_button(self, parent, text, command, width=120, height=38):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=0,
            fg_color=DARK_BUTTON,
            hover_color=DARK_BUTTON_HOVER,
            text_color=WHITE,
            font=self.font(13, bold=True)
        )

    def create_entry(self, parent, width=140):
        return ctk.CTkEntry(
            parent,
            width=width,
            height=36,
            corner_radius=0,
            fg_color=SURFACE_3,
            border_color=BORDER_LIGHT,
            text_color=WHITE,
            font=self.font(14)
        )

    @staticmethod
    def create_divider(parent):
        return ctk.CTkFrame(
            parent,
            height=1,
            fg_color=BORDER,
            corner_radius=0
        )

    def create_form_label(self, parent, text):
        return ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            text_color=WHITE,
            font=self.font(14, bold=True)
        )

    def create_card_heading(self, parent, number, title, description):
        heading = ctk.CTkFrame(
            parent,
            fg_color="transparent",
            corner_radius=0
        )
        heading.grid_columnconfigure(1, weight=1)

        number_box = ctk.CTkFrame(
            heading,
            width=30,
            height=30,
            fg_color=ORANGE,
            corner_radius=0
        )
        number_box.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="ns",
            padx=(0, 12)
        )
        number_box.grid_propagate(False)

        ctk.CTkLabel(
            number_box,
            text=number,
            text_color=BACKGROUND,
            font=self.font(15, bold=True)
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            heading,
            text=title,
            anchor="w",
            text_color=WHITE,
            font=self.font(17, bold=True)
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            heading,
            text=description,
            anchor="w",
            justify="left",
            text_color=TEXT_DIM,
            font=self.font(12)
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        return heading

    def create_view_container(self):
        container = ctk.CTkFrame(
            self,
            fg_color=SURFACE,
            corner_radius=0,
            border_width=1,
            border_color=BORDER
        )
        container.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=42,
            pady=(0, 14)
        )

        container.grid_columnconfigure(0, weight=1, uniform="cards")
        container.grid_columnconfigure(1, weight=1, uniform="cards")
        container.grid_rowconfigure(0, weight=1)

        return container

    def create_settings_card_frame(self, parent, title, description):
        card = ctk.CTkFrame(
            parent,
            fg_color=SURFACE_2,
            corner_radius=0,
            border_width=1,
            border_color=BORDER
        )
        card.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(18, 28),
            pady=24
        )
        card.grid_columnconfigure(0, weight=1)

        self.create_card_heading(
            parent=card,
            number="2",
            title=title,
            description=description
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 12))

        self.create_divider(card).grid(row=1, column=0, sticky="ew", padx=22)

        form = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        form.grid(row=2, column=0, sticky="ew", padx=22, pady=(14, 16))
        form.grid_columnconfigure(0, minsize=150)
        form.grid_columnconfigure(1, weight=1)

        return card, form

    def create_location_box(self, parent, row, textvariable, command):
        """
        Read-only, single-line path display with a 'Change folder' button.
        Long paths scroll horizontally instead of wrapping.
        """

        location_box = ctk.CTkFrame(
            parent,
            fg_color=SURFACE_3,
            corner_radius=0,
            border_width=1,
            border_color=BORDER_LIGHT
        )
        location_box.grid(row=row, column=0, columnspan=2, sticky="ew")
        location_box.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(
            location_box,
            textvariable=textvariable,
            height=36,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
            text_color=TEXT_MUTED,
            font=self.font(12),
            state="readonly"
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(12, 10), pady=4)

        self.create_secondary_button(
            location_box,
            text="Change folder",
            command=command,
            width=160,
            height=36
        ).grid(row=0, column=1, sticky="e", padx=(0, 8), pady=4)

        return entry

    def register_drop_target(self, widget, handler):
        """
        Registers a widget AND all of its children as drop targets.
        CustomTkinter widgets are made of inner tk widgets (canvas,
        label...), so registering only the outer frame misses drops
        that land on the text.
        """

        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", handler)
        except (AttributeError, tk.TclError):
            pass

        for child in widget.winfo_children():
            self.register_drop_target(child, handler)

    def set_path_display(self, entry, variable, folder_path):
        variable.set(str(folder_path))

        # Keep the beginning of the path visible.
        self.after(50, lambda: entry.xview_moveto(0))

    # ============================================================
    # UI
    # ============================================================

    def create_interface(self):
        self.create_header()

        self.split_view = self.create_view_container()
        self.create_split_pdf_card(self.split_view)
        self.create_split_settings_card(self.split_view)

        self.merge_view = self.create_view_container()
        self.create_merge_files_card(self.merge_view)
        self.create_merge_settings_card(self.merge_view)

        self.create_footer()

    def create_header(self):
        header = ctk.CTkFrame(self, fg_color=BACKGROUND, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=42, pady=(22, 16))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkFrame(
            header,
            width=12,
            height=54,
            fg_color=ORANGE,
            corner_radius=0
        ).grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 16))

        self.header_title = ctk.CTkLabel(
            header,
            text="PDF splitter",
            anchor="w",
            text_color=WHITE,
            font=self.font(30, bold=True)
        )
        self.header_title.grid(row=0, column=1, sticky="sw")

        self.header_subtitle = ctk.CTkLabel(
            header,
            text="Split PDF files by page count or maximum size.",
            anchor="w",
            text_color=TEXT_MUTED,
            font=self.font(14)
        )
        self.header_subtitle.grid(row=1, column=1, sticky="nw", pady=(2, 0))

        self.mode_switch = ctk.CTkSegmentedButton(
            header,
            values=["Split", "Merge"],
            command=self.switch_mode,
            width=240,
            height=40,
            dynamic_resizing=False,
            corner_radius=0,
            fg_color=SURFACE_3,
            selected_color=ORANGE,
            selected_hover_color=ORANGE_HOVER,
            unselected_color=DARK_BUTTON,
            unselected_hover_color=DARK_BUTTON_HOVER,
            text_color=WHITE,
            font=self.font(14, bold=True)
        )
        self.mode_switch.grid(row=0, column=2, rowspan=2, sticky="e")
        self.mode_switch.set("Split")

    # ------------------------------------------------------------
    # SPLIT VIEW
    # ------------------------------------------------------------

    def create_split_pdf_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        card.grid(row=0, column=0, sticky="nsew", padx=(28, 18), pady=24)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        self.create_card_heading(
            parent=card,
            number="1",
            title="Select a PDF",
            description="Choose the PDF document to split."
        ).grid(row=0, column=0, sticky="ew", pady=(0, 16))

        self.drop_zone = ctk.CTkFrame(
            card,
            fg_color=SURFACE_2,
            corner_radius=0,
            border_width=2,
            border_color=ORANGE
        )
        self.drop_zone.grid(row=1, column=0, sticky="nsew")
        self.drop_zone.grid_columnconfigure(0, weight=1)
        self.drop_zone.grid_rowconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            self.drop_zone,
            text="Drag and drop your PDF here",
            text_color=WHITE,
            font=self.font(18, bold=True)
        ).grid(row=0, column=0, pady=(28, 0))

        ctk.CTkLabel(
            self.drop_zone,
            text="or choose a file from your computer",
            text_color=TEXT_MUTED,
            font=self.font(13)
        ).grid(row=1, column=0)

        self.file_name_label = ctk.CTkLabel(
            self.drop_zone,
            text="No file selected",
            text_color=ORANGE,
            wraplength=360,
            font=self.font(12)
        )
        self.file_name_label.grid(row=2, column=0, padx=12, pady=(0, 8))

        self.create_primary_button(
            self.drop_zone,
            text="Choose a PDF",
            command=self.browse_pdf
        ).grid(row=3, column=0, pady=(0, 28))

        self.register_drop_target(self.drop_zone, self.handle_split_drop)

    def create_split_settings_card(self, parent):
        _, form = self.create_settings_card_frame(
            parent,
            title="Split settings",
            description="Configure the output files and destination."
        )

        self.create_form_label(form, "Split method").grid(
            row=0, column=0, sticky="w"
        )

        self.split_mode = ctk.StringVar(value="pages")

        mode_frame = ctk.CTkFrame(form, fg_color="transparent", corner_radius=0)
        mode_frame.grid(row=0, column=1, sticky="w")

        for column, (text, value) in enumerate(
            (("Pages", "pages"), ("Max size (KB)", "size"))
        ):
            ctk.CTkRadioButton(
                mode_frame,
                text=text,
                variable=self.split_mode,
                value=value,
                command=self.update_split_mode,
                fg_color=ORANGE,
                hover_color=ORANGE_HOVER,
                border_color="#8A8A8A",
                text_color=WHITE,
                font=self.font(13)
            ).grid(row=0, column=column, padx=(0, 18))

        self.value_label = self.create_form_label(form, "Pages per file")
        self.value_label.grid(row=1, column=0, sticky="w", pady=(12, 0))

        value_frame = ctk.CTkFrame(form, fg_color="transparent", corner_radius=0)
        value_frame.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        value_frame.grid_columnconfigure(1, weight=1)

        self.split_value_entry = self.create_entry(value_frame, width=100)
        self.split_value_entry.grid(row=0, column=0, sticky="w")
        self.split_value_entry.insert(0, "30")

        self.value_description = ctk.CTkLabel(
            value_frame,
            text="Pages per output file.",
            anchor="w",
            text_color=TEXT_MUTED,
            font=self.font(12)
        )
        self.value_description.grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.create_divider(form).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=12
        )

        self.create_form_label(form, "Folder name").grid(
            row=3, column=0, sticky="w"
        )

        self.folder_name_entry = self.create_entry(form)
        self.folder_name_entry.grid(row=3, column=1, sticky="ew")
        self.folder_name_entry.insert(0, "split_pdfs")

        self.create_divider(form).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=12
        )

        self.create_form_label(form, "Output location").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        self.split_output_entry = self.create_location_box(
            form,
            row=6,
            textvariable=self.split_output_var,
            command=self.choose_split_output_folder
        )

    # ------------------------------------------------------------
    # MERGE VIEW
    # ------------------------------------------------------------

    def create_merge_files_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        card.grid(row=0, column=0, sticky="nsew", padx=(28, 18), pady=24)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        heading = self.create_card_heading(
            parent=card,
            number="1",
            title="Add PDFs",
            description="Merged top to bottom. Alt+Up / Alt+Down to reorder, "
                        "Delete to remove."
        )
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        self.merge_summary_label = ctk.CTkLabel(
            heading,
            text="No files added",
            anchor="e",
            text_color=ORANGE,
            font=self.font(13, bold=True)
        )
        self.merge_summary_label.grid(row=0, column=2, sticky="e", padx=(12, 0))

        self.merge_drop_zone = ctk.CTkFrame(
            card,
            fg_color=SURFACE_2,
            corner_radius=0,
            border_width=2,
            border_color=ORANGE
        )
        self.merge_drop_zone.grid(row=1, column=0, sticky="nsew")
        self.merge_drop_zone.grid_columnconfigure(0, weight=1)
        self.merge_drop_zone.grid_rowconfigure(0, weight=1)

        self.merge_listbox = tk.Listbox(
            self.merge_drop_zone,
            selectmode="extended",
            activestyle="none",
            bg=SURFACE_3,
            fg=WHITE,
            selectbackground=ORANGE,
            selectforeground=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            font=("Arial", 13),
            exportselection=False
        )
        self.merge_listbox.grid(
            row=0, column=0, sticky="nsew", padx=(10, 0), pady=10
        )

        scrollbar = ctk.CTkScrollbar(
            self.merge_drop_zone,
            command=self.merge_listbox.yview,
            corner_radius=0,
            fg_color=SURFACE_2,
            button_color=BORDER_LIGHT,
            button_hover_color=TEXT_DIM
        )
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 6), pady=10)
        self.merge_listbox.configure(yscrollcommand=scrollbar.set)

        self.merge_empty_label = ctk.CTkLabel(
            self.merge_drop_zone,
            text="Drag and drop PDFs or a folder here\n"
                 "or click Add PDFs",
            fg_color=SURFACE_3,
            text_color=TEXT_MUTED,
            justify="center",
            font=self.font(16, bold=True)
        )

        self.merge_listbox.bind("<Delete>", lambda _: self.remove_merge_selection())
        self.merge_listbox.bind("<BackSpace>", lambda _: self.remove_merge_selection())
        self.merge_listbox.bind("<Alt-Up>", lambda _: self.move_merge_selection(-1))
        self.merge_listbox.bind("<Alt-Down>", lambda _: self.move_merge_selection(1))

        buttons = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        button_specs = [
            ("Add PDFs", self.browse_merge_pdfs, True),
            ("Move up", lambda: self.move_merge_selection(-1), False),
            ("Move down", lambda: self.move_merge_selection(1), False),
            ("Remove", self.remove_merge_selection, False),
            ("Clear", self.clear_merge_files, False),
        ]

        for column, (text, command, primary) in enumerate(button_specs):
            buttons.grid_columnconfigure(column, weight=1, uniform="merge_buttons")

            if primary:
                button = self.create_primary_button(
                    buttons, text, command, width=80, height=38
                )
            else:
                button = self.create_secondary_button(
                    buttons, text, command, width=80, height=38
                )

            button.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 6, 0)
            )

        self.register_drop_target(self.merge_drop_zone, self.handle_merge_drop)
        self.register_drop_target(self.merge_empty_label, self.handle_merge_drop)

    def create_merge_settings_card(self, parent):
        _, form = self.create_settings_card_frame(
            parent,
            title="Merge settings",
            description="Name the merged file and choose where to save it."
        )

        self.create_form_label(form, "File name").grid(
            row=0, column=0, sticky="w"
        )

        self.merge_name_entry = self.create_entry(form)
        self.merge_name_entry.grid(row=0, column=1, sticky="ew")
        self.merge_name_entry.insert(0, "merged.pdf")

        self.create_divider(form).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=16
        )

        self.create_form_label(form, "Optimize").grid(
            row=2, column=0, sticky="w"
        )

        ctk.CTkCheckBox(
            form,
            text="Lossless size optimization",
            variable=self.merge_optimize_var,
            corner_radius=0,
            fg_color=ORANGE,
            hover_color=ORANGE_HOVER,
            border_color="#8A8A8A",
            checkmark_color=BACKGROUND,
            text_color=WHITE,
            font=self.font(13)
        ).grid(row=2, column=1, sticky="w")

        self.create_divider(form).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=16
        )

        self.create_form_label(form, "Output location").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        self.merge_output_entry = self.create_location_box(
            form,
            row=5,
            textvariable=self.merge_output_var,
            command=self.choose_merge_output_folder
        )

    # ------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------

    def create_footer(self):
        footer = ctk.CTkFrame(
            self,
            height=96,
            fg_color="#101010",
            corner_radius=0,
            border_width=1,
            border_color=BORDER
        )
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            footer,
            text="Select a PDF to start.",
            anchor="w",
            text_color=TEXT_MUTED,
            font=self.font(13)
        )
        self.status_label.grid(
            row=0, column=0, sticky="ew", padx=42, pady=(10, 5)
        )

        action_row = ctk.CTkFrame(footer, fg_color="transparent", corner_radius=0)
        action_row.grid(row=1, column=0, sticky="ew", padx=42, pady=(0, 12))
        action_row.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            action_row,
            height=8,
            corner_radius=0,
            fg_color="#3A3A3A",
            progress_color=ORANGE
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 18))
        self.progress_bar.set(0)

        self.action_button = ctk.CTkButton(
            action_row,
            text="Split PDF",
            command=self.start_action,
            width=190,
            height=44,
            corner_radius=0,
            fg_color=ORANGE,
            hover_color=ORANGE_HOVER,
            text_color=BACKGROUND,
            text_color_disabled=WHITE,
            font=self.font(15, bold=True)
        )
        self.action_button.grid(row=0, column=1, sticky="e")

    # ============================================================
    # MODE SWITCHING
    # ============================================================

    def switch_mode(self, value):
        if self.is_processing:
            # Should not happen (the switch is disabled), but stay safe.
            self.mode_switch.set(self.current_mode.capitalize())
            return

        self.current_mode = value.lower()

        if self.current_mode == "split":
            self.merge_view.grid_remove()
            self.split_view.grid()
            self.header_title.configure(text="PDF splitter")
            self.header_subtitle.configure(
                text="Split PDF files by page count or maximum size."
            )
        else:
            self.split_view.grid_remove()
            self.merge_view.grid()
            self.header_title.configure(text="PDF merger")
            self.header_subtitle.configure(
                text="Combine several PDF files into a single document."
            )

        self.refresh_action_button()
        self.progress_bar.set(0)
        self.show_idle_status()

    def refresh_action_button(self, text=None):
        if text is None:
            text = "Split PDF" if self.current_mode == "split" else "Merge PDFs"

        self.action_button.configure(
            text=text,
            state="normal",
            fg_color=ORANGE
        )

    def show_idle_status(self):
        if self.current_mode == "split":
            if self.selected_pdf:
                text = "PDF selected. Configure settings, then click Split PDF."
            else:
                text = "Select a PDF to start."
        else:
            count = len(self.merge_files)

            if count == 0:
                text = "Add at least two PDFs to start."
            elif count == 1:
                text = "Add at least one more PDF."
            else:
                text = f"{count} PDFs ready. Check the order, then click Merge PDFs."

        self.set_status(text, TEXT_MUTED)

    def set_status(self, text, color=WHITE):
        self.status_label.configure(text=text, text_color=color)

    def start_action(self):
        if self.current_mode == "split":
            self.start_split()
        else:
            self.start_merge()

    # ============================================================
    # SPLIT: PDF FILE SELECTION
    # ============================================================

    def handle_split_drop(self, event):
        files = self.tk.splitlist(event.data)

        if not files:
            return

        pdfs = [f for f in files if f.lower().endswith(".pdf")]

        if len(pdfs) > 1:
            self.set_status(
                "Several PDFs dropped: only the first one is used. "
                "Use the Merge tab to combine files.",
                TEXT_MUTED
            )

        self.set_selected_pdf(pdfs[0] if pdfs else files[0])

    def browse_pdf(self):
        file_path = filedialog.askopenfilename(
            title="Choose a PDF file",
            filetypes=[("PDF files", "*.pdf")]
        )

        if file_path:
            self.set_selected_pdf(file_path)

    def set_selected_pdf(self, file_path):
        if self.is_processing:
            return

        file_path = os.path.normpath(file_path)

        if not file_path.lower().endswith(".pdf"):
            messagebox.showerror("Invalid file", "Please choose a PDF file.")
            return

        if not os.path.isfile(file_path):
            messagebox.showerror(
                "File not found",
                "The selected PDF could not be found."
            )
            return

        self.selected_pdf = file_path

        self.file_name_label.configure(
            text=f"Selected: {os.path.basename(file_path)}",
            text_color=ORANGE
        )

        if not self.split_output_folder:
            self.set_path_display(
                self.split_output_entry,
                self.split_output_var,
                os.path.dirname(file_path)
            )

        self.progress_bar.set(0)
        self.refresh_action_button()
        self.show_idle_status()

    def choose_split_output_folder(self):
        folder = filedialog.askdirectory(
            title="Choose where the output folder will be created"
        )

        if folder:
            self.split_output_folder = os.path.normpath(folder)
            self.set_path_display(
                self.split_output_entry,
                self.split_output_var,
                self.split_output_folder
            )

    # ============================================================
    # SPLIT: SETTINGS
    # ============================================================

    def update_split_mode(self):
        self.split_value_entry.delete(0, "end")

        if self.split_mode.get() == "pages":
            self.value_label.configure(text="Pages per file")
            self.value_description.configure(text="Pages per output file.")
            self.split_value_entry.insert(0, "30")
        else:
            self.value_label.configure(text="Maximum size")
            self.value_description.configure(
                text="Hard maximum size per output PDF."
            )
            self.split_value_entry.insert(0, "5000")

    def get_split_value(self):
        value = self.split_value_entry.get().strip()

        try:
            number = int(value)

            if number <= 0:
                raise ValueError

            return number

        except ValueError:
            if self.split_mode.get() == "pages":
                message = "Pages per file must be a whole number above 0."
            else:
                message = "Maximum size must be a whole number above 0 KB."

            messagebox.showerror("Invalid value", message)
            return None

    @staticmethod
    def validate_name(name, label):
        """
        Returns an error message for an invalid Windows file/folder
        name, or None when the name is valid.
        """

        if not name:
            return f"Please enter a {label.lower()}."

        if re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            return f'{label} cannot contain: < > : " / \\ | ? *'

        if name in {".", ".."}:
            return f"Please choose another {label.lower()}."

        if name.endswith((".", " ")):
            return f"{label} cannot end with a dot or a space."

        if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
            return f'"{name}" is a reserved name on Windows.'

        return None

    def get_folder_name(self):
        folder_name = self.folder_name_entry.get().strip()
        error = self.validate_name(folder_name, "Folder name")

        if error:
            messagebox.showerror("Invalid folder name", error)
            return None

        return folder_name

    # ============================================================
    # QPDF OPERATIONS
    # ============================================================

    def get_page_count(self, pdf_path):
        result = self.run_qpdf_command(
            [self.qpdf_path, "--show-npages", pdf_path]
        )

        if result.returncode not in (0, 3):
            details = result.stderr.strip() or result.stdout.strip()
            raise QPDFError(f"Unable to read this PDF.\n\n{details}")

        matches = re.findall(r"\d+", result.stdout)

        if not matches:
            raise QPDFError("Unable to determine PDF page count.")

        return int(matches[-1])

    def build_pages_command(self, page_specs, output_path, optimize=True):
        """
        page_specs is the list of arguments placed between --pages and --,
        e.g. ["file.pdf", "1-10"] or ["a.pdf", "b.pdf", "c.pdf"].
        """

        command = [self.qpdf_path, "--empty"]

        if optimize:
            command += QPDF_OPTIMIZE_ARGS

        command += ["--pages", *page_specs, "--", str(output_path)]

        return command

    def run_pages_command(self, page_specs, output_path, optimize, error_message):
        result = self.run_qpdf_command(
            self.build_pages_command(page_specs, output_path, optimize)
        )

        # qpdf uses return code 3 for warnings while still writing a PDF.
        if result.returncode not in (0, 3):
            details = result.stderr.strip() or result.stdout.strip()
            raise QPDFError(f"{error_message}\n\n{details}")

        if not os.path.isfile(output_path):
            raise QPDFError("qpdf did not create the expected output PDF.")

    def create_pdf_range(self, pdf_path, start_page, end_page, output_path):
        """
        Creates a PDF containing only the requested page range.

        qpdf does not recompress JPEG images. It optimizes PDF structure,
        object streams, and Flate-compressed streams where possible.
        """

        self.run_pages_command(
            [pdf_path, f"{start_page}-{end_page}"],
            output_path,
            optimize=True,
            error_message="qpdf could not create a split PDF."
        )

    def create_candidate(self, pdf_path, start_page, end_page, temp_folder):
        candidate_path = os.path.join(
            temp_folder,
            f"candidate_{start_page}_{end_page}.pdf"
        )

        self.create_pdf_range(pdf_path, start_page, end_page, candidate_path)

        return candidate_path, os.path.getsize(candidate_path)

    @staticmethod
    def move_file(source_path, destination):
        destination = Path(destination)

        if destination.exists():
            destination.unlink()

        shutil.move(str(source_path), str(destination))

    # ============================================================
    # SPLIT: PROCESSING
    # ============================================================

    def start_split(self):
        if self.is_processing:
            return

        if not self.check_qpdf():
            return

        if not self.selected_pdf:
            messagebox.showwarning(
                "No PDF selected",
                "Please drag a PDF into the app or click Choose a PDF."
            )
            return

        if not os.path.isfile(self.selected_pdf):
            messagebox.showerror(
                "File not found",
                f"The selected PDF no longer exists:\n\n{self.selected_pdf}"
            )
            return

        split_value = self.get_split_value()

        if split_value is None:
            return

        folder_name = self.get_folder_name()

        if folder_name is None:
            return

        if self.split_output_folder:
            output_parent = Path(self.split_output_folder)
        else:
            output_parent = Path(self.selected_pdf).parent

        output_folder = output_parent / folder_name

        if output_folder.exists() and not output_folder.is_dir():
            messagebox.showerror(
                "Invalid folder",
                f"A file with this name already exists:\n\n{output_folder}"
            )
            return

        if output_folder.is_dir() and any(output_folder.iterdir()):
            should_continue = messagebox.askyesno(
                "Folder already exists",
                f"This folder already exists:\n\n"
                f"{output_folder}\n\n"
                "Continue and create output PDFs in this folder?\n"
                "Files with the same name will be replaced."
            )

            if not should_continue:
                return

        self.begin_processing("Splitting...", "Reading PDF...")

        # Read every Tk value here, in the main thread.
        worker = threading.Thread(
            target=self.process_split,
            args=(
                self.selected_pdf,
                self.split_mode.get(),
                split_value,
                output_folder
            ),
            daemon=True
        )
        worker.start()

    def process_split(self, pdf_path, mode, split_value, output_folder):
        try:
            total_pages = self.get_page_count(pdf_path)

            if total_pages <= 0:
                raise QPDFError("The selected PDF does not contain any pages.")

            output_folder.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory() as temp_folder:
                if mode == "pages":
                    parts_created = self.split_by_pages(
                        pdf_path, total_pages, split_value,
                        output_folder, temp_folder
                    )
                else:
                    parts_created = self.split_by_max_size(
                        pdf_path, total_pages, split_value,
                        output_folder, temp_folder
                    )

            self.ui(self.show_split_success, output_folder, parts_created)

        except RequestedSizeImpossibleError as error:
            self.ui(self.show_error, "Requested size cannot be reached", str(error))

        except Exception as error:
            # The message is converted to text NOW: Python deletes the
            # 'error' variable at the end of the except block.
            self.ui(
                self.show_error,
                "Processing error",
                f"Unable to split this PDF.\n\n{error}"
            )

    def split_by_pages(self, pdf_path, total_pages, pages_per_file,
                       output_folder, temp_folder):
        total_parts = (total_pages + pages_per_file - 1) // pages_per_file
        part_number = 0

        for start_page in range(1, total_pages + 1, pages_per_file):
            end_page = min(start_page + pages_per_file - 1, total_pages)
            part_number += 1

            self.post_status(f"Creating pages {start_page} to {end_page}...")

            temporary_file = os.path.join(temp_folder, f"part_{part_number}.pdf")

            self.create_pdf_range(pdf_path, start_page, end_page, temporary_file)

            self.move_file(
                temporary_file,
                output_folder / self.part_filename(part_number, start_page, end_page)
            )

            self.post_progress(
                part_number / total_parts,
                f"Created file {part_number} of {total_parts}."
            )

        return part_number

    def find_largest_fitting_range(self, pdf_path, start_page, remaining_pages,
                                   maximum_bytes, temp_folder):
        """
        Finds the biggest page range starting at start_page whose output
        stays below maximum_bytes.

        Returns (page_count, file_path, one_page_size).
        """

        best_count = 0
        best_path = None
        one_page_size = None

        def try_count(count):
            nonlocal best_count, best_path, one_page_size

            end_page = start_page + count - 1
            self.post_status(f"Checking pages {start_page} to {end_page}...")

            path, size = self.create_candidate(
                pdf_path, start_page, end_page, temp_folder
            )

            if count == 1:
                one_page_size = size

            if size <= maximum_bytes:
                if best_path and os.path.isfile(best_path):
                    os.remove(best_path)

                best_count, best_path = count, path
                return True

            if os.path.isfile(path):
                os.remove(path)

            return False

        # Fast path: everything that is left fits in one file.
        if try_count(remaining_pages):
            return best_count, best_path, one_page_size

        # Binary search between 1 and remaining_pages - 1.
        low, high = 1, remaining_pages - 1

        while low <= high:
            middle = (low + high) // 2

            if try_count(middle):
                low = middle + 1
            else:
                high = middle - 1

        return best_count, best_path, one_page_size

    def split_by_max_size(self, pdf_path, total_pages, max_size_kb,
                          output_folder, temp_folder):
        maximum_bytes = max_size_kb * 1024
        current_page = 1
        part_number = 0

        while current_page <= total_pages:
            remaining_pages = total_pages - current_page + 1

            best_count, best_path, one_page_size = self.find_largest_fitting_range(
                pdf_path, current_page, remaining_pages,
                maximum_bytes, temp_folder
            )

            if best_count == 0:
                size_text = (
                    f"{one_page_size / 1024:.0f} KB"
                    if one_page_size is not None else "unknown"
                )

                raise RequestedSizeImpossibleError(
                    f"Page {current_page} cannot fit below {max_size_kb} KB.\n\n"
                    f"Optimized one-page size: {size_text}.\n\n"
                    "qpdf preserves embedded image quality. "
                    "Use a larger maximum size."
                )

            part_number += 1
            end_page = current_page + best_count - 1

            self.move_file(
                best_path,
                output_folder / self.part_filename(part_number, current_page, end_page)
            )

            current_page = end_page + 1
            progress = end_page / total_pages

            self.post_progress(
                progress,
                f"Created file {part_number}. {int(progress * 100)}% complete."
            )

        return part_number

    @staticmethod
    def part_filename(part_number, start_page, end_page):
        return f"part_{part_number}_pages_{start_page}-{end_page}.pdf"

    # ============================================================
    # MERGE: FILE LIST
    # ============================================================

    def handle_merge_drop(self, event):
        self.add_merge_files(self.tk.splitlist(event.data))

    def browse_merge_pdfs(self):
        file_paths = filedialog.askopenfilenames(
            title="Choose PDF files to merge",
            filetypes=[("PDF files", "*.pdf")]
        )

        if file_paths:
            self.add_merge_files(file_paths)

    def add_merge_files(self, paths):
        if self.is_processing:
            return

        existing = {os.path.normcase(p) for p in self.merge_files}
        added = 0
        skipped = 0

        candidates = []

        for path in paths:
            path = os.path.normpath(path)

            if os.path.isdir(path):
                # A dropped folder adds the PDFs it contains, in natural order.
                try:
                    folder_pdfs = [
                        os.path.join(path, name)
                        for name in os.listdir(path)
                        if name.lower().endswith(".pdf")
                    ]
                except OSError:
                    folder_pdfs = []

                candidates.extend(sorted(folder_pdfs, key=natural_sort_key))
            else:
                candidates.append(path)

        for path in candidates:
            key = os.path.normcase(path)

            if (
                not path.lower().endswith(".pdf")
                or not os.path.isfile(path)
                or key in existing
            ):
                skipped += 1
                continue

            self.merge_files.append(path)
            existing.add(key)
            added += 1

        self.refresh_merge_list()
        self.progress_bar.set(0)
        self.refresh_action_button()

        if added == 0 and skipped:
            self.set_status(
                "No new PDF added (not a PDF, missing, or already in the list).",
                ERROR
            )
        elif skipped:
            self.set_status(
                f"Added {added} PDF(s). Skipped {skipped} item(s) "
                "(not a PDF or already in the list).",
                TEXT_MUTED
            )
        else:
            self.show_idle_status()

    def refresh_merge_list(self, select=None):
        self.merge_listbox.delete(0, "end")

        for index, path in enumerate(self.merge_files, start=1):
            self.merge_listbox.insert("end", f"  {index}.   {os.path.basename(path)}")

        if select:
            for index in select:
                self.merge_listbox.selection_set(index)

            self.merge_listbox.see(select[0])

        if self.merge_files:
            self.merge_empty_label.place_forget()

            total_size = 0

            for path in self.merge_files:
                try:
                    total_size += os.path.getsize(path)
                except OSError:
                    pass

            self.merge_summary_label.configure(
                text=f"{len(self.merge_files)} PDF(s) · {format_size(total_size)}"
            )
        else:
            self.merge_empty_label.place(relx=0.5, rely=0.5, anchor="center")
            self.merge_summary_label.configure(text="No files added")

        if not self.merge_output_folder:
            if self.merge_files:
                location = os.path.dirname(self.merge_files[0])
            else:
                location = "Same location as first PDF"

            self.set_path_display(
                self.merge_output_entry,
                self.merge_output_var,
                location
            )

    def get_merge_selection(self):
        return sorted(int(i) for i in self.merge_listbox.curselection())

    def move_merge_selection(self, direction):
        if self.is_processing:
            return "break"

        selection = self.get_merge_selection()

        if not selection:
            return "break"

        if direction < 0 and selection[0] == 0:
            return "break"

        if direction > 0 and selection[-1] == len(self.merge_files) - 1:
            return "break"

        order = selection if direction < 0 else reversed(selection)

        for index in order:
            target = index + direction
            self.merge_files[index], self.merge_files[target] = (
                self.merge_files[target],
                self.merge_files[index]
            )

        self.refresh_merge_list(select=[i + direction for i in selection])

        # "break" stops Tk's default Up/Down handling for key bindings.
        return "break"

    def remove_merge_selection(self):
        if self.is_processing:
            return

        selection = self.get_merge_selection()

        if not selection:
            return

        for index in reversed(selection):
            del self.merge_files[index]

        next_index = min(selection[0], len(self.merge_files) - 1)
        self.refresh_merge_list(select=[next_index] if next_index >= 0 else None)
        self.show_idle_status()

    def clear_merge_files(self):
        if self.is_processing or not self.merge_files:
            return

        self.merge_files.clear()
        self.refresh_merge_list()
        self.progress_bar.set(0)
        self.show_idle_status()

    def choose_merge_output_folder(self):
        folder = filedialog.askdirectory(
            title="Choose where the merged PDF will be saved"
        )

        if folder:
            self.merge_output_folder = os.path.normpath(folder)
            self.set_path_display(
                self.merge_output_entry,
                self.merge_output_var,
                self.merge_output_folder
            )

    def get_merge_file_name(self):
        name = self.merge_name_entry.get().strip()

        if name and not name.lower().endswith(".pdf"):
            name += ".pdf"

        error = self.validate_name(name, "File name")

        if not error and name.lower() == ".pdf":
            error = "Please enter a file name."

        if error:
            messagebox.showerror("Invalid file name", error)
            return None

        return name

    # ============================================================
    # MERGE: PROCESSING
    # ============================================================

    def start_merge(self):
        if self.is_processing:
            return

        if not self.check_qpdf():
            return

        if len(self.merge_files) < 2:
            messagebox.showwarning(
                "Not enough files",
                "Please add at least two PDF files to merge."
            )
            return

        missing = [p for p in self.merge_files if not os.path.isfile(p)]

        if missing:
            messagebox.showerror(
                "File not found",
                "These files no longer exist:\n\n"
                + "\n".join(os.path.basename(p) for p in missing[:10])
            )
            return

        file_name = self.get_merge_file_name()

        if file_name is None:
            return

        if self.merge_output_folder:
            output_folder = Path(self.merge_output_folder)
        else:
            output_folder = Path(self.merge_files[0]).parent

        output_path = output_folder / file_name

        output_key = os.path.normcase(os.path.abspath(output_path))
        input_keys = {
            os.path.normcase(os.path.abspath(p)) for p in self.merge_files
        }

        if output_key in input_keys:
            messagebox.showerror(
                "Invalid file name",
                "The merged PDF cannot replace one of the files being merged.\n\n"
                "Please choose another file name or location."
            )
            return

        if output_path.exists():
            should_replace = messagebox.askyesno(
                "File already exists",
                f"This file already exists:\n\n{output_path}\n\nReplace it?"
            )

            if not should_replace:
                return

        self.begin_processing("Merging...", "Reading PDFs...")

        worker = threading.Thread(
            target=self.process_merge,
            args=(
                list(self.merge_files),
                output_path,
                self.merge_optimize_var.get()
            ),
            daemon=True
        )
        worker.start()

    def process_merge(self, files, output_path, optimize):
        try:
            total_files = len(files)
            total_pages = 0

            # 1. Check every file first, so errors name the faulty PDF.
            for index, path in enumerate(files, start=1):
                name = os.path.basename(path)
                self.post_status(f"Reading {name} ({index} of {total_files})...")

                try:
                    total_pages += self.get_page_count(path)
                except QPDFError as error:
                    raise QPDFError(f"Problem with: {name}\n\n{error}") from error

                self.post_progress(0.3 * index / total_files)

            # 2. Merge.
            with tempfile.TemporaryDirectory() as temp_folder:
                temp_output = os.path.join(temp_folder, "merged.pdf")

                self.merge_pdfs(files, temp_output, temp_folder, optimize)

                output_path.parent.mkdir(parents=True, exist_ok=True)
                self.move_file(temp_output, output_path)

            self.ui(self.show_merge_success, output_path, total_files, total_pages)

        except Exception as error:
            self.ui(
                self.show_error,
                "Processing error",
                f"Unable to merge these PDFs.\n\n{error}"
            )

    @staticmethod
    def make_merge_batches(files):
        """
        Splits the file list so that each qpdf command line stays under
        the Windows command-line length limit.
        """

        batches = []
        current = []
        current_length = 0

        for path in files:
            length = len(path) + 3

            if current and current_length + length > MAX_COMMAND_LENGTH:
                batches.append(current)
                current = []
                current_length = 0

            current.append(path)
            current_length += length

        if current:
            batches.append(current)

        return batches

    def merge_pdfs(self, files, output_path, temp_folder, optimize):
        batches = self.make_merge_batches(files)
        previous_result = None

        for index, batch in enumerate(batches, start=1):
            is_last = index == len(batches)

            if len(batches) == 1:
                self.post_status(f"Merging {len(files)} PDFs...")
            else:
                self.post_status(f"Merging part {index} of {len(batches)}...")

            inputs = ([previous_result] if previous_result else []) + batch

            target = output_path if is_last else os.path.join(
                temp_folder, f"merge_step_{index}.pdf"
            )

            self.run_pages_command(
                inputs,
                target,
                optimize=optimize,
                error_message="qpdf could not merge the PDFs."
            )

            if previous_result and os.path.isfile(previous_result):
                os.remove(previous_result)

            previous_result = target

            self.post_progress(0.3 + 0.7 * index / len(batches))

    # ============================================================
    # SHARED PROCESSING HELPERS
    # ============================================================

    def check_qpdf(self):
        if self.qpdf_path and os.path.isfile(self.qpdf_path):
            return True

        messagebox.showerror(
            "qpdf not found",
            "qpdf could not be found.\n\n"
            "Install qpdf (for example: winget install qpdf), "
            "or place qpdf.exe and its DLL files in a 'qpdf_bin' folder "
            "next to this program, then restart the app."
        )
        return False

    def begin_processing(self, button_text, status_text):
        self.is_processing = True

        self.action_button.configure(
            text=button_text,
            state="disabled",
            fg_color=DISABLED_BUTTON
        )
        self.mode_switch.configure(state="disabled")

        self.progress_bar.set(0)
        self.set_status(status_text, WHITE)

    def end_processing(self, button_text=None):
        self.is_processing = False
        self.mode_switch.configure(state="normal")
        self.refresh_action_button(button_text)

    def post_status(self, message):
        """Thread-safe status update."""
        self.ui(self.set_status, message, WHITE)

    def post_progress(self, progress, message=None):
        """Thread-safe progress update."""
        self.ui(self.update_progress, progress, message)

    def update_progress(self, progress, message=None):
        self.progress_bar.set(max(0.0, min(1.0, progress)))

        if message:
            self.set_status(message, WHITE)

    # ============================================================
    # RESULTS
    # ============================================================

    def show_split_success(self, output_folder, parts_created):
        self.end_processing("Split another PDF")
        self.progress_bar.set(1)

        self.set_status(
            f"Completed: {parts_created} PDF file(s) created.",
            SUCCESS
        )

        should_open = messagebox.askyesno(
            "Split complete",
            f"{parts_created} PDF file(s) were created.\n\n"
            f"Output folder:\n{output_folder}\n\n"
            "Open the output folder now?"
        )

        if should_open:
            self.open_folder(output_folder)

    def show_merge_success(self, output_path, file_count, total_pages):
        self.end_processing("Merge again")
        self.progress_bar.set(1)

        try:
            size_text = format_size(os.path.getsize(output_path))
        except OSError:
            size_text = "unknown size"

        self.set_status(
            f"Completed: {file_count} PDFs merged into {output_path.name} "
            f"({total_pages} pages, {size_text}).",
            SUCCESS
        )

        should_open = messagebox.askyesno(
            "Merge complete",
            f"{file_count} PDFs were merged ({total_pages} pages, {size_text}).\n\n"
            f"Output file:\n{output_path}\n\n"
            "Open the output folder now?"
        )

        if should_open:
            self.open_folder(output_path.parent, select_file=output_path)

    def show_error(self, title, message):
        self.end_processing()
        self.set_status("An error occurred.", ERROR)
        messagebox.showerror(title, message)

    @staticmethod
    def open_folder(folder, select_file=None):
        folder = str(folder)

        try:
            if sys.platform.startswith("win"):
                if select_file:
                    # Opens Explorer with the merged file highlighted.
                    subprocess.Popen(["explorer", "/select,", str(select_file)])
                else:
                    os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except OSError as error:
            messagebox.showerror("Unable to open folder", str(error))


if __name__ == "__main__":
    app = PDFToolsApp()
    app.mainloop()
