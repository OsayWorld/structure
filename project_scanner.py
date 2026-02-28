# project_scanner.py
import os
import json
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
from dataclasses import dataclass, field

# Optional imports from app_core for highlighting if needed in worker
try:
    from pygments import lex
    from pygments.lexers import get_lexer_for_filename, guess_lexer_for_filename, TextLexer
    from pygments.token import Token
    SYNTAX_HIGHLIGHTING = True
except ImportError:
    SYNTAX_HIGHLIGHTING = False

class ProjectScanner:
    def __init__(self, app_instance, config_manager):
        self.app = app_instance
        self.config_manager = config_manager
        
        # References to other managers, set after initialization
        self.ui_builder = None
        self.code_editor_manager = None
        self.prompt_generator = None

        self.project_path = None

        self.workspace_paths = []
        self.active_workspace_path = None

        self.file_count = 0
        self.total_size = 0

        # Threading state for project scan
        self.scan_thread = None
        self.scan_in_progress = False
        self.scanned_tree_data = [] # Active workspace tree data
        self.scanned_file_list_data = [] # Active workspace file list data
        self.scan_error = None

        self.search_job = None

        self.PRELOAD_FILE_SIZE_LIMIT = 100 * 1024 # 100 KB limit for pre-reading and lexing

        self.index_cache_dir = os.path.join(os.path.dirname(__file__), ".project_index_cache")

        @dataclass
        class _WorkspaceState:
            project_path: str
            file_count: int = 0
            total_size: int = 0
            scanned_tree_data: list = field(default_factory=list)
            scanned_file_list_data: list = field(default_factory=list)
            loaded: bool = False

        self._WorkspaceState = _WorkspaceState
        self._workspaces = {}

    def set_dependencies(self, code_editor_manager, prompt_generator):
        # Access ui_builder after its initialization in app_core
        self.ui_builder = self.app.ui_builder 
        self.code_editor_manager = code_editor_manager
        self.prompt_generator = prompt_generator

    def initialize_project(self):
        """Initialize with last project or remembered workspaces."""
        try:
            initial_paths = []

            if getattr(self.config_manager, 'workspace_paths', None):
                initial_paths = [p for p in self.config_manager.workspace_paths if p and os.path.exists(p)]
            elif self.config_manager.last_project_path and os.path.exists(self.config_manager.last_project_path):
                initial_paths = [self.config_manager.last_project_path]

            if not initial_paths:
                self.app.set_status("Ready - Use 'File' > 'Add Workspace...' to start.")
                return

            for p in initial_paths:
                self._ensure_workspace(p)
                if hasattr(self.ui_builder, 'add_workspace_tab') and hasattr(self.ui_builder, 'workspace_notebook') and self.ui_builder.workspace_notebook:
                    try:
                        self.ui_builder.add_workspace_tab(p)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).exception("Failed to add workspace tab during init for %s", p)

            active = getattr(self.config_manager, 'active_workspace_path', '')
            if active and active in self._workspaces:
                self.set_active_workspace(active)
            else:
                self.set_active_workspace(initial_paths[0])
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Error initializing project")
            self.app.set_status("Ready - Error initializing project.")

    def prompt_for_project(self):
        """Ask user to select a workspace folder and add it."""
        try:
            project_path = filedialog.askdirectory(title="Select Workspace Folder", parent=self.app)
            if project_path:
                self.add_workspace(project_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to select project: {e}", parent=self.app)

    def load_project(self, project_path):
        """Load a project"""
        return self.load_project_cached(project_path, force_rescan=False)

    def get_workspace_paths(self):
        return list(self.workspace_paths)

    def add_workspace(self, project_path: str):
        if not project_path:
            return

        project_path = os.path.abspath(project_path)
        self._ensure_workspace(project_path)

        if hasattr(self.ui_builder, 'add_workspace_tab'):
            try:
                self.ui_builder.add_workspace_tab(project_path)
            except Exception:
                pass

        self.set_active_workspace(project_path)
        self.config_manager.save_config()

    def close_active_workspace(self):
        if not self.active_workspace_path:
            self.app.set_status("No workspace to close.")
            return
        self.close_workspace(self.active_workspace_path)

    def close_workspace(self, project_path: str):
        project_path = os.path.abspath(project_path)
        if project_path not in self._workspaces:
            return

        if self.scan_in_progress and self.project_path == project_path:
            messagebox.showwarning("Scan In Progress", "Cannot close the active workspace while a scan is running.", parent=self.app)
            return

        self._workspaces.pop(project_path, None)
        if project_path in self.workspace_paths:
            self.workspace_paths.remove(project_path)

        if hasattr(self.ui_builder, 'remove_workspace_tab'):
            try:
                self.ui_builder.remove_workspace_tab(project_path)
            except Exception:
                pass

        if self.active_workspace_path == project_path:
            if self.workspace_paths:
                self.set_active_workspace(self.workspace_paths[0])
            else:
                self.active_workspace_path = None
                self.project_path = None
                self.scanned_tree_data = []
                self.scanned_file_list_data = []
                self.file_count = 0
                self.total_size = 0
                if self.ui_builder.project_label:
                    self.ui_builder.project_label.config(text="No project loaded")
                if self.ui_builder.tree:
                    self.ui_builder.tree.delete(*self.ui_builder.tree.get_children())
                if self.ui_builder.file_list:
                    self.ui_builder.file_list.delete(*self.ui_builder.file_list.get_children())
                self.app.update_stats()

        self.config_manager.save_config()

    def set_active_workspace(self, project_path: str):
        project_path = os.path.abspath(project_path)
        if project_path not in self._workspaces:
            self._ensure_workspace(project_path)

        self.active_workspace_path = project_path
        self.project_path = project_path

        ws = self._workspaces[project_path]
        self.file_count = ws.file_count
        self.total_size = ws.total_size
        self.scanned_tree_data = ws.scanned_tree_data
        self.scanned_file_list_data = ws.scanned_file_list_data

        if self.ui_builder.project_label:
            self.ui_builder.project_label.config(text=f" {os.path.basename(project_path)}")

        if ws.loaded:
            self._process_scanned_data(self.scanned_tree_data, self.scanned_file_list_data)
            self.app.update_stats()
            self._do_search()
        else:
            self.load_project_cached(project_path, force_rescan=False)

        self.config_manager.active_workspace_path = project_path
        self.config_manager.last_project_path = project_path
        self.config_manager.save_config()

    def _ensure_workspace(self, project_path: str):
        project_path = os.path.abspath(project_path)
        if project_path in self._workspaces:
            return
        self._workspaces[project_path] = self._WorkspaceState(project_path=project_path)
        if project_path not in self.workspace_paths:
            self.workspace_paths.append(project_path)

    def load_project_cached(self, project_path, force_rescan: bool = False):
        """Load a project, optionally using on-disk cached index to skip a full rescan."""
        if self.scan_in_progress:
            messagebox.showwarning("Scan In Progress", "A project scan is already running. Please wait.", parent=self.app)
            return

        try:
            project_path = os.path.abspath(project_path)
            self._ensure_workspace(project_path)

            self.project_path = project_path
            self.active_workspace_path = project_path

            if not force_rescan:
                cached = self._load_project_index_cache(project_path)
                if cached is not None:
                    self.scanned_tree_data = cached.get("scanned_tree_data", [])
                    self.scanned_file_list_data = cached.get("scanned_file_list_data", [])
                    self.file_count = cached.get("file_count", 0)
                    self.total_size = cached.get("total_size", 0)

                    ws = self._workspaces[project_path]
                    ws.scanned_tree_data = self.scanned_tree_data
                    ws.scanned_file_list_data = self.scanned_file_list_data
                    ws.file_count = self.file_count
                    ws.total_size = self.total_size
                    ws.loaded = True

                    # Update UI elements via ui_builder
                    if self.ui_builder.project_label:
                        self.ui_builder.project_label.config(text=f" {os.path.basename(project_path)}")

                    self._process_scanned_data(self.scanned_tree_data, self.scanned_file_list_data)
                    self.app.update_stats()
                    self.app.set_status(f"Project '{os.path.basename(self.project_path)}' loaded from cache. {self.file_count:,} files, {self.format_size(self.total_size)}.")
                    self.config_manager.save_config()
                    return

            # Update UI elements via ui_builder
            if self.ui_builder.project_label:
                self.ui_builder.project_label.config(text=f" {os.path.basename(project_path)}")
            
            # Clear UI elements via ui_builder
            if self.ui_builder.tree:
                self.ui_builder.tree.delete(*self.ui_builder.tree.get_children())
            if self.ui_builder.file_list:
                self.ui_builder.file_list.delete(*self.ui_builder.file_list.get_children())
            
            self.code_editor_manager.clear_editor()
            self.prompt_generator.clear_prompt_text()
            self.code_editor_manager.current_editor_file = None
            self.code_editor_manager.clear_editor_highlight()
            self.code_editor_manager.update_line_numbers()
            
            self.app.set_status("Loading project, please wait...")
            self.scan_in_progress = True

            self.scan_thread = threading.Thread(target=self._load_project_worker_target, args=(project_path,), daemon=True)
            self.scan_thread.start()
            self._check_scan_status()
            
            self.config_manager.save_config() # Save last opened project path
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load project: {e}", parent=self.app)
            self.app.set_status(f"Error loading project: {e}")
            self.scan_error = e
            self.scan_in_progress = False

    def _load_project_worker_target(self, project_path):
        try:
            tree_nodes_to_insert_raw = []
            file_list_items_to_insert_raw = []
            self.file_count = 0
            self.total_size = 0

            root_name = os.path.basename(project_path)
            tree_nodes_to_insert_raw.append(('', root_name, project_path, True, 0))

            def _recursive_scan(parent_id_placeholder, directory, depth):
                if depth > 10:
                    return
                try:
                    items = os.listdir(directory)
                except (PermissionError, OSError):
                    tree_nodes_to_insert_raw.append((parent_id_placeholder, f" {os.path.basename(directory)} (Access Denied)", directory, True, depth + 1))
                    return

                items.sort()
                for item in items:
                    full_path = os.path.join(directory, item)

                    if item in self.config_manager.excluded_patterns or os.path.basename(full_path) in self.config_manager.excluded_patterns:
                        continue

                    if item.startswith('.') and item not in {'.gitignore', '.env.example', '.dockerignore', 'Dockerfile', 'LICENSE', 'README'}:
                        continue

                    try:
                        if os.path.isdir(full_path):
                            new_id_placeholder = f"{parent_id_placeholder}/{item}"
                            tree_nodes_to_insert_raw.append((parent_id_placeholder, item, full_path, True, depth + 1))
                            _recursive_scan(new_id_placeholder, full_path, depth + 1)
                        else:
                            ext = os.path.splitext(item)[1].lower()
                            if not self.config_manager.included_extensions or ext in self.config_manager.included_extensions or (ext == '' and 'no ext' in self.config_manager.included_extensions):
                                self.file_count += 1
                                try:
                                    file_size = os.path.getsize(full_path)
                                    self.total_size += file_size
                                    size_str = self.format_size(file_size)
                                except (OSError, PermissionError):
                                    size_str = "N/A"

                                tree_nodes_to_insert_raw.append((parent_id_placeholder, item, full_path, False, depth + 1))
                                icon_text = self.get_file_icon(item)
                                file_list_items_to_insert_raw.append((f"{icon_text} {os.path.relpath(full_path, project_path)}", size_str, (ext.upper() if ext else 'FILE'), full_path))
                    except (PermissionError, OSError):
                        continue

            _recursive_scan('', project_path, 0)

            self.scanned_tree_data = tree_nodes_to_insert_raw
            self.scanned_file_list_data = file_list_items_to_insert_raw
            self.scan_error = None
        except Exception as e:
            self.scan_error = e
        finally:
            self.scan_in_progress = False

    def _check_scan_status(self):
        """Polls the status of the worker thread from the main Tkinter thread."""
        if self.scan_in_progress:
            self.app.after(100, self._check_scan_status)
        else:
            if self.scan_error:
                messagebox.showerror("Scan Error", f"Failed to scan project: {self.scan_error}", parent=self.app)
                self.app.set_status(f"Error loading project: {self.scan_error}")
                self.scan_error = None
            else:
                self._process_scanned_data(self.scanned_tree_data, self.scanned_file_list_data)
                self._save_project_index_cache()
                self.app.update_stats() # Update stats after scan is complete
                self.app.set_status(f"Project '{os.path.basename(self.project_path)}' loaded. {self.file_count:,} files, {self.format_size(self.total_size)}.")

                if self.project_path in self._workspaces:
                    ws = self._workspaces[self.project_path]
                    ws.scanned_tree_data = self.scanned_tree_data
                    ws.scanned_file_list_data = self.scanned_file_list_data
                    ws.file_count = self.file_count
                    ws.total_size = self.total_size
                    ws.loaded = True

    def _process_scanned_data(self, tree_nodes_raw_data, file_list_raw_data):
        """Populate GUI elements on the main thread with data from the worker."""
        if self.ui_builder.tree:
            self.ui_builder.tree.delete(*self.ui_builder.tree.get_children())
        if self.ui_builder.file_list:
            self.ui_builder.file_list.delete(*self.ui_builder.file_list.get_children())
        
        id_map = {}
        root_node_id = None

        if tree_nodes_raw_data and self.ui_builder.tree:
            # Correctly get the first element for the root
            root_id_placeholder_raw, root_name, root_path, is_dir_flag, depth = tree_nodes_raw_data[0] 
            
            # Treeview values for folders: [full_path]
            root_node_id = self.ui_builder.tree.insert("", "end", text=f" {root_name}", 
                                           values=[root_path], open=True) # OPEN ROOT NODE BY DEFAULT
            id_map[root_id_placeholder_raw] = root_node_id

            # Process remaining nodes
            for node_data in tree_nodes_raw_data[1:]:
                parent_id_placeholder_raw, name, full_path, is_dir_flag, depth = node_data
                
                parent_node_id = id_map.get(parent_id_placeholder_raw, None)
                if parent_node_id:
                    if is_dir_flag:
                        new_id_placeholder_raw = f"{parent_id_placeholder_raw}/{name}" # Reconstruct placeholder
                        new_node_id = self.ui_builder.tree.insert(parent_node_id, "end", text=f" {name}", 
                                                       values=[full_path], open=False)
                        id_map[new_id_placeholder_raw] = new_node_id
                    else: # It's a file
                        icon = self.get_file_icon(name)
                        # File values: [full_path]
                        self.ui_builder.tree.insert(parent_node_id, "end", text=f"{icon} {name}", 
                                         values=[full_path])
        
        # For file_list, each item_data is (icon_rel_path, size_str, ext_upper, full_path)
        if self.ui_builder.file_list:
            for item_data in file_list_raw_data:
                icon_rel_path, size_str, ext_upper, full_path = item_data
                # Insert into file_list
                self.ui_builder.file_list.insert("", "end", text=icon_rel_path, 
                                    values=[size_str, ext_upper, full_path])
        
        # Select and focus the root node after population for better UX
        if root_node_id and self.ui_builder.tree:
            self.ui_builder.tree.focus(root_node_id)
            self.ui_builder.tree.selection_set(root_node_id)

    def get_file_icon(self, filename):
        """Get icon for file type"""
        ext = os.path.splitext(filename)[1].lower()
        
        # Special handling for files without extensions but recognizable names
        filename_lower = filename.lower()
        if filename_lower == 'license': return ' '
        if filename_lower.startswith('readme'): return ' '
        if filename_lower == 'dockerfile': return ' '
        if filename_lower == '.env': return ' '
        if filename_lower.endswith('.log'): return ' '
        if 'config' in filename_lower or 'conf' in filename_lower: return ' '

        icons = {
            '.py': ' ', '.js': ' ', '.ts': ' ', '.html': ' ', '.css': ' ',
            '.json': ' ', '.md': ' ', '.txt': ' ', '.yml': ' ', '.yaml': ' ',
            '.xml': ' ', '': ' ', '.sql': ' ', '.java': ' ', '.cpp': ' ', '.c': ' ',
            '.h': ' ', '.php': ' ', '.rb': ' ', '.go': ' ', '.rs': ' ',
            '.jsx': ' ', '.tsx': ' ', '.vue': ' ', '.sh': ' ', '.bat': ' ',
            '.ps1': ' ', '.svg': ' ', '.png': ' ', '.jpg': ' ', '.jpeg': ' ',
            '.gif': ' ', '.pdf': ' ', '.zip': ' ', '.rar': ' ', '.tar': ' ',
            '.gz': ' ', '.lock': ' ', '.npmignore': ' ', '.gitignore': ' ',
            '.editorconfig': ' ', '.prettierrc': ' ', '.eslintrc': ' ',
            '.tsconfig': ' ', '.babelrc': ' ', '.gitattributes': ' ',
            '.env.example': ' ', '.dockerignore': ' ', 'makefile': ' ' # Dockerfile is handled above as special name
        }
        return icons.get(ext, ' ')

    def format_size(self, size):
        """Format file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}TB"

    def on_search_change(self, *args):
        """Debounced search to avoid rebuilding list every keystroke."""
        if self.search_job:
            try:
                self.app.after_cancel(self.search_job)
            except Exception:
                pass
        self.search_job = self.app.after(200, self._do_search)

    def _do_search(self):
        if not self.ui_builder.file_list:
            return

        search_term = self.ui_builder.search_var.get().lower().strip()

        for item in self.ui_builder.file_list.get_children():
            self.ui_builder.file_list.delete(item)

        if not self.project_path:
            return

        try:
            if not search_term:
                for item_data in self.scanned_file_list_data:
                    icon_rel_path, size_str, ext_upper, full_path = item_data
                    self.ui_builder.file_list.insert("", "end", text=icon_rel_path,
                        values=[size_str, ext_upper, full_path])
                return

            temp_filtered = []
            for item_data in self.scanned_file_list_data:
                icon_rel_path, size_str, ext_upper, full_path = item_data
                if search_term in icon_rel_path.lower():
                    temp_filtered.append(item_data)

            for item_data in temp_filtered:
                icon_rel_path, size_str, ext_upper, full_path = item_data
                self.ui_builder.file_list.insert("", "end", text=icon_rel_path,
                    values=[size_str, ext_upper, full_path])

        except Exception as e:
            print(f"Search error: {e}")
            self.app.set_status(f"Error during search: {e}")

    def on_tree_select(self, event):
        """Handle tree selection"""
        if not self.ui_builder.tree: return
        try:
            selection = self.ui_builder.tree.selection()
            if selection:
                item_id = selection[0] 
                values = self.ui_builder.tree.item(item_id, "values")
                
                if values and len(values) > 0:
                    file_path = values[0] 

                    if os.path.isfile(file_path):
                        self.code_editor_manager.load_file_into_editor(file_path)
                        self.prompt_generator.generate_prompt([file_path]) # No post-copy action needed here, just generate.
                    elif os.path.isdir(file_path):
                        self.code_editor_manager.clear_editor()
                        self.code_editor_manager.current_editor_file = None
                        self.code_editor_manager.clear_editor_highlight()
                        self.code_editor_manager.update_line_numbers()
                        self.prompt_generator.clear_prompt_text()
                        self.app.set_status(f"Selected folder: {os.path.basename(file_path)}")
                else:
                    self.app.set_status("Selected item has no associated path.")
        except Exception as e:
            print(f"Tree selection error: {e}")
            self.app.set_status(f"Error selecting tree item: {e}")

    def on_list_select(self, event):
        """Handle list selection"""
        if not self.ui_builder.file_list: return
        try:
            selection = self.ui_builder.file_list.selection()
            if selection:
                item_id = selection[0] 
                values = self.ui_builder.file_list.item(item_id, "values")
                
                if values and len(values) >= 3:
                    file_path = values[2]
                    if os.path.isfile(file_path):
                        self.code_editor_manager.load_file_into_editor(file_path)
                        self.prompt_generator.generate_prompt([file_path]) # No post-copy action needed here, just generate.
                else:
                    self.app.set_status("Selected list item has incomplete data.")
        except Exception as e:
            print(f"List selection error: {e}")
            self.app.set_status(f"Error selecting list item: {e}")

    def open_selected_in_editor(self):
        """Load the currently selected file into the code editor."""
        selection = None
        if self.ui_builder.tree:
            selection = self.ui_builder.tree.selection()
        if not selection and self.ui_builder.file_list:
            selection = self.ui_builder.file_list.selection()

        if not selection:
            messagebox.showwarning("No Selection", "Please select a file to open in the editor.", parent=self.app)
            return

        item_id = selection[0] 
        values = None
        is_tree_item = False
        if self.ui_builder.tree and self.ui_builder.tree.exists(item_id):
            is_tree_item = True

        if is_tree_item:
            values = self.ui_builder.tree.item(item_id, "values")
        elif self.ui_builder.file_list and self.ui_builder.file_list.exists(item_id):
            values = self.ui_builder.file_list.item(item_id, "values")
        else:
            self.app.set_status("Selected item does not exist in tree or list.")
            return

        if not values:
            self.app.set_status("Selected item has no associated data.")
            return

        file_path = None

        if is_tree_item:
            file_path = values[0] 
        else: 
            file_path = values[2] 
        
        if file_path and os.path.isfile(file_path):
            self.code_editor_manager.load_file_into_editor(file_path)
        elif file_path and os.path.isdir(file_path):
            self.code_editor_manager.clear_editor()
            self.code_editor_manager.current_editor_file = None
            self.code_editor_manager.clear_editor_highlight()
            self.code_editor_manager.update_line_numbers()
            self.app.set_status(f"Selected folder: {os.path.basename(file_path)}")
        else:
            messagebox.showwarning("Invalid Selection", "Selected item is not a valid file path.", parent=self.app)

    def get_folder_files(self, folder_path):
        """Get eligible files in a given folder (recursively) applying current filters."""
        files = []
        try:
            # Iterate through already scanned and filtered files
            for item_data in self.scanned_file_list_data:
                full_file_path = item_data[3] 
                # Check if the file's path starts with the folder_path (and is not the folder_path itself)
                if full_file_path.startswith(folder_path + os.sep) or full_file_path == folder_path:
                    files.append(full_file_path)
        except Exception as e:
            print(f"Error getting folder files for '{folder_path}': {e}")
            self.app.set_status(f"Error getting folder files: {e}")
        return files

    def get_all_files(self):
        """Get all eligible project file paths from scanned data."""
        if self.project_path:
            return [item_data[3] for item_data in self.scanned_file_list_data] 
        return []

    def reload_project(self):
        """Reload current project."""
        if self.project_path:
            self.load_project_cached(self.project_path, force_rescan=True)
        else:
            self.app.set_status("No project loaded to reload.")

    def _get_project_index_cache_path(self, project_path: str) -> str:
        os.makedirs(self.index_cache_dir, exist_ok=True)
        key = hashlib.sha1(project_path.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return os.path.join(self.index_cache_dir, f"index_{key}.json")

    def _load_project_index_cache(self, project_path: str):
        try:
            cache_path = self._get_project_index_cache_path(project_path)
            if not os.path.exists(cache_path):
                return None
            with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)

            if data.get("project_path") != project_path:
                return None

            if set(data.get("excluded_patterns", [])) != set(self.config_manager.excluded_patterns):
                return None
            if set(data.get("included_extensions", [])) != set(self.config_manager.included_extensions):
                return None

            scanned_tree_data = data.get("scanned_tree_data")
            scanned_file_list_data = data.get("scanned_file_list_data")
            if not isinstance(scanned_tree_data, list) or not isinstance(scanned_file_list_data, list):
                return None

            return data
        except Exception:
            return None

    def _save_project_index_cache(self):
        try:
            if not self.project_path:
                return

            cache_path = self._get_project_index_cache_path(self.project_path)
            payload = {
                "project_path": self.project_path,
                "excluded_patterns": list(self.config_manager.excluded_patterns),
                "included_extensions": list(self.config_manager.included_extensions),
                "file_count": self.file_count,
                "total_size": self.total_size,
                "saved_at": time.time(),
                "scanned_tree_data": self.scanned_tree_data,
                "scanned_file_list_data": self.scanned_file_list_data,
            }

            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            return

    def show_project_stats(self):
        """Show project statistics."""
        try:
            if not self.project_path:
                messagebox.showwarning("No Project", "Please load a project first.", parent=self.app)
                return
            
            stats = f"📊 PROJECT STATISTICS\n\n"
            stats += f"📁 Project: {os.path.basename(self.project_path)}\n"
            stats += f"📄 Total Eligible Files: {self.file_count:,}\n"
            stats += f"📏 Total Eligible Size: {self.format_size(self.total_size)}\n\n"
            
            file_types = {}
            for item_data in self.scanned_file_list_data:
                full_path = item_data[3]
                ext = os.path.splitext(full_path)[1].lower() or '' 
                file_types[ext] = file_types.get(ext, 0) + 1
            
            stats += "🔧 FILE TYPES (Top 10):\n"
            for ext, count in sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:10]:
                stats += f"  {ext if ext else '(No Ext)'}: {count} files\n"
            
            messagebox.showinfo("Project Statistics", stats, parent=self.app)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to show stats: {e}", parent=self.app)
            self.app.set_status(f"Error showing stats: {e}")