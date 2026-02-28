# ui_builder.py
import os
import tkinter as tk
from tkinter import filedialog, Menu, messagebox, scrolledtext, simpledialog

import ttkbootstrap as tkb
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class UIBuilder:
    def __init__(self, app_instance):
        self.app = app_instance

        # Dependencies (injected later)
        self.config_manager = None
        self.project_scanner = None
        self.code_editor_manager = None
        self.prompt_generator = None

        # Global UI references
        self.project_label = None
        self.status_label = None
        self.stats_label = None
        self.search_var = tk.StringVar()
        self.search_entry = None

        # Active workspace widgets (point to currently selected tab's widgets)
        self.tree = None
        self.file_list = None

        self.workspace_notebook = None
        self.workspace_tabs = {}
        self._workspace_tab_changing = False

        self.excluded_entry = None
        self.extensions_entry = None
        self.font_label = None

        self.include_structure = tk.BooleanVar(value=True)
        self.strip_comments = tk.BooleanVar(value=False)
        self.template_var = tk.StringVar(value="Standard")
        self.max_prompt_file_length_var = tk.IntVar()  # set after config loaded

        # Editor/Prompt widgets
        self.code_editor = None
        self.line_numbers = None
        self.prompt_text = None

    def set_dependencies(self, config_manager, project_scanner, code_editor_manager, prompt_generator):
        self.config_manager = config_manager
        self.project_scanner = project_scanner
        self.code_editor_manager = code_editor_manager
        self.prompt_generator = prompt_generator

        self.max_prompt_file_length_var.set(self.config_manager.max_prompt_file_length)

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

    # -----------------------------
    # Explorer Tab
    # -----------------------------
    def setup_explorer_tab(self, parent_frame):
        self.pane = ttk.PanedWindow(parent_frame, orient=tk.HORIZONTAL)
        self.pane.pack(fill=tk.BOTH, expand=True)

        self.left_panel = ttk.Frame(self.pane)
        self.right_panel = ttk.Frame(self.pane)

        self.pane.add(self.left_panel, weight=1)
        self.pane.add(self.right_panel, weight=3)
        self.app.after(100, lambda: self.pane.sashpos(0, 300))

        self.left_panel.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.workspace_notebook = ttk.Notebook(self.left_panel)
        self.workspace_notebook.grid(row=0, column=0, sticky=tk.NSEW)
        self.workspace_notebook.bind("<<NotebookTabChanged>>", self._on_workspace_tab_changed)

        self.right_panel.grid_rowconfigure(0, weight=2)
        self.right_panel.grid_rowconfigure(1, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)

        # Code Editor Area
        editor_container = ttk.Frame(self.right_panel, padding=5)
        editor_container.grid(row=0, column=0, sticky=tk.NSEW, pady=(0, 5))
        ttk.Label(editor_container, text="📝 Code Editor", style="Inverse.TLabel").pack(fill=tk.X, pady=(0, 5))

        editor_frame_with_lines = ttk.Frame(editor_container)
        editor_frame_with_lines.pack(fill=tk.BOTH, expand=True)

        self.line_numbers = tk.Text(
            editor_frame_with_lines,
            width=4,
            padx=3,
            borderwidth=0,
            background="#282c34",
            foreground="#636d83",
            font=("Consolas", self.config_manager.font_size),
            state=tk.DISABLED,
            wrap=tk.NONE,
            relief=tk.FLAT,
        )
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        self.code_editor = scrolledtext.ScrolledText(
            editor_frame_with_lines,
            wrap=tk.NONE,
            font=("Consolas", self.config_manager.font_size),
            bg="#1e222a",
            fg="#abb2bf",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            undo=True,
        )
        self.code_editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scroll sync
        self.code_editor.vbar.config(command=self.code_editor_manager.on_shared_yview)
        self.code_editor.config(yscrollcommand=self.code_editor.vbar.set)

        # Give widgets to manager
        self.code_editor_manager.set_editor_widgets(self.code_editor, self.line_numbers)
        self.code_editor_manager.setup_pygments_tags()

        # Prompt area
        prompt_container = ttk.Frame(self.right_panel, padding=5)
        prompt_container.grid(row=1, column=0, sticky=tk.NSEW)
        ttk.Label(prompt_container, text="🤖 Generated Prompt", style="Inverse.TLabel").pack(fill=tk.X, pady=(0, 5))

        controls_frame = ttk.Frame(prompt_container, padding=5, bootstyle=SECONDARY)
        controls_frame.pack(fill=tk.X, pady=(5, 5))

        ttk.Checkbutton(
            controls_frame,
            text="Include Structure",
            variable=self.include_structure,
            bootstyle="success-round-toggle",
        ).grid(row=0, column=0, padx=(0, 10), sticky=tk.W)

        ttk.Checkbutton(
            controls_frame,
            text="Strip Comments",
            variable=self.strip_comments,
            bootstyle="success-round-toggle",
        ).grid(row=0, column=1, padx=(0, 20), sticky=tk.W)

        ttk.Label(controls_frame, text="Template:", bootstyle=LIGHT).grid(row=0, column=2, padx=(20, 5), sticky=tk.E)
        ttk.Combobox(
            controls_frame,
            textvariable=self.template_var,
            width=12,
            values=["Standard", "Debug", "Review", "Refactor"],
            state="readonly",
            bootstyle=INFO,
        ).grid(row=0, column=3, sticky=tk.E)

        self.max_prompt_file_length_var.trace_add("write", self.config_manager.on_max_length_change)
        ttk.Label(controls_frame, text="Max File Chars:", bootstyle=LIGHT).grid(row=1, column=0, pady=(5, 0), sticky=tk.W)
        ttk.Entry(controls_frame, textvariable=self.max_prompt_file_length_var, width=8, bootstyle=SECONDARY).grid(row=1, column=1, pady=(5, 0), sticky=tk.W)

        ttk.Button(
            controls_frame,
            text="📋 Copy Prompt",
            command=self.prompt_generator.copy_current_prompt,
            bootstyle=PRIMARY,
        ).grid(row=1, column=2, padx=(20, 5), pady=(5, 0), sticky=tk.E)

        ttk.Button(
            controls_frame,
            text="💾 Save Prompt",
            command=self.prompt_generator.save_prompt_to_file,
            bootstyle=INFO,
        ).grid(row=1, column=3, pady=(5, 0), sticky=tk.E)

        ttk.Button(
            controls_frame,
            text="📏 Tokens",
            command=self.prompt_generator.show_prompt_token_estimate,
            bootstyle=INFO,
        ).grid(row=1, column=4, padx=(8, 0), pady=(5, 0), sticky=tk.E)

        controls_frame.grid_columnconfigure(0, weight=1)
        controls_frame.grid_columnconfigure(1, weight=1)

        self.prompt_text = scrolledtext.ScrolledText(
            prompt_container,
            height=12,
            font=("Consolas", self.config_manager.font_size),
            bg="#1a1a1a",
            fg="#cccccc",
            relief=tk.FLAT,
        )
        self.prompt_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.prompt_generator.set_prompt_text_widget(self.prompt_text)

        # Bind editor events
        self.code_editor.bind("<<Modified>>", self.code_editor_manager.on_editor_content_modified)
        self.code_editor.bind("<MouseWheel>", self.code_editor_manager.on_editor_mouse_wheel)

    # -----------------------------
    # Workspace Tabs
    # -----------------------------
    def add_workspace_tab(self, project_path: str):
        if not self.workspace_notebook:
            return

        project_path = os.path.abspath(project_path)
        if project_path in self.workspace_tabs:
            self.select_workspace_tab(project_path)
            return

        tab_frame = ttk.Frame(self.workspace_notebook, padding=0)
        tab_frame.grid_rowconfigure(0, weight=1)
        tab_frame.grid_rowconfigure(1, weight=1)
        tab_frame.grid_columnconfigure(0, weight=1)

        # Tree
        tree_container = ttk.Frame(tab_frame, padding=5)
        tree_container.grid(row=0, column=0, sticky=tk.NSEW, pady=(0, 5))
        
        tree_header = ttk.Frame(tree_container)
        tree_header.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(tree_header, text="📁 Project Structure", style="Inverse.TLabel").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        folder_controls = ttk.Frame(tree_header)
        folder_controls.pack(side=tk.RIGHT)
        ttk.Button(folder_controls, text="✓ All", command=self.select_all_folders, width=6, bootstyle="success-outline").pack(side=tk.LEFT, padx=2)
        ttk.Button(folder_controls, text="✗ All", command=self.deselect_all_folders, width=6, bootstyle="danger-outline").pack(side=tk.LEFT, padx=2)

        tree = ttk.Treeview(tree_container, selectmode="browse", bootstyle=SECONDARY)
        tree.heading("#0", text="Files & Folders", anchor="w")

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=tree.yview, bootstyle="secondary-round")
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # File list
        list_container = ttk.Frame(tab_frame, padding=5)
        list_container.grid(row=1, column=0, sticky=tk.NSEW)
        ttk.Label(list_container, text="📄 All Files", style="Inverse.TLabel").pack(fill=tk.X, pady=(0, 5))

        file_list = ttk.Treeview(list_container, columns=("Size", "Type"), show="tree headings", bootstyle=SECONDARY)
        file_list.heading("#0", text="File", anchor="w")
        file_list.heading("Size", text="Size", anchor="e")
        file_list.heading("Type", text="Type", anchor="w")
        file_list.column("Size", width=80, anchor="e", stretch=tk.NO)
        file_list.column("Type", width=60, anchor="w", stretch=tk.NO)

        list_scroll = ttk.Scrollbar(list_container, orient="vertical", command=file_list.yview, bootstyle="secondary-round")
        file_list.configure(yscrollcommand=list_scroll.set)
        file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Bindings
        tree.bind("<<TreeviewSelect>>", self.project_scanner.on_tree_select)
        tree.bind("<Button-3>", self.show_context_menu)
        tree.bind("<Button-1>", self.on_tree_click)
        file_list.bind("<<TreeviewSelect>>", self.project_scanner.on_list_select)
        file_list.bind("<Button-3>", self.show_context_menu)

        tab_title = os.path.basename(project_path) or project_path
        self.workspace_notebook.add(tab_frame, text=f" {tab_title} ")

# ... (rest of the code remains the same)
        self.workspace_tabs[project_path] = {"frame": tab_frame, "tree": tree, "file_list": file_list}
        self.select_workspace_tab(project_path)

    def remove_workspace_tab(self, project_path: str):
        if not self.workspace_notebook:
            return

        project_path = os.path.abspath(project_path)
        tab = self.workspace_tabs.get(project_path)
        if not tab:
            return

        try:
            self.workspace_notebook.forget(tab["frame"])
        except Exception:
            pass

        self.workspace_tabs.pop(project_path, None)
        self._on_workspace_tab_changed(None)

    def select_workspace_tab(self, project_path: str):
        if not self.workspace_notebook:
            return

        project_path = os.path.abspath(project_path)
        tab = self.workspace_tabs.get(project_path)
        if not tab:
            return

        try:
            self._workspace_tab_changing = True
            self.workspace_notebook.select(tab["frame"])
        finally:
            self._workspace_tab_changing = False

        self._set_active_widgets_for_workspace(project_path)

    def _on_workspace_tab_changed(self, event):
        if not self.workspace_notebook or self._workspace_tab_changing:
            return

        selected = self.workspace_notebook.select()
        if not selected:
            self.tree = None
            self.file_list = None
            return

        selected_frame = self.workspace_notebook.nametowidget(selected)
        for path, tab in self.workspace_tabs.items():
            if tab["frame"] == selected_frame:
                self._set_active_widgets_for_workspace(path)
                break

    def _set_active_widgets_for_workspace(self, project_path: str):
        project_path = os.path.abspath(project_path)
        tab = self.workspace_tabs.get(project_path)
        if not tab:
            return

        self.tree = tab["tree"]
        self.file_list = tab["file_list"]

        # Tell scanner to switch active workspace
        if hasattr(self.project_scanner, "set_active_workspace"):
            self.project_scanner.set_active_workspace(project_path)

    # -----------------------------
    # Settings Tab
    # -----------------------------
    def setup_settings_tab(self, parent_frame):
        settings_main = ttk.Frame(parent_frame, padding=15)
        settings_main.pack(fill=tk.BOTH, expand=True)

        filters_frame = ttk.LabelFrame(settings_main, text="File Filters", padding=15, bootstyle=PRIMARY)
        filters_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(filters_frame, text="Excluded folders/files (comma-separated, relative paths or names):").pack(anchor="w", pady=(5, 5))
        self.excluded_entry = tk.Text(filters_frame, height=3, font=("Consolas", 10), relief=tk.FLAT, bg="#1a1a1a", fg="#cccccc")
        self.excluded_entry.pack(fill=tk.X, expand=True, pady=(0, 10))
        self.excluded_entry.insert("1.0", ", ".join(self.config_manager.excluded_patterns))

        ttk.Label(filters_frame, text="Included file extensions (comma-separated, e.g., .py, .js):").pack(anchor="w", pady=(5, 5))
        self.extensions_entry = tk.Text(filters_frame, height=3, font=("Consolas", 10), relief=tk.FLAT, bg="#1a1a1a", fg="#cccccc")
        self.extensions_entry.pack(fill=tk.X, expand=True, pady=(0, 10))
        self.extensions_entry.insert("1.0", ", ".join(self.config_manager.included_extensions))

        buttons_frame = ttk.Frame(filters_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            buttons_frame,
            text="💾 Save Settings",
            command=lambda: self.config_manager.save_settings(self.excluded_entry, self.extensions_entry, self.max_prompt_file_length_var),
            bootstyle=SUCCESS,
        ).pack(side=tk.LEFT)

        ttk.Button(
            buttons_frame,
            text="🔄 Reset Defaults",
            command=lambda: self.config_manager.reset_settings(self.excluded_entry, self.extensions_entry, self.max_prompt_file_length_var, self.font_label),
            bootstyle=WARNING,
        ).pack(side=tk.LEFT, padx=(10, 0))

        font_frame = ttk.LabelFrame(settings_main, text="Display Settings", padding=15, bootstyle=PRIMARY)
        font_frame.pack(fill=tk.X, pady=(10, 0))

        font_controls = ttk.Frame(font_frame)
        font_controls.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(font_controls, text="Editor Font Size:").pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(font_controls, text="-", command=lambda: self.code_editor_manager.change_font_size(-1), width=5, bootstyle=LIGHT).pack(side=tk.LEFT, padx=(10, 0))
        self.font_label = ttk.Label(font_controls, text=str(self.config_manager.font_size), font=("Segoe UI", 10, "bold"), width=3, anchor=tk.CENTER)
        self.font_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(font_controls, text="+", command=lambda: self.code_editor_manager.change_font_size(1), width=5, bootstyle=LIGHT).pack(side=tk.LEFT)

    # -----------------------------
    # Status + Shortcuts
    # -----------------------------
    def setup_status_bar(self):
        self.status_frame = ttk.Frame(self.app, bootstyle=SECONDARY)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=0, pady=0)

        self.status_label = ttk.Label(self.status_frame, text="Ready", style="Status.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=5, pady=2, fill=tk.X, expand=True)

        self.stats_label = ttk.Label(self.status_frame, text="", style="Status.TLabel")
        self.stats_label.pack(side=tk.RIGHT, padx=5, pady=2)

    def setup_shortcuts(self):
        self.app.bind("<Control-o>", lambda e: self.project_scanner.prompt_for_project())
        self.app.bind("<F5>", lambda e: self.project_scanner.reload_project())
        self.app.bind("<Control-s>", lambda e: self.code_editor_manager.save_current_editor_file())
        self.app.bind("<Control-c>", lambda e: self.prompt_generator.copy_selected_prompt(post_copy_action=True))
        self.app.bind("<Control-f>", lambda e: self.search_entry.focus() if self.search_entry else None)
        self.app.bind("<Control-g>", lambda e: self.code_editor_manager.go_to_line_dialog())
        self.app.bind("<Control-Alt-c>", lambda e: self.prompt_generator.copy_full_project_code())

    # -----------------------------
    # Folder Selection Controls
    # -----------------------------
    def on_tree_click(self, event):
        """Handle tree click - toggle checkbox if clicking on a folder."""
        if not self.tree:
            return
        
        if not hasattr(self, 'project_scanner') or not self.project_scanner:
            return
        
        try:
            item_id = self.tree.identify_row(event.y)
            if not item_id:
                return
            
            values = self.tree.item(item_id, "values")
            if not values or len(values) < 1:
                return
            
            folder_path = values[0]
            if not os.path.isdir(folder_path):
                return
            
            is_included = self.project_scanner.toggle_folder_exclusion(folder_path)
            self.update_folder_visual_state(item_id, folder_path, is_included)
            
            excluded_count = len(self.project_scanner.excluded_folders)
            if excluded_count > 0:
                self.app.set_status(f"Folder {'included' if is_included else 'excluded'}. {excluded_count} folder(s) excluded from full copy.")
            else:
                self.app.set_status("All folders included for full project copy.")
                
        except Exception as e:
            print(f"Error handling tree click: {e}")
            import traceback
            traceback.print_exc()
    
    def update_folder_visual_state(self, item_id, folder_path, is_included):
        """Update the visual state of a folder in the tree."""
        if not self.tree:
            return
        
        try:
            current_text = self.tree.item(item_id, "text")
            folder_name = current_text.strip()
            
            # Remove existing checkbox and folder icon
            for marker in ["☑ 📁 ", "☐ 📁 ", "☑ ", "☐ ", "📁 "]:
                if folder_name.startswith(marker):
                    folder_name = folder_name[len(marker):]
                    break
            
            # Add checkbox based on inclusion state
            if is_included:
                checkbox = "☑"
                tags = ("included",)
            else:
                checkbox = "☐"
                tags = ("excluded",)
            
            new_text = f"{checkbox} 📁 {folder_name}"
            self.tree.item(item_id, text=new_text, tags=tags)
            
            # Configure tag colors
            self.tree.tag_configure("excluded", foreground="#888888")
            self.tree.tag_configure("included", foreground="")
            
        except Exception as e:
            print(f"Error updating folder visual state: {e}")
    
    def select_all_folders(self):
        """Include all folders for full project copy."""
        if not hasattr(self, 'project_scanner') or not self.project_scanner:
            return
        
        if not self.project_scanner.project_path:
            return
        
        try:
            self.project_scanner.clear_all_exclusions()
            self.refresh_folder_visual_states()
            self.app.set_status("All folders included for full project copy.")
        except Exception as e:
            print(f"Error selecting all folders: {e}")
            import traceback
            traceback.print_exc()
    
    def deselect_all_folders(self):
        """Exclude all folders from full project copy."""
        if not hasattr(self, 'project_scanner') or not self.project_scanner:
            return
        
        if not self.project_scanner.project_path:
            return
        
        try:
            self.project_scanner.exclude_all_folders()
            self.refresh_folder_visual_states()
            excluded_count = len(self.project_scanner.excluded_folders)
            self.app.set_status(f"{excluded_count} folder(s) excluded from full project copy.")
        except Exception as e:
            print(f"Error deselecting all folders: {e}")
            import traceback
            traceback.print_exc()
    
    def refresh_folder_visual_states(self):
        """Refresh visual states of all folders in the tree."""
        if not self.tree:
            return
        
        if not hasattr(self, 'project_scanner') or not self.project_scanner:
            return
        
        try:
            def update_item(item_id):
                try:
                    values = self.tree.item(item_id, "values")
                    if values and len(values) > 0:
                        folder_path = values[0]
                        if os.path.isdir(folder_path):
                            is_included = not self.project_scanner.is_folder_excluded(folder_path)
                            self.update_folder_visual_state(item_id, folder_path, is_included)
                    
                    # Recursively update children
                    for child_id in self.tree.get_children(item_id):
                        update_item(child_id)
                except Exception as e:
                    print(f"Error updating item {item_id}: {e}")
            
            # Start from root items
            for root_item in self.tree.get_children():
                update_item(root_item)
                
        except Exception as e:
            print(f"Error refreshing folder visual states: {e}")
            import traceback
            traceback.print_exc()

    # -----------------------------
    # Context Menu
    # -----------------------------
    def show_context_menu(self, event):
        try:
            menu = Menu(self.app, tearoff=0)

            selected_item_id = None
            widget_clicked = None

            if self.tree and self.tree.identify_row(event.y):
                selected_item_id = self.tree.identify_row(event.y)
                self.tree.selection_set(selected_item_id)
                widget_clicked = self.tree
            elif self.file_list and self.file_list.identify_row(event.y):
                selected_item_id = self.file_list.identify_row(event.y)
                self.file_list.selection_set(selected_item_id)
                widget_clicked = self.file_list

            if selected_item_id and widget_clicked:
                values = widget_clicked.item(selected_item_id, "values") or ()

                if widget_clicked == self.tree:
                    if len(values) < 1:
                        return
                    potential_path = values[0]
                else:
                    if len(values) < 3:
                        return
                    potential_path = values[2]

                if os.path.isdir(potential_path):
                    menu.add_command(label="📁 Copy Folder Prompt", command=lambda: self.prompt_generator.copy_folder_prompt(post_copy_action=True))
                    menu.add_separator()
                    menu.add_command(label="🌐 Copy Project Prompt", command=lambda: self.prompt_generator.copy_project_prompt(post_copy_action=True))
                    menu.add_command(label="🗄️ Copy Full Project Code", command=self.prompt_generator.copy_full_project_code)
                else:
                    menu.add_command(label="📋 Copy File Prompt", command=lambda: self.prompt_generator.copy_selected_prompt(post_copy_action=True))
                    menu.add_command(label="📝 Open in Editor", command=self.project_scanner.open_selected_in_editor)
                    menu.add_separator()
                    if self.code_editor_manager.current_editor_file and os.path.isfile(self.code_editor_manager.current_editor_file):
                        menu.add_command(label="💾 Save Current File", command=self.code_editor_manager.save_current_editor_file)

            menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Context menu error: {e}")
            self.app.set_status(f"Error showing context menu: {e}")