# ui_builder.py
import os
import tkinter as tk
from tkinter import filedialog, Menu, messagebox, scrolledtext, simpledialog

import ttkbootstrap as tkb
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class UIBuilder:
    def __init__(self, app, config_manager, project_scanner, code_editor_manager, prompt_generator):
        self.app = app
        self.config_manager = config_manager
        self.project_scanner = project_scanner
        self.code_editor_manager = code_editor_manager
        self.prompt_generator = prompt_generator

        self.tree = None
        self.file_list = None
        self.code_editor = None
        self.line_numbers = None
        self.prompt_text = None
        self.search_var = tk.StringVar()
        self.search_entry = None
        self.project_label = None
        self.font_label = None

        self.include_structure = tk.BooleanVar(value=True)
        self.strip_comments = tk.BooleanVar(value=False)
        self.template_var = tk.StringVar(value="Standard")
        self.max_prompt_file_length_var = tk.IntVar(value=self.config_manager.max_prompt_file_length)

        self.workspace_notebook = None
        self.workspace_tabs = {}
        self._workspace_tab_changing = False

    def build_ui(self):
        self.create_menu_bar()
        self.create_toolbar()
        self.setup_main_content()
        self.setup_status_bar()
        self.setup_shortcuts()

    def setup_main_content(self):
        self.notebook = ttk.Notebook(self.app)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        explorer_tab = ttk.Frame(self.notebook)
        settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(explorer_tab, text=" 📁 Explorer ")
        self.notebook.add(settings_tab, text=" ⚙️ Settings ")

        self.setup_explorer_tab(explorer_tab)
        self.setup_settings_tab(settings_tab)

    # -----------------------------
    # Top UI (Menu + Toolbar)
    # -----------------------------
    def create_menu_bar(self):
        self.menubar = Menu(self.app)
        self.app.config(menu=self.menubar)

        file_menu = Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="📂 Add Workspace...", command=self.project_scanner.prompt_for_project, accelerator="Ctrl+O")
        file_menu.add_command(label="🗙 Close Workspace", command=self.project_scanner.close_active_workspace)
        file_menu.add_command(label="🔄 Reload Workspace", command=self.project_scanner.reload_project, accelerator="F5")
        file_menu.add_separator()
        file_menu.add_command(label="💾 Save File", command=self.code_editor_manager.save_current_editor_file, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="❌ Exit", command=self.app.quit)

        edit_menu = Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="📋 Copy File Prompt", command=lambda: self.prompt_generator.copy_selected_prompt(post_copy_action=True), accelerator="Ctrl+C")
        edit_menu.add_command(label="📂 Copy Folder Prompt", command=lambda: self.prompt_generator.copy_folder_prompt(post_copy_action=True), accelerator="Ctrl+Shift+C")
        edit_menu.add_command(label="🌐 Copy Project Prompt", command=lambda: self.prompt_generator.copy_project_prompt(post_copy_action=True), accelerator="Ctrl+Shift+P")
        edit_menu.add_command(label="🗄️ Copy Full Project Code", command=self.prompt_generator.copy_full_project_code, accelerator="Ctrl+Alt+C")

        tools_menu = Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="📊 Project Stats", command=self.project_scanner.show_project_stats)
        tools_menu.add_command(label="🎨 Smart Prompt", command=self.prompt_generator.generate_smart_prompt)
        tools_menu.add_command(label="🧮 Budgeted Project Prompt", command=self.prompt_generator.generate_project_prompt_budgeted)
        tools_menu.add_command(label="🔐 Secret Scan", command=self.prompt_generator.scan_project_for_secrets)
        tools_menu.add_command(label="🔗 Go to Line in Editor...", command=self.code_editor_manager.go_to_line_dialog, accelerator="Ctrl+G")

    def create_toolbar(self):
        self.toolbar = ttk.Frame(self.app, padding=5, bootstyle="secondary")
        self.toolbar.pack(fill=tk.X, padx=0, pady=0)

        self.project_label = ttk.Label(self.toolbar, text="No project loaded", font=("Segoe UI", 10, "bold"), bootstyle="light")
        self.project_label.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(self.toolbar, text="📂 Open", command=self.project_scanner.prompt_for_project, bootstyle=PRIMARY).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text="🔄 Reload", command=self.project_scanner.reload_project, bootstyle=INFO).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text="📊 Stats", command=self.project_scanner.show_project_stats, bootstyle=INFO).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text="💾 Save File", command=self.code_editor_manager.save_current_editor_file, bootstyle=SUCCESS).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.toolbar, text="🗄️ Copy Full Project", command=self.prompt_generator.copy_full_project_code, bootstyle=WARNING).pack(side=tk.LEFT, padx=5)

        search_frame = ttk.Frame(self.toolbar)
        search_frame.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Label(search_frame, text="🔍 Search:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 2))
        self.search_var.trace("w", self.project_scanner.on_search_change)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=25, bootstyle=SECONDARY)
        self.search_entry.pack(side=tk.LEFT)

    # ... rest of the file continues with proper indentation
