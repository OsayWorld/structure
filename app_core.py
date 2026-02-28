# app_core.py
import logging
import os
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog
from datetime import datetime
import threading
import time
import io
import re

# Optional imports with fallbacks
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False
    print("Warning: pyperclip not available. Clipboard features disabled.")

try:
    from pygments import lex
    from pygments.lexers import get_lexer_for_filename, guess_lexer_for_filename, TextLexer
    from pygments.token import Token
    SYNTAX_HIGHLIGHTING = True
except ImportError:
    SYNTAX_HIGHLIGHTING = False
    print("Warning: pygments not available. Syntax highlighting disabled.")

# Import ttkbootstrap
import ttkbootstrap as tkb
from ttkbootstrap import ttk # Use ttk from ttkbootstrap
from ttkbootstrap.constants import * # Import all constants for convenience (e.g., PRIMARY, SUCCESS)

# Import refactored modules - these need to exist alongside app_core
# We'll assume these files are in the same directory as app_core.py
from config_manager import ConfigManager
from ui_builder import UIBuilder
from project_scanner import ProjectScanner
from code_editor_manager import CodeEditorManager
from prompt_generator import PromptGenerator

class OsayStudioApp(tkb.Window):
    def __init__(self):
        super().__init__(themename="darkly")

        def _report_callback_exception(exc, val, tb):
            logging.getLogger(__name__).exception("Tkinter callback exception", exc_info=(exc, val, tb))
            try:
                super(OsayStudioApp, self).report_callback_exception(exc, val, tb)
            except Exception:
                pass

        self.report_callback_exception = _report_callback_exception
        self.title("🌿 Osay Studio Structure Prompt")
        self.geometry("1400x800")
        self.minimum_width = 1000
        self.minimum_height = 600
        self.minsize(self.minimum_width, self.minimum_height)

        self._apply_osay_studio_theme() # Apply theme early

        # Initialize core components
        self.config_manager = ConfigManager(self)
        self.ui_builder = UIBuilder(self)
        self.project_scanner = ProjectScanner(self, self.config_manager)
        self.code_editor_manager = CodeEditorManager(self, self.config_manager)
        self.prompt_generator = PromptGenerator(self, self.config_manager, self.project_scanner, CLIPBOARD_AVAILABLE, SYNTAX_HIGHLIGHTING)

        # Set references in components that need to interact with others
        self.ui_builder.set_dependencies(self.config_manager, self.project_scanner, self.code_editor_manager, self.prompt_generator)
        self.project_scanner.set_dependencies(self.code_editor_manager, self.prompt_generator)
        self.prompt_generator.set_dependencies(self.ui_builder) # Added dependency for prompt_generator to access ui_builder's elements

        # UI setup order is crucial:
        self.ui_builder.create_menu_bar()
        self.ui_builder.create_toolbar()
        
        # Main container for notebook, with consistent padding
        self.main_container = ttk.Frame(self, padding=10)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.explorer_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.explorer_frame, text="📁 Explorer")
        
        self.settings_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.settings_frame, text="⚙️ Settings")
        
        # Pass the frame objects to the UIBuilder to set up their contents
        self.ui_builder.setup_explorer_tab(self.explorer_frame)
        self.ui_builder.setup_settings_tab(self.settings_frame)
        self.ui_builder.setup_status_bar()
        
        self.ui_builder.setup_shortcuts()
        
        self.project_scanner.initialize_project() # Load last project or prompt for new one

    def _apply_osay_studio_theme(self):
        """Applies a custom dark green theme using ttkbootstrap's Style."""
        style = tkb.Style()
        
        # Base theme for general dark elements
        style.theme_use("darkly") 

        # Define custom dark green palette
        self.osay_green_primary = "#1a5d3f"  # Dark Forest Green
        self.osay_green_secondary = "#2a754e" # Slightly lighter green for secondary elements
        self.osay_green_success = "#32cd32"  # Lime Green for success/toggle
        self.osay_green_info = "#66bb6a"     # Another shade for info buttons
        self.osay_red_danger = "#dc3545"     # Standard red for danger
        self.osay_yellow_warning = "#ffc107" # Standard yellow for warning

        # Override ttkbootstrap's default colors
        style.colors.primary = self.osay_green_primary
        style.colors.secondary = self.osay_green_secondary
        style.colors.success = self.osay_green_success
        style.colors.info = self.osay_green_info
        style.colors.danger = self.osay_red_danger
        style.colors.warning = self.osay_yellow_warning
        
        # Adjust some specific widget styles for better contrast/look
        style.configure("TLabel", foreground=style.colors.light)
        style.configure("TButton", font=("Segoe UI", 9, "bold"))
        style.configure("TCheckbutton", foreground=style.colors.light)
        style.configure("TCombobox", fieldbackground=style.colors.inputbg, foreground=style.colors.inputfg)

        # Style for header labels (e.g., "Project Structure")
        style.configure("Inverse.TLabel", 
                        background=style.colors.primary, 
                        foreground=style.colors.light,
                        font=("Segoe UI", 10, "bold"),
                        padding=[10, 5])

        # Style for status bar label
        style.configure("Status.TLabel", 
                        background=style.colors.secondary,
                        foreground=style.colors.light,
                        padding=[5, 2])
                        
    def set_status(self, text):
        """Update status bar text."""
        try:
            if hasattr(self.ui_builder, 'status_label') and self.ui_builder.status_label:
                self.ui_builder.status_label.config(text=text)
                if self.winfo_exists():
                    self.update_idletasks()
        except Exception as e:
            print(f"Status update error: {e}")

    def update_stats(self):
        """Update statistics display."""
        try:
            if hasattr(self.project_scanner, 'project_path') and self.ui_builder.stats_label:
                self.ui_builder.stats_label.config(text=f"📄 {self.project_scanner.file_count:,} files • 📏 {self.project_scanner.format_size(self.project_scanner.total_size)}")
        except Exception as e:
            print(f"Stats update error: {e}")

    def quit(self):
        """Handle application exit."""
        self.config_manager.save_config()
        super().quit()