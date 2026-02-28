# config_manager.py
import os
import json
import tkinter as tk
from tkinter import messagebox

class ConfigManager:
    def __init__(self, app_instance):
        self.app = app_instance
        self.config_file = "explorer_config.json"
        
        # Default values (will be loaded from config or reset)
        self.last_project_path = ''
        self.workspace_paths = []
        self.active_workspace_path = ''
        self.theme = 'darkly'
        self.font_size = 11
        self.max_prompt_file_length = 10000
        self.excluded_patterns = {'.git', '__pycache__', 'node_modules', '.vscode', '.idea', 'venv', 'env', '.next', 'dist', 'build'}
        self.included_extensions = {'.py', '.js', '.ts', '.html', '.css', '.json', '.md', '.txt', '.yml', '.yaml', '.xml', '.sql', '.java', '.cpp', '.c', '.h', '.php', '.rb', '.go', '.rs', '.swift', '.jsx', '.tsx', '.vue'}

        self.load_config()

    def load_config(self):
        """Load user preferences with error handling"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.last_project_path = config.get('last_project_path', '')
                    self.workspace_paths = config.get('workspace_paths', [])
                    self.active_workspace_path = config.get('active_workspace_path', '')
                    self.theme = config.get('theme', 'darkly')
                    self.font_size = config.get('font_size', 11)
                    self.max_prompt_file_length = config.get('max_prompt_file_length', 10000)
                    
                    loaded_excluded = config.get('excluded_patterns')
                    if loaded_excluded is not None:
                        self.excluded_patterns = set(loaded_excluded)
                    loaded_included = config.get('included_extensions')
                    if loaded_included is not None:
                        self.included_extensions = set(loaded_included)
            else:
                self.reset_config_to_defaults() # Load defaults if no config file
        except Exception as e:
            print(f"Error loading config: {e}")
            self.reset_config_to_defaults() # Reset if error during load

    def reset_config_to_defaults(self):
        """Reset to default configuration values internally."""
        self.last_project_path = ''
        self.workspace_paths = []
        self.active_workspace_path = ''
        self.theme = 'darkly'
        self.font_size = 11
        self.max_prompt_file_length = 10000
        self.excluded_patterns = {'.git', '__pycache__', 'node_modules', '.vscode', '.idea', 'venv', 'env', '.next', 'dist', 'build'}
        self.included_extensions = {'.py', '.js', '.ts', '.html', '.css', '.json', '.md', '.txt', '.yml', '.yaml', '.xml', '.sql', '.java', '.cpp', '.c', '.h', '.php', '.rb', '.go', '.rs', '.swift', '.jsx', '.tsx', '.vue'}

    def save_config(self):
        """Save current configuration to file."""
        try:
            workspace_paths = []
            active_workspace_path = ''
            if hasattr(self.app, 'project_scanner') and hasattr(self.app.project_scanner, 'get_workspace_paths'):
                workspace_paths = self.app.project_scanner.get_workspace_paths()
            if hasattr(self.app, 'project_scanner') and hasattr(self.app.project_scanner, 'project_path'):
                active_workspace_path = getattr(self.app.project_scanner, 'project_path', '') or ''

            config = {
                'last_project_path': active_workspace_path, # Backward compatibility
                'workspace_paths': workspace_paths,
                'active_workspace_path': active_workspace_path,
                'theme': self.theme,
                'font_size': self.font_size,
                'max_prompt_file_length': self.max_prompt_file_length,
                'excluded_patterns': list(self.excluded_patterns),
                'included_extensions': list(self.included_extensions)
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    # These methods are called from UIBuilder's context, so they will interact with UI elements
    def save_settings(self, excluded_entry, extensions_entry, max_length_var):
        """Save settings from the settings tab."""
        try:
            excluded_text = excluded_entry.get('1.0', tk.END).strip()
            self.excluded_patterns = set(p.strip() for p in excluded_text.split(',') if p.strip())
            
            extensions_text = extensions_entry.get('1.0', tk.END).strip()
            self.included_extensions = set(e.strip() for e in extensions_text.split(',') if e.strip())
            
            # Update max_prompt_file_length from the UI variable
            try:
                val = max_length_var.get()
                if isinstance(val, int) and val >= 0:
                    self.max_prompt_file_length = val
            except tk.TclError:
                pass # Ignore invalid entries during typing

            self.save_config()
            messagebox.showinfo("Settings Saved", "✅ Your filter settings have been saved successfully!", parent=self.app)
            
            if hasattr(self.app.project_scanner, 'project_path') and self.app.project_scanner.project_path:
                self.app.project_scanner.reload_project() # Reload project to apply new filters
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}", parent=self.app)

    def reset_settings(self, excluded_entry, extensions_entry, max_length_var, font_label):
        """Reset to default settings."""
        try:
            self.reset_config_to_defaults()
            
            excluded_entry.delete('1.0', tk.END)
            excluded_entry.insert('1.0', ', '.join(self.excluded_patterns))
            
            extensions_entry.delete('1.0', tk.END)
            extensions_entry.insert('1.0', ', '.join(self.included_extensions))
            
            max_length_var.set(self.max_prompt_file_length)
            
            self.app.code_editor_manager.set_font_size(self.font_size) # Update editor font
            if font_label: # Check if the label exists
                font_label.config(text=str(self.font_size)) # Update font label
            
            self.save_config()
            
            messagebox.showinfo("Settings Reset", "🔄 Settings have been reset to defaults!", parent=self.app)
            
            if hasattr(self.app.project_scanner, 'project_path') and self.app.project_scanner.project_path:
                self.app.project_scanner.reload_project() # Reload project to apply default filters
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset settings: {e}", parent=self.app)

    def on_max_length_change(self, *args):
        """Update max_prompt_file_length when the entry changes."""
        try:
            # Safely access ui_builder and its variable
            if hasattr(self.app, 'ui_builder') and self.app.ui_builder.max_prompt_file_length_var:
                val = self.app.ui_builder.max_prompt_file_length_var.get()
                if isinstance(val, int) and val >= 0:
                    self.max_prompt_file_length = val
                    self.save_config()
        except tk.TclError:
            pass # Ignore invalid entries during typing