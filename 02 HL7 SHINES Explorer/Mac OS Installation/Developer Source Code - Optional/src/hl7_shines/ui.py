from __future__ import annotations

import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from .analytics import HL7Analytics
from .assistant import comparison_summary, message_summary
from .catalog import CODE_SUGGESTIONS, component_name, field_name, segment_name
from .mllp import MLLPListener, send_message
from .models import HL7Message, parse_path
from .parser import HL7ParseError, HL7Parser
from .samples import SampleMessage, practice_library
from .validator import HL7Validator
from .version import __version__
from .workspace import Workspace


APP_NAME = "HL7 Shines"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def user_document_dir() -> Path:
    return Path.home() / "Documents"


class ScrollableFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _on_mousewheel(self, event):
        if self.winfo_containing(event.x_root, event.y_root) and self._contains(self.winfo_containing(event.x_root, event.y_root)):
            delta = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(delta * 3, "units")

    def _contains(self, widget) -> bool:
        while widget:
            if widget == self:
                return True
            widget = widget.master
        return False


class SampleLibraryDialog(tk.Toplevel):
    def __init__(self, master: "HL7ShinesApp", on_open: Callable[[SampleMessage], None]):
        super().__init__(master)
        self.title("HL7 Shines Practice Library")
        self.geometry("980x680")
        self.minsize(760, 500)
        self.transient(master)
        self.on_open = on_open
        self.samples = practice_library()
        self.filtered = list(self.samples)

        header = ttk.Frame(self, padding=14)
        header.pack(fill="x")
        ttk.Label(header, text="Practice Library", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="347 synthetic, training-only examples. Never use them as clinical records.", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(header, textvariable=self.search_var)
        entry.pack(fill="x")
        entry.bind("<KeyRelease>", lambda _e: self.refresh())

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        left = ttk.Frame(body)
        right = ttk.Frame(body, padding=(12, 0, 0, 0))
        body.add(left, weight=2)
        body.add(right, weight=3)

        self.tree = ttk.Treeview(left, columns=("type", "category"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Sample")
        self.tree.heading("type", text="Type")
        self.tree.heading("category", text="Category")
        self.tree.column("#0", width=360)
        self.tree.column("type", width=100)
        self.tree.column("category", width=170)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_selected())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())

        self.preview = tk.Text(right, wrap="none", font=("Menlo" if platform.system() == "Darwin" else "Consolas", 10), undo=False)
        y = ttk.Scrollbar(right, orient="vertical", command=self.preview.yview)
        x = ttk.Scrollbar(right, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self, padding=(14, 0, 14, 14))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Open in New Workspace", style="Accent.TButton", command=self.open_selected).pack(side="right", padx=(0, 8))
        self.refresh()
        self.grab_set()

    def refresh(self):
        term = self.search_var.get().strip().casefold()
        self.filtered = [sample for sample in self.samples if not term or term in f"{sample.title} {sample.category} {sample.message_type} {sample.description}".casefold()]
        self.tree.delete(*self.tree.get_children())
        for index, sample in enumerate(self.filtered):
            prefix = "★ " if sample.featured else ""
            self.tree.insert("", "end", iid=str(index), text=prefix + sample.title, values=(sample.message_type, sample.category))
        if self.filtered:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self.show_selected()
        else:
            self.preview.delete("1.0", "end")

    def selected_sample(self) -> SampleMessage | None:
        selection = self.tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        return self.filtered[index] if index < len(self.filtered) else None

    def show_selected(self):
        sample = self.selected_sample()
        self.preview.delete("1.0", "end")
        if sample:
            self.preview.insert("1.0", sample.raw.replace("\r", "\n"))

    def open_selected(self):
        sample = self.selected_sample()
        if sample:
            self.on_open(sample)
            self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: "HL7ShinesApp"):
        super().__init__(master)
        self.title("HL7 Shines Settings")
        self.geometry("440x280")
        self.resizable(False, False)
        self.transient(master)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Appearance", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="Theme").grid(row=1, column=0, sticky="w", pady=8)
        theme = ttk.Combobox(frame, textvariable=master.theme_var, state="readonly", values=("Light", "Blue", "Dark", "Soft Green", "Warm"), width=20)
        theme.grid(row=1, column=1, sticky="ew", pady=8)
        theme.bind("<<ComboboxSelected>>", lambda _e: master.apply_theme())
        ttk.Label(frame, text="Interface scale").grid(row=2, column=0, sticky="w", pady=8)
        scale = ttk.Scale(frame, from_=0.8, to=1.6, variable=master.scale_var, command=lambda _v: master.apply_scale())
        scale.grid(row=2, column=1, sticky="ew", pady=8)
        self.scale_label = ttk.Label(frame, text=f"{int(master.scale_var.get() * 100)}%")
        self.scale_label.grid(row=3, column=1, sticky="e")
        scale.configure(command=lambda _v: (master.apply_scale(), self.scale_label.configure(text=f"{int(master.scale_var.get() * 100)}%")))
        ttk.Separator(frame).grid(row=4, column=0, columnspan=2, sticky="ew", pady=16)
        ttk.Label(frame, text="Settings apply immediately and are saved locally.", style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Button(frame, text="Done", command=self.destroy).grid(row=6, column=1, sticky="e", pady=(16, 0))
        frame.columnconfigure(1, weight=1)
        self.grab_set()


class HL7ShinesApp(tk.Tk):
    def __init__(self, initial_files: list[str] | None = None):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1440x900")
        self.minsize(1080, 700)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.base_font_size = 10
        self.theme_var = tk.StringVar(value="Blue")
        self.scale_var = tk.DoubleVar(value=1.0)
        self.workspace_filter_var = tk.StringVar()
        self.message_filter_var = tk.StringVar()
        self.field_search_var = tk.StringVar()
        self.compare_target_var = tk.StringVar()
        self.include_unchanged_var = tk.BooleanVar(value=False)
        self.transmit_host_var = tk.StringVar(value="127.0.0.1")
        self.transmit_port_var = tk.StringVar(value="2575")
        self.transmit_tls_var = tk.BooleanVar(value=False)
        self.transmit_timeout_var = tk.StringVar(value="10")
        self.listener_host_var = tk.StringVar(value="127.0.0.1")
        self.listener_port_var = tk.StringVar(value="2575")

        self.workspaces: list[Workspace] = []
        self.closed_workspaces: list[Workspace] = []
        self.active_workspace_id: str | None = None
        self.current_view = "Inspect"
        self.listener: MLLPListener | None = None
        self._listener_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._field_path = ""
        self._icon_image: tk.PhotoImage | None = None
        self._theme_colors = {}

        self.load_preferences()
        self.configure_styles()
        self.set_icon()
        self.build_menu()
        self.build_ui()
        self.bind_shortcuts()

        self.add_workspace_from_raw(practice_library(4)[0].raw, "Starter Messages", append_messages=[sample.raw for sample in practice_library(4)[1:]])
        for file_path in initial_files or []:
            self.open_path(file_path)
        self.after(200, self.process_listener_queue)

    # ---------- Preferences and theme ----------
    @property
    def preferences_path(self) -> Path:
        if platform.system() == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home()))
        elif platform.system() == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path.home() / ".config"
        return base / "HL7 Shines" / "preferences.txt"

    def load_preferences(self):
        try:
            values = {}
            for line in self.preferences_path.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value
            if values.get("theme") in {"Light", "Blue", "Dark", "Soft Green", "Warm"}:
                self.theme_var.set(values["theme"])
            if values.get("scale"):
                self.scale_var.set(min(1.6, max(0.8, float(values["scale"]))))
        except Exception:
            pass

    def save_preferences(self):
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            self.preferences_path.write_text(f"theme={self.theme_var.get()}\nscale={self.scale_var.get():.2f}\n", encoding="utf-8")
        except Exception:
            pass

    def configure_styles(self):
        self.style = ttk.Style(self)
        available = self.style.theme_names()
        self.style.theme_use("clam" if "clam" in available else available[0])
        self.apply_theme()
        self.apply_scale()

    def apply_theme(self):
        themes = {
            "Light": {"bg": "#f5f7fb", "panel": "#ffffff", "sidebar": "#eef1f6", "text": "#14213d", "muted": "#667085", "accent": "#2563eb", "accent2": "#dbeafe", "line": "#d0d5dd", "field": "#ffffff", "select": "#dbeafe"},
            "Blue": {"bg": "#edf5ff", "panel": "#ffffff", "sidebar": "#e7ecf4", "text": "#102a43", "muted": "#62748a", "accent": "#1268d6", "accent2": "#d9ebff", "line": "#cbd8e8", "field": "#ffffff", "select": "#cfe4ff"},
            "Dark": {"bg": "#111827", "panel": "#1f2937", "sidebar": "#18212f", "text": "#f3f4f6", "muted": "#aab4c4", "accent": "#38bdf8", "accent2": "#123750", "line": "#3c4657", "field": "#111827", "select": "#164e63"},
            "Soft Green": {"bg": "#eef8f3", "panel": "#ffffff", "sidebar": "#e5f2eb", "text": "#17352a", "muted": "#607a6f", "accent": "#16855b", "accent2": "#d8f3e7", "line": "#c7ddd2", "field": "#ffffff", "select": "#d7f2e5"},
            "Warm": {"bg": "#fbf6ee", "panel": "#fffdf9", "sidebar": "#f2eadf", "text": "#3b2f2f", "muted": "#7a6a60", "accent": "#b45309", "accent2": "#fce7c7", "line": "#ded1c2", "field": "#fffdf9", "select": "#f8dfbd"},
        }
        c = themes.get(self.theme_var.get(), themes["Blue"])
        self._theme_colors = c
        self.configure(bg=c["bg"])
        self.style.configure(".", background=c["bg"], foreground=c["text"], fieldbackground=c["field"], bordercolor=c["line"], lightcolor=c["line"], darkcolor=c["line"])
        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("Panel.TFrame", background=c["panel"])
        self.style.configure("Sidebar.TFrame", background=c["sidebar"])
        self.style.configure("TLabel", background=c["bg"], foreground=c["text"])
        self.style.configure("Panel.TLabel", background=c["panel"], foreground=c["text"])
        self.style.configure("Sidebar.TLabel", background=c["sidebar"], foreground=c["text"])
        self.style.configure("Muted.TLabel", foreground=c["muted"])
        self.style.configure("Title.TLabel", font=("TkDefaultFont", max(14, int(17 * self.scale_var.get())), "bold"))
        self.style.configure("Header.TLabel", font=("TkDefaultFont", max(12, int(14 * self.scale_var.get())), "bold"))
        self.style.configure("Accent.TButton", background=c["accent"], foreground="#ffffff", borderwidth=0, padding=(12, 7))
        self.style.map("Accent.TButton", background=[("active", c["accent"]), ("pressed", c["accent"])], foreground=[("disabled", "#dddddd")])
        self.style.configure("Nav.TButton", anchor="w", padding=(12, 9), background=c["sidebar"], foreground=c["text"], borderwidth=0)
        self.style.map("Nav.TButton", background=[("active", c["accent2"]), ("pressed", c["accent2"])])
        self.style.configure("Selected.Nav.TButton", anchor="w", padding=(12, 9), background=c["accent2"], foreground=c["accent"], borderwidth=0)
        self.style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"], rowheight=max(25, int(28 * self.scale_var.get())))
        self.style.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["text"])])
        self.style.configure("Treeview.Heading", background=c["sidebar"], foreground=c["text"], relief="flat")
        self.style.configure("TNotebook", background=c["bg"], borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(12, 7), background=c["sidebar"], foreground=c["text"])
        self.style.map("TNotebook.Tab", background=[("selected", c["accent2"])], foreground=[("selected", c["accent"])])
        self.style.configure("TLabelframe", background=c["panel"], foreground=c["text"])
        self.style.configure("TLabelframe.Label", background=c["panel"], foreground=c["text"], font=("TkDefaultFont", 10, "bold"))
        self.option_add("*Text.background", c["field"])
        self.option_add("*Text.foreground", c["text"])
        self.option_add("*Text.insertBackground", c["text"])
        self.option_add("*Listbox.background", c["panel"])
        self.option_add("*Listbox.foreground", c["text"])
        self.refresh_text_colors()
        self.save_preferences()

    def refresh_text_colors(self):
        if not hasattr(self, "winfo_children"):
            return
        c = self._theme_colors
        for widget in self._walk_widgets(self):
            if isinstance(widget, (tk.Text, tk.Listbox, tk.Canvas)):
                try:
                    widget.configure(bg=c["field"] if not isinstance(widget, tk.Canvas) else c["panel"], fg=c["text"], insertbackground=c["text"])
                except tk.TclError:
                    pass

    def apply_scale(self):
        scale = self.scale_var.get()
        try:
            self.tk.call("tk", "scaling", 1.333333 * scale)
        except tk.TclError:
            pass
        self.style.configure("Title.TLabel", font=("TkDefaultFont", max(14, int(17 * scale)), "bold"))
        self.style.configure("Header.TLabel", font=("TkDefaultFont", max(12, int(14 * scale)), "bold"))
        self.style.configure("Treeview", rowheight=max(25, int(28 * scale)))
        self.save_preferences()

    def _walk_widgets(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._walk_widgets(child)

    def set_icon(self):
        try:
            png = resource_path("resources/HL7ShinesIcon-1024.png")
            if png.exists():
                image = tk.PhotoImage(file=str(png))
                self._icon_image = image.subsample(16, 16)
                self.iconphoto(True, image)
            if platform.system() == "Windows":
                ico = resource_path("resources/AppIcon.ico")
                if ico.exists():
                    self.iconbitmap(str(ico))
        except Exception:
            pass

    # ---------- Menus and layout ----------
    def build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Blank Workspace", accelerator=self.accel("N"), command=self.new_blank_workspace)
        file_menu.add_command(label="New Workspace Tab", accelerator=self.accel("T"), command=self.new_blank_workspace)
        file_menu.add_command(label="Open HL7 File(s)…", accelerator=self.accel("O"), command=self.open_files)
        file_menu.add_command(label="Paste into New Workspace", accelerator=self.accel("Shift+V"), command=self.paste_message)
        file_menu.add_separator()
        file_menu.add_command(label="Save Selected Message…", accelerator=self.accel("S"), command=self.export_selected)
        file_menu.add_command(label="Export Workspace…", command=self.export_workspace)
        file_menu.add_separator()
        file_menu.add_command(label="Close Workspace", accelerator=self.accel("W"), command=self.close_workspace)
        file_menu.add_command(label="Reopen Last Closed", accelerator=self.accel("Shift+T"), command=self.reopen_workspace)
        if platform.system() != "Darwin":
            file_menu.add_separator()
            file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator=self.accel("Z"), command=lambda: self.focus_event("<<Undo>>"))
        edit_menu.add_command(label="Redo", accelerator=self.accel("Shift+Z"), command=lambda: self.focus_event("<<Redo>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", accelerator=self.accel("X"), command=lambda: self.focus_event("<<Cut>>"))
        edit_menu.add_command(label="Copy", accelerator=self.accel("C"), command=self.copy_focused_or_message)
        edit_menu.add_command(label="Paste", accelerator=self.accel("V"), command=self.paste_focused_or_workspace)
        edit_menu.add_command(label="Select All", accelerator=self.accel("A"), command=lambda: self.focus_event("<<SelectAll>>"))
        menubar.add_cascade(label="Edit", menu=edit_menu)

        workspace_menu = tk.Menu(menubar, tearoff=False)
        workspace_menu.add_command(label="Duplicate Workspace", command=self.duplicate_workspace)
        workspace_menu.add_command(label="Move Workspace Up", command=lambda: self.move_workspace(-1))
        workspace_menu.add_command(label="Move Workspace Down", command=lambda: self.move_workspace(1))
        workspace_menu.add_separator()
        workspace_menu.add_command(label="Previous Workspace", command=lambda: self.select_relative_workspace(-1))
        workspace_menu.add_command(label="Next Workspace", command=lambda: self.select_relative_workspace(1))
        menubar.add_cascade(label="Workspace", menu=workspace_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        for name in ("Inspect", "Analyze", "Compare", "Assistant", "Integrations", "Transmit"):
            view_menu.add_command(label=name, command=lambda n=name: self.show_view(n))
        view_menu.add_separator()
        view_menu.add_command(label="Zoom In", accelerator=self.accel("+"), command=lambda: self.change_scale(0.1))
        view_menu.add_command(label="Zoom Out", accelerator=self.accel("-"), command=lambda: self.change_scale(-0.1))
        view_menu.add_command(label="Actual Size", accelerator=self.accel("0"), command=lambda: self.set_scale(1.0))
        view_menu.add_separator()
        view_menu.add_command(label="Settings…", command=lambda: SettingsDialog(self))
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Help & Documentation", command=self.show_help)
        help_menu.add_command(label="About HL7 Shines", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def accel(self, key: str) -> str:
        return ("⌘" if platform.system() == "Darwin" else "Ctrl+") + key

    def build_ui(self):
        self.main_pane = ttk.Panedwindow(self, orient="horizontal")
        self.main_pane.pack(fill="both", expand=True)
        self.sidebar = ttk.Frame(self.main_pane, style="Sidebar.TFrame", width=250, padding=14)
        self.main_area = ttk.Frame(self.main_pane, style="Panel.TFrame")
        self.main_pane.add(self.sidebar, weight=0)
        self.main_pane.add(self.main_area, weight=1)
        self.build_sidebar()
        self.build_main_area()
        self.apply_theme()

    def build_sidebar(self):
        header = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        header.pack(fill="x", pady=(0, 16))
        if self._icon_image:
            ttk.Label(header, image=self._icon_image, style="Sidebar.TLabel").pack(side="left", padx=(0, 10))
        titlebox = ttk.Frame(header, style="Sidebar.TFrame")
        titlebox.pack(side="left", fill="x", expand=True)
        ttk.Label(titlebox, text=APP_NAME, style="Sidebar.TLabel", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(titlebox, text=f"Version {__version__} · macOS & Windows", style="Sidebar.TLabel").pack(anchor="w")

        ttk.Label(self.sidebar, text="WORKSPACE TABS", style="Sidebar.TLabel", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(0, 5))
        toolbar = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        toolbar.pack(fill="x", pady=(0, 5))
        ttk.Button(toolbar, text="＋", width=3, command=self.new_blank_workspace).pack(side="left")
        ttk.Button(toolbar, text="↑", width=3, command=lambda: self.move_workspace(-1)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↓", width=3, command=lambda: self.move_workspace(1)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="⧉", width=3, command=self.duplicate_workspace).pack(side="left", padx=2)
        ttk.Button(toolbar, text="×", width=3, command=self.close_workspace).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↶", width=3, command=self.reopen_workspace).pack(side="left", padx=2)

        workspace_filter = ttk.Entry(self.sidebar, textvariable=self.workspace_filter_var)
        workspace_filter.pack(fill="x", pady=(0, 6))
        workspace_filter.insert(0, "")
        workspace_filter.bind("<KeyRelease>", lambda _e: self.refresh_workspace_tree())
        self.workspace_tree = ttk.Treeview(self.sidebar, columns=("count",), show="tree headings", height=9, selectmode="browse")
        self.workspace_tree.heading("#0", text="Workspace")
        self.workspace_tree.heading("count", text="Items")
        self.workspace_tree.column("#0", width=150, stretch=True)
        self.workspace_tree.column("count", width=50, anchor="center", stretch=False)
        self.workspace_tree.pack(fill="x", pady=(0, 16))
        self.workspace_tree.bind("<<TreeviewSelect>>", self.on_workspace_tree_select)

        ttk.Separator(self.sidebar).pack(fill="x", pady=(0, 12))
        ttk.Label(self.sidebar, text="WORKSPACE", style="Sidebar.TLabel", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self.nav_buttons: dict[str, ttk.Button] = {}
        for label, symbol in (("Inspect", "▣"), ("Analyze", "▥"), ("Compare", "◫"), ("Assistant", "✦"), ("Integrations", "↻"), ("Transmit", "⌁")):
            button = ttk.Button(self.sidebar, text=f"{symbol}  {label}", style="Nav.TButton", command=lambda n=label: self.show_view(n))
            button.pack(fill="x", pady=1)
            self.nav_buttons[label] = button

        ttk.Separator(self.sidebar).pack(fill="x", pady=12)
        ttk.Label(self.sidebar, text="GET STARTED", style="Sidebar.TLabel", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(0, 4))
        for text, command in (
            ("Open file", self.open_files), ("Paste message", self.paste_message), ("Sample library", self.show_sample_library),
            ("Export workspace", self.export_workspace), ("Help & Documentation", self.show_help), ("About HL7 Shines", self.show_about),
        ):
            ttk.Button(self.sidebar, text=text, style="Nav.TButton", command=command).pack(fill="x", pady=1)
        ttk.Button(self.sidebar, text="Theme", style="Nav.TButton", command=lambda: SettingsDialog(self)).pack(fill="x", pady=(8, 1))
        ttk.Button(self.sidebar, text="Interface size", style="Nav.TButton", command=lambda: SettingsDialog(self)).pack(fill="x", pady=1)

    def build_main_area(self):
        self.header_frame = ttk.Frame(self.main_area, style="Panel.TFrame", padding=(18, 14))
        self.header_frame.pack(fill="x")
        top = ttk.Frame(self.header_frame, style="Panel.TFrame")
        top.pack(fill="x")
        self.header_title = ttk.Label(top, text="No message selected", style="Header.TLabel")
        self.header_title.pack(side="left")
        ttk.Button(top, text="Copy metadata", command=self.copy_metadata).pack(side="right")
        ttk.Button(top, text="Copy HL7", command=self.copy_selected_message).pack(side="right", padx=(0, 8))
        self.metadata_frame = ttk.Frame(self.header_frame, style="Panel.TFrame")
        self.metadata_frame.pack(fill="x", pady=(10, 0))
        self.metadata_labels: dict[str, ttk.Label] = {}
        metadata_keys = ["Patient Name", "MRN", "Visit", "Location", "Message Date", "Control ID", "Sending Application", "Receiving Application", "Version ID", "Segments", "Size"]
        for index, key in enumerate(metadata_keys):
            box = ttk.Frame(self.metadata_frame, style="Sidebar.TFrame", padding=(8, 5))
            row, col = divmod(index, 4)
            box.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            ttk.Label(box, text=key, style="Sidebar.TLabel", font=("TkDefaultFont", 8, "bold")).pack(side="left")
            value = ttk.Label(box, text="—", style="Sidebar.TLabel")
            value.pack(side="right", padx=(8, 0))
            self.metadata_labels[key] = value
        for col in range(4):
            self.metadata_frame.columnconfigure(col, weight=1)

        ttk.Separator(self.main_area).pack(fill="x")
        body = ttk.Panedwindow(self.main_area, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.message_panel = ttk.Frame(body, style="Panel.TFrame", padding=12, width=275)
        self.content_panel = ttk.Frame(body, style="Panel.TFrame")
        body.add(self.message_panel, weight=0)
        body.add(self.content_panel, weight=1)
        self.build_message_panel()
        self.build_content_pages()

    def build_message_panel(self):
        self.workspace_title_label = ttk.Label(self.message_panel, text="Workspace", style="Header.TLabel")
        self.workspace_title_label.pack(anchor="w")
        self.workspace_count_label = ttk.Label(self.message_panel, text="0 messages", style="Muted.TLabel")
        self.workspace_count_label.pack(anchor="w", pady=(0, 8))
        entry = ttk.Entry(self.message_panel, textvariable=self.message_filter_var)
        entry.pack(fill="x", pady=(0, 8))
        entry.bind("<KeyRelease>", lambda _e: self.refresh_message_tree())
        self.message_tree = ttk.Treeview(self.message_panel, columns=("patient", "control", "size"), show="tree headings", selectmode="browse")
        self.message_tree.heading("#0", text="Type")
        self.message_tree.heading("patient", text="Patient")
        self.message_tree.heading("control", text="Control ID")
        self.message_tree.heading("size", text="Size")
        self.message_tree.column("#0", width=85, stretch=False)
        self.message_tree.column("patient", width=135, stretch=True)
        self.message_tree.column("control", width=105, stretch=False)
        self.message_tree.column("size", width=55, stretch=False)
        y = ttk.Scrollbar(self.message_panel, orient="vertical", command=self.message_tree.yview)
        self.message_tree.configure(yscrollcommand=y.set)
        self.message_tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        self.message_tree.bind("<<TreeviewSelect>>", self.on_message_select)
        self.message_tree.bind("<Double-1>", lambda _e: self.show_view("Inspect"))

    def build_content_pages(self):
        self.pages: dict[str, ttk.Frame] = {}
        self.pages["Inspect"] = self.build_inspect_page()
        self.pages["Analyze"] = self.build_analyze_page()
        self.pages["Compare"] = self.build_compare_page()
        self.pages["Assistant"] = self.build_assistant_page()
        self.pages["Integrations"] = self.build_integrations_page()
        self.pages["Transmit"] = self.build_transmit_page()
        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.show_view("Inspect")

    # ---------- Page builders ----------
    def build_inspect_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=(6, 6, 10, 10))
        self.inspect_notebook = ttk.Notebook(page)
        self.inspect_notebook.pack(fill="both", expand=True)

        workbench = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        form = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        structure = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        raw = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        validation = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        plain = ttk.Frame(self.inspect_notebook, style="Panel.TFrame")
        for frame, label in ((workbench, "Workbench"), (form, "Form"), (structure, "Structure"), (raw, "Raw"), (validation, "Validation"), (plain, "Plain English")):
            self.inspect_notebook.add(frame, text=label)

        pane = ttk.Panedwindow(workbench, orient="horizontal")
        pane.pack(fill="both", expand=True)
        raw_frame = ttk.Labelframe(pane, text="Raw message", padding=6)
        field_frame = ttk.Labelframe(pane, text="Field form", padding=6)
        pane.add(raw_frame, weight=2)
        pane.add(field_frame, weight=3)
        self.segment_tree = ttk.Treeview(raw_frame, columns=("raw",), show="tree headings", selectmode="browse")
        self.segment_tree.heading("#0", text="# / Segment")
        self.segment_tree.heading("raw", text="ER7 content")
        self.segment_tree.column("#0", width=95, stretch=False)
        self.segment_tree.column("raw", width=460)
        sy = ttk.Scrollbar(raw_frame, orient="vertical", command=self.segment_tree.yview)
        sx = ttk.Scrollbar(raw_frame, orient="horizontal", command=self.segment_tree.xview)
        self.segment_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.segment_tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        raw_frame.rowconfigure(0, weight=1)
        raw_frame.columnconfigure(0, weight=1)
        self.segment_tree.bind("<<TreeviewSelect>>", self.on_segment_select)

        searchbar = ttk.Frame(field_frame, style="Panel.TFrame")
        searchbar.pack(fill="x", pady=(0, 6))
        ttk.Label(searchbar, text="Search fields:", style="Panel.TLabel").pack(side="left")
        field_search = ttk.Entry(searchbar, textvariable=self.field_search_var)
        field_search.pack(side="left", fill="x", expand=True, padx=6)
        field_search.bind("<KeyRelease>", lambda _e: self.refresh_field_tree())
        ttk.Button(searchbar, text="Statistics", command=lambda: self.show_view("Analyze")).pack(side="right")

        self.field_tree = ttk.Treeview(field_frame, columns=("path", "name", "value"), show="headings", selectmode="browse")
        self.field_tree.heading("path", text="Path")
        self.field_tree.heading("name", text="Field name")
        self.field_tree.heading("value", text="Value")
        self.field_tree.column("path", width=105, stretch=False)
        self.field_tree.column("name", width=210)
        self.field_tree.column("value", width=360)
        fy = ttk.Scrollbar(field_frame, orient="vertical", command=self.field_tree.yview)
        self.field_tree.configure(yscrollcommand=fy.set)
        self.field_tree.pack(side="left", fill="both", expand=True)
        fy.pack(side="right", fill="y")
        self.field_tree.bind("<<TreeviewSelect>>", self.on_field_select)
        self.field_tree.bind("<Double-1>", lambda _e: self.focus_field_editor())

        editor = ttk.Labelframe(form, text="Edit selected field", padding=12)
        editor.pack(fill="x", padx=8, pady=8)
        self.form_path_label = ttk.Label(editor, text="Select a field", style="Header.TLabel")
        self.form_path_label.grid(row=0, column=0, sticky="w")
        self.form_name_label = ttk.Label(editor, text="", style="Muted.TLabel")
        self.form_name_label.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.field_value_var = tk.StringVar()
        self.field_value_entry = ttk.Entry(editor, textvariable=self.field_value_var)
        self.field_value_entry.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.field_suggestions = ttk.Combobox(editor, state="readonly")
        self.field_suggestions.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.field_suggestions.bind("<<ComboboxSelected>>", lambda _e: self.field_value_var.set(self.field_suggestions.get()))
        ttk.Button(editor, text="Apply Field Edit", style="Accent.TButton", command=self.apply_field_edit).grid(row=4, column=0, sticky="e")
        editor.columnconfigure(0, weight=1)
        self.form_tree = ttk.Treeview(form, columns=("path", "name", "value"), show="headings", selectmode="browse")
        for column, label, width in (("path", "Path", 120), ("name", "Human-readable name", 300), ("value", "Value", 600)):
            self.form_tree.heading(column, text=label)
            self.form_tree.column(column, width=width, stretch=True)
        form_y = ttk.Scrollbar(form, orient="vertical", command=self.form_tree.yview)
        self.form_tree.configure(yscrollcommand=form_y.set)
        self.form_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        form_y.pack(side="right", fill="y", padx=(0, 8), pady=(0, 8))
        self.form_tree.bind("<<TreeviewSelect>>", self.on_form_field_select)

        self.structure_tree = ttk.Treeview(structure, columns=("name", "value"), show="tree headings")
        self.structure_tree.heading("#0", text="Path")
        self.structure_tree.heading("name", text="Name")
        self.structure_tree.heading("value", text="Value")
        self.structure_tree.column("#0", width=180)
        self.structure_tree.column("name", width=280)
        self.structure_tree.column("value", width=600)
        structure_y = ttk.Scrollbar(structure, orient="vertical", command=self.structure_tree.yview)
        self.structure_tree.configure(yscrollcommand=structure_y.set)
        self.structure_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        structure_y.pack(side="right", fill="y", padx=(0, 8), pady=8)

        raw_toolbar = ttk.Frame(raw, style="Panel.TFrame", padding=8)
        raw_toolbar.pack(fill="x")
        ttk.Label(raw_toolbar, text="Editable ER7", style="Header.TLabel").pack(side="left")
        ttk.Button(raw_toolbar, text="Apply & Reparse", style="Accent.TButton", command=self.apply_raw_edit).pack(side="right")
        self.raw_text = tk.Text(raw, wrap="none", undo=True, font=("Menlo" if platform.system() == "Darwin" else "Consolas", 10))
        raw_y = ttk.Scrollbar(raw, orient="vertical", command=self.raw_text.yview)
        raw_x = ttk.Scrollbar(raw, orient="horizontal", command=self.raw_text.xview)
        self.raw_text.configure(yscrollcommand=raw_y.set, xscrollcommand=raw_x.set)
        self.raw_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        raw_y.pack(side="right", fill="y", pady=(0, 8))
        raw_x.pack(side="bottom", fill="x", padx=8)

        self.validation_tree = ttk.Treeview(validation, columns=("severity", "path", "message", "suggestion"), show="headings")
        for column, label, width in (("severity", "Severity", 90), ("path", "Path", 120), ("message", "Finding", 420), ("suggestion", "Suggested action", 420)):
            self.validation_tree.heading(column, text=label)
            self.validation_tree.column(column, width=width, stretch=column in {"message", "suggestion"})
        val_y = ttk.Scrollbar(validation, orient="vertical", command=self.validation_tree.yview)
        self.validation_tree.configure(yscrollcommand=val_y.set)
        self.validation_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        val_y.pack(side="right", fill="y", padx=(0, 8), pady=8)

        self.plain_text = tk.Text(plain, wrap="word", font=("TkDefaultFont", 11), padx=16, pady=16)
        self.plain_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.plain_text.configure(state="disabled")
        return page

    def build_analyze_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=12)
        header = ttk.Frame(page, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Collection Analytics", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Refresh", command=self.refresh_analytics).pack(side="right")
        self.analytics_summary = ttk.Label(page, text="", style="Muted.TLabel")
        self.analytics_summary.pack(fill="x", pady=(0, 8))
        self.analytics_tree = ttk.Treeview(page, columns=("path", "present", "fill", "unique", "length", "top"), show="headings")
        for column, label, width in (("path", "Field", 120), ("present", "Present", 90), ("fill", "Fill rate", 90), ("unique", "Unique", 80), ("length", "Min–max length", 120), ("top", "Frequent values", 500)):
            self.analytics_tree.heading(column, text=label)
            self.analytics_tree.column(column, width=width, stretch=column == "top")
        y = ttk.Scrollbar(page, orient="vertical", command=self.analytics_tree.yview)
        self.analytics_tree.configure(yscrollcommand=y.set)
        self.analytics_tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        return page

    def build_compare_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=12)
        header = ttk.Frame(page, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Field-aware Compare", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Compare with:", style="Panel.TLabel").pack(side="left", padx=(20, 5))
        self.compare_combo = ttk.Combobox(header, textvariable=self.compare_target_var, state="readonly", width=46)
        self.compare_combo.pack(side="left", fill="x", expand=True)
        self.compare_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_compare())
        ttk.Checkbutton(header, text="Show unchanged", variable=self.include_unchanged_var, command=self.refresh_compare).pack(side="left", padx=8)
        ttk.Button(header, text="Refresh", command=self.refresh_compare).pack(side="right")
        self.compare_summary_text = tk.Text(page, height=6, wrap="word", padx=10, pady=10)
        self.compare_summary_text.pack(fill="x", pady=(0, 8))
        self.compare_summary_text.configure(state="disabled")
        self.compare_tree = ttk.Treeview(page, columns=("kind", "path", "left", "right"), show="headings")
        for column, label, width in (("kind", "Change", 90), ("path", "Path", 130), ("left", "Selected message", 430), ("right", "Comparison message", 430)):
            self.compare_tree.heading(column, text=label)
            self.compare_tree.column(column, width=width, stretch=column in {"left", "right"})
        y = ttk.Scrollbar(page, orient="vertical", command=self.compare_tree.yview)
        self.compare_tree.configure(yscrollcommand=y.set)
        self.compare_tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        return page

    def build_assistant_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=12)
        header = ttk.Frame(page, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Local HL7 Assistant", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Rule-based · on-device · no upload", style="Muted.TLabel").pack(side="left", padx=12)
        ttk.Button(header, text="Copy Analysis", command=self.copy_assistant).pack(side="right")
        self.assistant_text = tk.Text(page, wrap="word", padx=18, pady=18, font=("TkDefaultFont", 11))
        self.assistant_text.pack(fill="both", expand=True)
        self.assistant_text.configure(state="disabled")
        return page

    def build_integrations_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=16)
        ttk.Label(page, text="Integration Tools", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="Local file and clipboard workflows. No message content is uploaded.", style="Muted.TLabel").pack(anchor="w", pady=(2, 16))
        grid = ttk.Frame(page, style="Panel.TFrame")
        grid.pack(fill="x")
        actions = [
            ("Open HL7 files", "Import one or more .hl7, .er7, or .txt files into separate workspaces.", self.open_files),
            ("Paste clipboard", "Create a workspace from HL7 content currently on the clipboard.", self.paste_message),
            ("Save selected message", "Write the active message as ER7 text.", self.export_selected),
            ("Export complete workspace", "Write all messages in the active workspace to one file.", self.export_workspace),
            ("Copy selected HL7", "Copy the exact active ER7 message.", self.copy_selected_message),
            ("Copy metadata", "Copy patient and routing metadata only.", self.copy_metadata),
            ("Open sample library", "Browse 347 synthetic training templates.", self.show_sample_library),
            ("Open MLLP test bench", "Send a message or run a local listener with AA ACK responses.", lambda: self.show_view("Transmit")),
        ]
        for index, (title, desc, command) in enumerate(actions):
            card = ttk.Labelframe(grid, text=title, padding=12)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            ttk.Label(card, text=desc, style="Panel.TLabel", wraplength=360).pack(anchor="w", fill="x", expand=True)
            ttk.Button(card, text="Open", command=command).pack(anchor="e", pady=(12, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        return page

    def build_transmit_page(self) -> ttk.Frame:
        page = ttk.Frame(self.content_panel, style="Panel.TFrame", padding=12)
        ttk.Label(page, text="MLLP Test Bench", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="Use only against systems and ports you are authorized to test.", style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        controls = ttk.Panedwindow(page, orient="horizontal")
        controls.pack(fill="x")
        sender = ttk.Labelframe(controls, text="Sender", padding=12)
        listener = ttk.Labelframe(controls, text="Local Listener", padding=12)
        controls.add(sender, weight=1)
        controls.add(listener, weight=1)
        self._labeled_entry(sender, "Host", self.transmit_host_var, 0)
        self._labeled_entry(sender, "Port", self.transmit_port_var, 1)
        self._labeled_entry(sender, "Timeout (seconds)", self.transmit_timeout_var, 2)
        ttk.Checkbutton(sender, text="Use TLS", variable=self.transmit_tls_var).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Button(sender, text="Send Selected Message", style="Accent.TButton", command=self.send_selected_mllp).grid(row=4, column=1, sticky="e", pady=(10, 0))
        sender.columnconfigure(1, weight=1)
        self._labeled_entry(listener, "Bind host", self.listener_host_var, 0)
        self._labeled_entry(listener, "Port", self.listener_port_var, 1)
        self.listener_button = ttk.Button(listener, text="Start Listener", style="Accent.TButton", command=self.toggle_listener)
        self.listener_button.grid(row=2, column=1, sticky="e", pady=(10, 0))
        listener.columnconfigure(1, weight=1)
        ttk.Label(page, text="Activity log", style="Header.TLabel").pack(anchor="w", pady=(12, 4))
        self.transmit_log = tk.Text(page, height=18, wrap="word", font=("Menlo" if platform.system() == "Darwin" else "Consolas", 10), padx=10, pady=10)
        self.transmit_log.pack(fill="both", expand=True)
        return page

    def _labeled_entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)

    # ---------- Workspace operations ----------
    @property
    def active_workspace(self) -> Workspace | None:
        return next((workspace for workspace in self.workspaces if workspace.id == self.active_workspace_id), None)

    @property
    def selected_message(self) -> HL7Message | None:
        workspace = self.active_workspace
        return workspace.selected_message if workspace else None

    def unique_title(self, base: str) -> str:
        titles = {workspace.title for workspace in self.workspaces}
        if base not in titles:
            return base
        index = 2
        while f"{base} {index}" in titles:
            index += 1
        return f"{base} {index}"

    def new_blank_workspace(self):
        workspace = Workspace(title=self.unique_title("Untitled.hl7"), draft="")
        self.workspaces.append(workspace)
        self.select_workspace(workspace.id)
        self.show_view("Inspect")
        self.inspect_notebook.select(3)
        self.raw_text.focus_set()

    def add_workspace_from_raw(self, raw: str, title: str, source_path: str = "", append_messages: list[str] | None = None):
        try:
            messages = HL7Parser.parse_stream(raw)
            for extra in append_messages or []:
                messages.extend(HL7Parser.parse_stream(extra))
        except (HL7ParseError, ValueError) as exc:
            messagebox.showerror("Unable to parse HL7", str(exc), parent=self)
            return None
        workspace = Workspace(title=self.unique_title(title), messages=messages, source_path=source_path)
        self.workspaces.append(workspace)
        self.select_workspace(workspace.id)
        return workspace

    def open_files(self):
        paths = filedialog.askopenfilenames(title="Open HL7 files", filetypes=[("HL7 messages", "*.hl7 *.er7 *.txt"), ("All files", "*.*")])
        for path in paths:
            self.open_path(path)

    def open_path(self, path: str):
        try:
            raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            messagebox.showerror("Unable to open file", str(exc), parent=self)
            return
        self.add_workspace_from_raw(raw, Path(path).name, source_path=str(path))

    def paste_message(self):
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Clipboard is empty", "Copy an HL7 message and try again.", parent=self)
            return
        if not raw.strip():
            messagebox.showinfo("Clipboard is empty", "Copy an HL7 message and try again.", parent=self)
            return
        self.add_workspace_from_raw(raw, "Clipboard.hl7")

    def show_sample_library(self):
        SampleLibraryDialog(self, lambda sample: self.add_workspace_from_raw(sample.raw, sample.title))

    def duplicate_workspace(self):
        workspace = self.active_workspace
        if not workspace:
            return
        raws = [message.raw for message in workspace.messages]
        if raws:
            self.add_workspace_from_raw("\r".join(raws), self.unique_title(f"{workspace.title} Copy"))
        else:
            clone = Workspace(title=self.unique_title(f"{workspace.title} Copy"), draft=workspace.draft)
            self.workspaces.append(clone)
            self.select_workspace(clone.id)

    def close_workspace(self):
        workspace = self.active_workspace
        if not workspace:
            return
        if workspace.dirty and not messagebox.askyesno("Close edited workspace?", "This workspace has unsaved edits. Close it anyway?", parent=self):
            return
        index = self.workspaces.index(workspace)
        self.closed_workspaces.append(workspace)
        self.workspaces.remove(workspace)
        if not self.workspaces:
            blank = Workspace(title="Untitled.hl7")
            self.workspaces.append(blank)
        self.select_workspace(self.workspaces[min(index, len(self.workspaces) - 1)].id)

    def reopen_workspace(self):
        if not self.closed_workspaces:
            self.bell()
            return
        workspace = self.closed_workspaces.pop()
        workspace.title = self.unique_title(workspace.title)
        self.workspaces.append(workspace)
        self.select_workspace(workspace.id)

    def move_workspace(self, direction: int):
        workspace = self.active_workspace
        if not workspace:
            return
        index = self.workspaces.index(workspace)
        target = index + direction
        if 0 <= target < len(self.workspaces):
            self.workspaces[index], self.workspaces[target] = self.workspaces[target], self.workspaces[index]
            self.refresh_workspace_tree()
            self.workspace_tree.selection_set(workspace.id)
            self.workspace_tree.see(workspace.id)

    def select_relative_workspace(self, direction: int):
        workspace = self.active_workspace
        if not workspace or not self.workspaces:
            return
        index = self.workspaces.index(workspace)
        self.select_workspace(self.workspaces[(index + direction) % len(self.workspaces)].id)

    def select_workspace(self, workspace_id: str):
        if not any(workspace.id == workspace_id for workspace in self.workspaces):
            return
        self.active_workspace_id = workspace_id
        self.message_filter_var.set(self.active_workspace.message_filter if self.active_workspace else "")
        self.refresh_workspace_tree()
        self.refresh_message_tree()
        self.refresh_all_views()

    def refresh_workspace_tree(self):
        if not hasattr(self, "workspace_tree"):
            return
        selected = self.active_workspace_id
        self.workspace_tree.delete(*self.workspace_tree.get_children())
        term = self.workspace_filter_var.get().strip().casefold()
        for workspace in self.workspaces:
            if term and term not in workspace.searchable_text():
                continue
            count = len(workspace.messages) if workspace.messages else "Draft"
            marker = " ●" if workspace.dirty else ""
            self.workspace_tree.insert("", "end", iid=workspace.id, text=workspace.title + marker, values=(count,))
        if selected and self.workspace_tree.exists(selected):
            self.workspace_tree.selection_set(selected)
            self.workspace_tree.focus(selected)
            self.workspace_tree.see(selected)

    def on_workspace_tree_select(self, _event=None):
        selection = self.workspace_tree.selection()
        if selection and selection[0] != self.active_workspace_id:
            self.select_workspace(selection[0])

    def refresh_message_tree(self):
        if not hasattr(self, "message_tree"):
            return
        workspace = self.active_workspace
        self.message_tree.delete(*self.message_tree.get_children())
        if not workspace:
            return
        workspace.message_filter = self.message_filter_var.get()
        self.workspace_title_label.configure(text=workspace.title)
        self.workspace_count_label.configure(text=f"{len(workspace.messages)} message{'s' if len(workspace.messages) != 1 else ''}" if workspace.messages else "Blank draft")
        visible_indices = []
        for index, message in enumerate(workspace.messages):
            if not HL7Analytics.matches(message, workspace.message_filter):
                continue
            visible_indices.append(index)
            self.message_tree.insert("", "end", iid=str(index), text=message.message_type, values=(message.patient_name, message.control_id, message.metadata()["Size"]))
        selected = str(workspace.selected_index)
        if self.message_tree.exists(selected):
            self.message_tree.selection_set(selected)
            self.message_tree.focus(selected)
            self.message_tree.see(selected)
        elif visible_indices:
            workspace.selected_index = visible_indices[0]
            self.message_tree.selection_set(str(visible_indices[0]))
            self.message_tree.focus(str(visible_indices[0]))

    def on_message_select(self, _event=None):
        workspace = self.active_workspace
        selection = self.message_tree.selection()
        if workspace and selection:
            workspace.selected_index = int(selection[0])
            self.refresh_all_views()

    # ---------- View refresh ----------
    def show_view(self, name: str):
        self.current_view = name
        self.pages[name].lift()
        for label, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if label == name else "Nav.TButton")
        if name == "Analyze":
            self.refresh_analytics()
        elif name == "Compare":
            self.refresh_compare_targets()
            self.refresh_compare()
        elif name == "Assistant":
            self.refresh_assistant()
        elif name == "Inspect":
            self.refresh_inspect()

    def refresh_all_views(self):
        self.refresh_header()
        self.refresh_inspect()
        self.refresh_analytics()
        self.refresh_compare_targets()
        self.refresh_compare()
        self.refresh_assistant()
        self.refresh_workspace_tree()

    def refresh_header(self):
        message = self.selected_message
        if not message:
            self.header_title.configure(text="Blank workspace — paste or type HL7 in Raw")
            for label in self.metadata_labels.values():
                label.configure(text="—")
            return
        self.header_title.configure(text=message.message_type.replace("^", " · ") + (f"  ({message.message_structure})" if message.message_structure else ""))
        metadata = message.metadata()
        for key, label in self.metadata_labels.items():
            value = metadata.get(key, "—")
            label.configure(text=value[:36] + "…" if len(value) > 37 else value)

    def refresh_inspect(self):
        message = self.selected_message
        self.segment_tree.delete(*self.segment_tree.get_children())
        self.field_tree.delete(*self.field_tree.get_children())
        self.form_tree.delete(*self.form_tree.get_children())
        self.structure_tree.delete(*self.structure_tree.get_children())
        self.validation_tree.delete(*self.validation_tree.get_children())
        self._set_text(self.raw_text, (message.raw if message else (self.active_workspace.draft if self.active_workspace else "")).replace("\r", "\n"), editable=True)
        self._set_readonly_text(self.plain_text, message_summary(message) if message else "Paste or type an HL7 message in the Raw tab, then choose Apply & Reparse.")
        if not message:
            return
        for index, segment in enumerate(message.segments, start=1):
            iid = f"{segment.name}[{segment.occurrence}]"
            self.segment_tree.insert("", "end", iid=iid, text=f"{index}  {segment.name}", values=(segment.raw,))
        if message.segments:
            first = f"{message.segments[0].name}[{message.segments[0].occurrence}]"
            self.segment_tree.selection_set(first)
            self.segment_tree.focus(first)
        self.refresh_field_tree()
        self.refresh_form_tree()
        self.refresh_structure_tree()
        for issue_index, issue in enumerate(HL7Validator.validate(message)):
            self.validation_tree.insert("", "end", iid=str(issue_index), values=(issue.severity.upper(), issue.path, issue.message, issue.suggestion))

    def refresh_field_tree(self):
        if not hasattr(self, "field_tree"):
            return
        message = self.selected_message
        self.field_tree.delete(*self.field_tree.get_children())
        if not message:
            return
        selection = self.segment_tree.selection()
        segment_id = selection[0] if selection else f"{message.segments[0].name}[1]"
        try:
            seg_name, occ_raw = segment_id.split("[")
            occurrence = int(occ_raw.rstrip("]"))
        except Exception:
            seg_name, occurrence = message.segments[0].name, message.segments[0].occurrence
        segment = message.segment(seg_name, occurrence)
        if not segment:
            return
        term = self.field_search_var.get().strip().casefold()
        max_field = len(segment.fields) + (1 if segment.name == "MSH" else 0)
        for number in range(1, max_field + 1):
            path = f"{segment.name}[{segment.occurrence}]-{number}"
            name = field_name(segment.name, number)
            value = segment.value(number)
            haystack = f"{path} {name} {value}".casefold()
            if term and term not in haystack:
                continue
            self.field_tree.insert("", "end", iid=path, values=(path, name, value or "<empty>"))

    def refresh_form_tree(self):
        message = self.selected_message
        if not message:
            return
        for segment in message.segments:
            max_field = len(segment.fields) + (1 if segment.name == "MSH" else 0)
            for number in range(1, max_field + 1):
                path = f"{segment.name}[{segment.occurrence}]-{number}"
                self.form_tree.insert("", "end", iid=path, values=(path, field_name(segment.name, number), segment.value(number) or "<empty>"))

    def refresh_structure_tree(self):
        message = self.selected_message
        if not message:
            return
        for segment in message.segments:
            seg_id = f"seg-{segment.name}-{segment.occurrence}"
            self.structure_tree.insert("", "end", iid=seg_id, text=f"{segment.name}[{segment.occurrence}]", values=(segment_name(segment.name), segment.raw))
            max_field = len(segment.fields) + (1 if segment.name == "MSH" else 0)
            for number in range(1, max_field + 1):
                path = f"{segment.name}[{segment.occurrence}]-{number}"
                value = segment.value(number)
                field_id = f"field-{path}"
                self.structure_tree.insert(seg_id, "end", iid=field_id, text=path, values=(field_name(segment.name, number), value or "<empty>"))
                repetitions = value.split(message.delimiters.repetition) if value else []
                for rep_idx, repetition in enumerate(repetitions, start=1):
                    components = repetition.split(message.delimiters.component)
                    if len(components) <= 1:
                        continue
                    rep_parent = field_id
                    if len(repetitions) > 1:
                        rep_parent = f"rep-{path}-{rep_idx}"
                        self.structure_tree.insert(field_id, "end", iid=rep_parent, text=f"Repetition {rep_idx}", values=("", repetition))
                    for comp_idx, component in enumerate(components, start=1):
                        comp_id = f"comp-{path}-{rep_idx}-{comp_idx}"
                        self.structure_tree.insert(rep_parent, "end", iid=comp_id, text=f"{path}[{rep_idx}].{comp_idx}", values=(component_name(segment.name, number, comp_idx), component or "<empty>"))

    def refresh_analytics(self):
        if not hasattr(self, "analytics_tree"):
            return
        workspace = self.active_workspace
        self.analytics_tree.delete(*self.analytics_tree.get_children())
        if not workspace or not workspace.messages:
            self.analytics_summary.configure(text="No parsed messages in the active workspace.")
            return
        counts = HL7Analytics.message_type_counts(workspace.messages)
        types = ", ".join(f"{key}: {value}" for key, value in counts.most_common())
        total_bytes = sum(message.size_bytes for message in workspace.messages)
        self.analytics_summary.configure(text=f"{len(workspace.messages)} messages · {total_bytes:,} bytes · {types}")
        for index, stat in enumerate(HL7Analytics.statistics(workspace.messages)):
            top = "; ".join(f"{value} ({count})" for value, count in stat.unique_values[:5])
            self.analytics_tree.insert("", "end", iid=str(index), values=(stat.path, f"{stat.present_count}/{stat.message_count}", f"{stat.fill_rate:.0%}", len(stat.unique_values), f"{stat.min_length}–{stat.max_length}", top))

    def all_message_choices(self) -> list[tuple[str, HL7Message]]:
        choices = []
        for workspace in self.workspaces:
            for index, message in enumerate(workspace.messages):
                label = f"{workspace.title} · {index + 1} · {message.message_type} · {message.control_id or 'no ID'}"
                choices.append((label, message))
        return choices

    def refresh_compare_targets(self):
        if not hasattr(self, "compare_combo"):
            return
        selected = self.selected_message
        choices = [(label, message) for label, message in self.all_message_choices() if message.id != (selected.id if selected else None)]
        self._compare_choices = choices
        labels = [label for label, _ in choices]
        self.compare_combo.configure(values=labels)
        if self.compare_target_var.get() not in labels:
            self.compare_target_var.set(labels[0] if labels else "")

    def refresh_compare(self):
        if not hasattr(self, "compare_tree"):
            return
        self.compare_tree.delete(*self.compare_tree.get_children())
        left = self.selected_message
        target_label = self.compare_target_var.get()
        right = next((message for label, message in getattr(self, "_compare_choices", []) if label == target_label), None)
        if not left or not right:
            self._set_readonly_text(self.compare_summary_text, "Open at least two messages to compare them.")
            return
        changes = HL7Analytics.diff(left, right, include_unchanged=self.include_unchanged_var.get())
        self._set_readonly_text(self.compare_summary_text, comparison_summary(left, right, changes))
        for index, entry in enumerate(changes):
            self.compare_tree.insert("", "end", iid=str(index), values=(entry.kind.upper(), entry.path, entry.left or "<empty>", entry.right or "<empty>"))

    def refresh_assistant(self):
        if not hasattr(self, "assistant_text"):
            return
        message = self.selected_message
        self._set_readonly_text(self.assistant_text, message_summary(message) if message else "No parsed message is selected.")

    # ---------- Inspect interaction ----------
    def on_segment_select(self, _event=None):
        self.refresh_field_tree()

    def on_field_select(self, _event=None):
        selection = self.field_tree.selection()
        if selection:
            self.load_field_editor(selection[0])

    def on_form_field_select(self, _event=None):
        selection = self.form_tree.selection()
        if selection:
            self.load_field_editor(selection[0])

    def load_field_editor(self, path: str):
        message = self.selected_message
        if not message:
            return
        try:
            parsed = parse_path(path)
        except ValueError:
            return
        self._field_path = path
        self.form_path_label.configure(text=path)
        self.form_name_label.configure(text=field_name(parsed.segment, parsed.field))
        self.field_value_var.set(message.value_at(path))
        suggestions = CODE_SUGGESTIONS.get(f"{parsed.segment}-{parsed.field}", [])
        self.field_suggestions.configure(values=suggestions)
        self.field_suggestions.set("")
        self.inspect_notebook.select(1)

    def focus_field_editor(self):
        self.field_value_entry.focus_set()
        self.field_value_entry.select_range(0, "end")

    def apply_field_edit(self):
        message = self.selected_message
        workspace = self.active_workspace
        if not message or not workspace or not self._field_path:
            return
        try:
            message.set_value_at(self._field_path, self.field_value_var.get())
        except Exception as exc:
            messagebox.showerror("Unable to edit field", str(exc), parent=self)
            return
        workspace.dirty = True
        self.refresh_message_tree()
        self.refresh_all_views()
        self.load_field_editor(self._field_path)

    def apply_raw_edit(self):
        workspace = self.active_workspace
        if not workspace:
            return
        raw = self.raw_text.get("1.0", "end-1c")
        try:
            messages = HL7Parser.parse_stream(raw)
        except Exception as exc:
            workspace.draft = raw
            workspace.dirty = True
            messagebox.showerror("Unable to parse HL7", str(exc), parent=self)
            return
        if workspace.messages and len(messages) == 1:
            workspace.messages[workspace.selected_index] = messages[0]
        else:
            workspace.messages = messages
            workspace.selected_index = 0
        workspace.draft = ""
        workspace.dirty = True
        self.refresh_message_tree()
        self.refresh_all_views()
        self.inspect_notebook.select(0)

    # ---------- Copy/export ----------
    def copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def copy_selected_message(self):
        message = self.selected_message
        if message:
            self.copy_to_clipboard(message.raw)

    def copy_metadata(self):
        message = self.selected_message
        if message:
            self.copy_to_clipboard("\n".join(f"{key}: {value}" for key, value in message.metadata().items()))

    def copy_assistant(self):
        self.copy_to_clipboard(self.assistant_text.get("1.0", "end-1c"))

    def export_selected(self):
        message = self.selected_message
        if not message:
            messagebox.showinfo("No message selected", "Select a parsed message first.", parent=self)
            return
        initial = f"{message.message_type.replace('^', '-')}-{message.control_id or 'message'}.hl7"
        path = filedialog.asksaveasfilename(title="Save selected HL7 message", initialdir=user_document_dir(), initialfile=initial, defaultextension=".hl7", filetypes=[("HL7 message", "*.hl7"), ("ER7 text", "*.er7"), ("Text", "*.txt")])
        if path:
            Path(path).write_text(message.raw, encoding="utf-8")
            if self.active_workspace:
                self.active_workspace.dirty = False
                self.refresh_workspace_tree()

    def export_workspace(self):
        workspace = self.active_workspace
        if not workspace:
            return
        content = "\r".join(message.raw for message in workspace.messages) if workspace.messages else self.raw_text.get("1.0", "end-1c")
        path = filedialog.asksaveasfilename(title="Export workspace", initialdir=user_document_dir(), initialfile=workspace.title if "." in workspace.title else workspace.title + ".hl7", defaultextension=".hl7", filetypes=[("HL7 message collection", "*.hl7"), ("ER7 text", "*.er7"), ("Text", "*.txt")])
        if path:
            Path(path).write_text(content, encoding="utf-8")
            workspace.dirty = False
            self.refresh_workspace_tree()

    # ---------- MLLP ----------
    def append_log(self, text: str):
        if not hasattr(self, "transmit_log"):
            return
        self.transmit_log.insert("end", text.rstrip() + "\n")
        self.transmit_log.see("end")

    def send_selected_mllp(self):
        message = self.selected_message
        if not message:
            messagebox.showinfo("No message selected", "Select a parsed message first.", parent=self)
            return
        try:
            host = self.transmit_host_var.get().strip()
            port = int(self.transmit_port_var.get())
            timeout = float(self.transmit_timeout_var.get())
            if not host or not (1 <= port <= 65535) or timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid sender settings", "Enter a valid host, port (1–65535), and positive timeout.", parent=self)
            return
        self.append_log(f"Sending {message.message_type} / {message.control_id} to {host}:{port} (TLS={self.transmit_tls_var.get()})…")

        def worker():
            try:
                response = send_message(host, port, message.raw, timeout=timeout, use_tls=self.transmit_tls_var.get())
                self.after(0, lambda: self.append_log(f"Sent {response.bytes_sent} bytes; received {response.bytes_received} bytes\n{response.raw}"))
            except Exception as exc:
                self.after(0, lambda: self.append_log(f"Send failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def toggle_listener(self):
        if self.listener and self.listener.running:
            self.listener.stop()
            self.listener_button.configure(text="Start Listener")
            return
        try:
            host = self.listener_host_var.get().strip()
            port = int(self.listener_port_var.get())
            if not host or not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid listener settings", "Enter a valid bind host and port (1–65535).", parent=self)
            return
        self.listener = MLLPListener(
            host,
            port,
            on_message=lambda raw: self._listener_queue.put(("message", raw)),
            on_log=lambda text: self._listener_queue.put(("log", text)),
        )
        self.listener.start()
        self.listener_button.configure(text="Stop Listener")

    def process_listener_queue(self):
        try:
            while True:
                kind, value = self._listener_queue.get_nowait()
                if kind == "log":
                    self.append_log(value)
                elif kind == "message":
                    self.add_workspace_from_raw(value, "MLLP Received.hl7")
        except queue.Empty:
            pass
        self.after(200, self.process_listener_queue)

    # ---------- General commands ----------
    def bind_shortcuts(self):
        modifier = "Command" if platform.system() == "Darwin" else "Control"
        bindings = {
            f"<{modifier}-n>": self.new_blank_workspace,
            f"<{modifier}-t>": self.new_blank_workspace,
            f"<{modifier}-o>": self.open_files,
            f"<{modifier}-s>": self.export_selected,
            f"<{modifier}-w>": self.close_workspace,
            f"<{modifier}-plus>": lambda: self.change_scale(0.1),
            f"<{modifier}-equal>": lambda: self.change_scale(0.1),
            f"<{modifier}-minus>": lambda: self.change_scale(-0.1),
            f"<{modifier}-0>": lambda: self.set_scale(1.0),
            f"<{modifier}-Return>": self.apply_raw_edit,
        }
        for sequence, command in bindings.items():
            self.bind_all(sequence, lambda _e, c=command: (c(), "break")[1])

    def change_scale(self, amount: float):
        self.set_scale(self.scale_var.get() + amount)

    def set_scale(self, value: float):
        self.scale_var.set(min(1.6, max(0.8, value)))
        self.apply_scale()

    def focus_event(self, event_name: str):
        widget = self.focus_get()
        if widget:
            try:
                widget.event_generate(event_name)
            except tk.TclError:
                pass

    def copy_focused_or_message(self):
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            try:
                widget.event_generate("<<Copy>>")
                return
            except tk.TclError:
                pass
        self.copy_selected_message()

    def paste_focused_or_workspace(self):
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            try:
                widget.event_generate("<<Paste>>")
                return
            except tk.TclError:
                pass
        self.paste_message()

    def _set_text(self, widget: tk.Text, value: str, editable: bool):
        previous = str(widget.cget("state"))
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.edit_reset()
        widget.configure(state="normal" if editable else "disabled")
        if not editable and previous == "normal":
            widget.configure(state="disabled")

    def _set_readonly_text(self, widget: tk.Text, value: str):
        self._set_text(widget, value, editable=False)

    def show_help(self):
        window = tk.Toplevel(self)
        window.title("HL7 Shines Help & Documentation")
        window.geometry("900x700")
        text = tk.Text(window, wrap="word", padx=18, pady=18)
        text.pack(fill="both", expand=True)
        help_text = f"""HL7 Shines {__version__}

GETTING STARTED
1. Choose Open file, Paste message, or Sample library.
2. Select a workspace and message.
3. Inspect fields in Workbench, edit in Form or Raw, and use Validation, Analyze, Compare, or Assistant.

FIELD SEARCH
Use free text such as hemoglobin, or a field query such as PID-3:MRN840271, MSH-9.1:ADT, or OBX-3.2:HEMOGLOBIN.

WORKSPACES
Use + to create a blank workspace. You can duplicate, reorder, close, and reopen workspaces. Each workspace keeps its own message collection and draft.

EDITING
Select a field, open Form, change the value, and choose Apply Field Edit. MSH-1 must be changed in Raw because it controls the field delimiter. Raw edits are reparsed when you choose Apply & Reparse.

VALIDATION
The validator checks required MSH fields, timestamps, segment names, coded values, OBX numeric values, and duplicate control IDs. It is a practical quick reference, not a conformance profile.

MLLP
Transmit sends the selected message inside MLLP framing. The listener accepts an MLLP message and returns an AA ACK. Use these tools only on systems you are authorized to test.

PRIVACY
Parsing, validation, analytics, comparison, samples, and Assistant analysis run locally. Network activity happens only after an explicit MLLP send or listener action. HL7 files may contain PHI; follow your organization's privacy and security requirements.

KEYBOARD
{self.accel('N')}  New blank workspace
{self.accel('O')}  Open files
{self.accel('S')}  Save selected message
{self.accel('W')}  Close workspace
{self.accel('+')} / {self.accel('-')}  Change interface size
{self.accel('0')}  Actual size
{self.accel('Return')}  Apply and reparse Raw editor
"""
        text.insert("1.0", help_text)
        text.configure(state="disabled")

    def show_about(self):
        messagebox.showinfo(
            "About HL7 Shines",
            f"HL7 Shines {__version__}\n\nCross-platform local-first HL7 v2.x workbench for macOS and Windows.\n\nCreator: Rohit Gundu / Rohit-Shines\n\nSynthetic samples are for training only. This tool is not a substitute for an implementation guide, conformance profile, or clinical judgment.",
            parent=self,
        )

    def on_close(self):
        if self.listener:
            self.listener.stop()
        if any(workspace.dirty for workspace in self.workspaces):
            if not messagebox.askyesno("Quit HL7 Shines?", "One or more workspaces have unsaved edits. Quit anyway?", parent=self):
                return
        self.save_preferences()
        self.destroy()
