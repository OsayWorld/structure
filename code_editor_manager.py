# code_editor_manager.py
import os
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog
import threading
import time

from lru_cache import LRUCache

# Pygments imports (already handled in app_core, assume available here)
try:
    from pygments import lex
    from pygments.lexers import get_lexer_for_filename, guess_lexer_for_filename, TextLexer
    from pygments.token import Token
    SYNTAX_HIGHLIGHTING = True
except ImportError:
    SYNTAX_HIGHLIGHTING = False

class CodeEditorManager:
    def __init__(self, app_instance, config_manager):
        self.app = app_instance
        self.config_manager = config_manager

        self.code_editor = None
        self.line_numbers = None

        self.current_editor_file = None
        self.highlight_update_job = None
        self.line_numbers_update_job = None
        self.editor_loading_thread = None
        self.editor_load_timestamp = None

        self.file_cache = LRUCache(max_items=20)

    def set_editor_widgets(self, code_editor, line_numbers):
        """Set the actual Tkinter widgets for the editor and line numbers."""
        self.code_editor = code_editor
        self.line_numbers = line_numbers

    def _get_pygments_lexer(self, file_path, content_sample=""):
        """
        Get Pygments lexer for a given file path, with a fallback to guess lexer
        if initial filename-based detection fails.
        """
        if not SYNTAX_HIGHLIGHTING:
            return TextLexer()

        try:
            return get_lexer_for_filename(file_path, stripall=True)
        except Exception:
            try:
                if content_sample:
                    return guess_lexer_for_filename(file_path, content_sample, stripall=True)
                return TextLexer()
            except Exception:
                return TextLexer()

    def setup_pygments_tags(self):
        """Configure Tkinter text tags based on Pygments token types."""
        if not SYNTAX_HIGHLIGHTING or not self.code_editor:
            return

        self.code_editor.tag_configure('default', foreground="#abb2bf")
        self.code_editor.tag_configure('highlight_line', background="#3f4b5d")

        token_colors = {
            Token.Keyword: "#c678dd", Token.Keyword.Constant: "#c678dd", Token.Keyword.Declaration: "#c678dd",
            Token.Keyword.Namespace: "#c678dd", Token.Keyword.Pseudo: "#c678dd", Token.Keyword.Reserved: "#c678dd",
            Token.Keyword.Type: "#c678dd", Token.Name.Builtin: "#e5c07b", Token.Name.Builtin.Pseudo: "#e5c07b",
            Token.Name.Function: "#61afef", Token.Name.Variable: "#abb2bf", Token.Name.Constant: "#d19a66",
            Token.Name.Decorator: "#e5c07b", Token.String: "#98c379", Token.String.Char: "#98c379",
            Token.String.Doc: "#98c379", Token.String.Double: "#98c379", Token.String.Escape: "#98c379",
            Token.String.Heredoc: "#98c379", Token.String.Interpol: "#98c379", Token.String.Other: "#98c379",
            Token.String.Regex: "#98c379", Token.String.Single: "#98c379", Token.String.Symbol: "#98c379",
            Token.Number: "#d19a66", Token.Operator: "#56b6c2", Token.Punctuation: "#abb2bf",
            Token.Comment: "#7f848e", Token.Comment.Multiline: "#7f848e", Token.Comment.Single: "#7f848e",
            Token.Comment.Preproc: "#7f848e", Token.Literal: "#d19a66", Token.Literal.Date: "#d19a66",
            Token.Generic.Deleted: "#e06c75", Token.Generic.Error: "#e06c75", Token.Generic.Heading: "#61afef",
            Token.Generic.Inserted: "#98c379", Token.Generic.Output: "#abb2bf", Token.Generic.Prompt: "#61afef",
            Token.Generic.Strong: "#e5c07b", Token.Generic.Subheading: "#61afef", Token.Generic.Emph: "#c678dd",
            Token.Generic.Traceback: "#e06c75", Token.Error: "#e06c75", Token.Name.Class: "#e5c07b",
            Token.Name.Exception: "#e06c75", Token.Name.Label: "#61afef", Token.Name.Tag: "#e06c75",
            Token.Operator.Word: "#c678dd", Token.Text: "#abb2bf",
        }

        for token_type, color_hex in token_colors.items():
            tag_name = str(token_type).replace('.', '_')
            self.code_editor.tag_configure(tag_name, foreground=color_hex)
        
        self.code_editor.tag_configure('unmapped', foreground="#abb2bf")

    def apply_syntax_highlighting_in_memory(self, content, file_path=""):
        """
        Applies Pygments lexing and returns a list of (tag_name, start_offset, end_offset) tuples.
        This runs in the worker thread for pre-loading or on the main thread for typing.
        """
        if not SYNTAX_HIGHLIGHTING or not content:
            return []

        lexer = self._get_pygments_lexer(file_path, content_sample=content[:1024])
        tag_data = []
        try:
            offset = 0
            for token_type, value in lex(content, lexer):
                tag_name = str(token_type).replace('.', '_')
                tag_data.append((tag_name, offset, offset + len(value)))
                offset += len(value)
        except Exception as e:
            print(f"Error lexing for syntax highlighting: {e}")
            tag_data.append(('default', 0, len(content)))
        return tag_data

    def _apply_tags_to_editor(self, tag_data):
        """Apply pre-calculated tags to the code_editor on the main thread."""
        if not self.code_editor: return

        self.code_editor.edit_modified(False)
        
        for tag_name in self.code_editor.tag_names():
            if tag_name.startswith('Token_') or tag_name == 'default' or tag_name == 'unmapped':
                self.code_editor.tag_remove(tag_name, '1.0', tk.END)

        for tag_name, start_offset, end_offset in tag_data:
            if tag_name not in self.code_editor.tag_names():
                # Fallback to default foreground if tag isn't configured for some reason
                self.code_editor.tag_configure(tag_name, foreground=self.code_editor.cget('fg'))
            
            start_index = f"1.0 + {start_offset}c"
            end_index = f"1.0 + {end_offset}c"
            self.code_editor.tag_add(tag_name, start_index, end_index)
        
        self.code_editor.edit_modified(True)

    def update_line_numbers(self, line_numbers_string=None):
        """
        Update the line numbers widget. Debounced for calculated updates,
        or instant if a pre-calculated string is provided.
        Always cancels any pending job before proceeding.
        """
        if not self.line_numbers or not self.code_editor: return

        if self.line_numbers_update_job:
            self.app.after_cancel(self.line_numbers_update_job)
            self.line_numbers_update_job = None

        if line_numbers_string:
            self.__do_update_line_numbers_instant(line_numbers_string)
        else:
            self.line_numbers_update_job = self.app.after(50, self.__do_update_line_numbers_calculate)

    def __do_update_line_numbers_instant(self, line_string):
        """Instant update of line numbers with a pre-calculated string."""
        if not self.line_numbers or not self.code_editor: return
        self.line_numbers.config(state=tk.NORMAL)
        self.line_numbers.delete('1.0', tk.END)
        self.line_numbers.insert('1.0', line_string)
        self.line_numbers.config(state=tk.DISABLED)
        self.line_numbers.yview_moveto(self.code_editor.yview()[0]) 

    def __do_update_line_numbers_calculate(self):
        """Actual line number calculation and update logic."""
        if not self.line_numbers or not self.code_editor: return
        # Mark the job as completed (clear the ID) as it's about to execute
        if self.line_numbers_update_job:
            self.line_numbers_update_job = None

        self.line_numbers.config(state=tk.NORMAL)
        self.line_numbers.delete('1.0', tk.END)

        content = self.code_editor.get('1.0', tk.END + '-1c')
        num_lines_in_editor = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
        if not content.strip() and num_lines_in_editor == 0: # Ensure at least one line for empty files
            num_lines_in_editor = 1

        line_string = ""
        for i in range(1, num_lines_in_editor + 1):
            line_string += f"{i}\n"
        
        self.line_numbers.insert('1.0', line_string)
        self.line_numbers.config(state=tk.DISABLED)

        self.line_numbers.yview_moveto(self.code_editor.yview()[0])
        
    def on_shared_yview(self, *args):
        """Unified scroll handler for both text widgets, called by the scrollbar."""
        if not self.code_editor or not self.line_numbers: return
        self.code_editor.yview(*args)
        self.line_numbers.yview(*args)
        self.update_line_numbers() # Re-calculate line numbers if view changed and content is modified
        
    def on_editor_content_modified(self, event=None):
        """Handle content changes in the code editor for highlighting and line numbers."""
        if not self.code_editor: return
        if self.code_editor.edit_modified():
            if self.highlight_update_job:
                self.app.after_cancel(self.highlight_update_job)
            self.highlight_update_job = self.app.after(150, self._do_highlight_and_lines_on_main_thread)
            
            self.code_editor.edit_modified(False) # Reset modified flag to accurately detect next change
            self.update_line_numbers() # Call _update_line_numbers for content changes, it handles debouncing internally.

    def on_editor_mouse_wheel(self, event):
        """Handle mouse wheel scrolling to sync both widgets and update line numbers."""
        if not self.code_editor or not self.line_numbers: return
        self.code_editor.yview_scroll(-1 * (event.delta // 120), "units")
        self.line_numbers.yview_scroll(-1 * (event.delta // 120), "units")
        self.update_line_numbers()
        return "break" # Prevents default Tkinter mouse wheel behavior

    def _do_highlight_and_lines_on_main_thread(self):
        """Performs the actual highlighting on the main thread for typing events."""
        if not self.code_editor: return
        content = self.code_editor.get('1.0', tk.END + '-1c')
        tag_data = self.apply_syntax_highlighting_in_memory(content, self.current_editor_file)
        self._apply_tags_to_editor(tag_data)
        self.highlight_update_job = None

    def load_file_into_editor(self, file_path, preloaded_content=None, preloaded_tag_data=None, preloaded_line_numbers_string=None):
        """
        Loads content into the code editor. Uses pre-loaded data if available,
        otherwise starts a new thread for heavy processing.
        """
        if not self.code_editor or not self.line_numbers: return

        self.editor_load_timestamp = time.time() # Timestamp for the current load request
        current_request_timestamp = self.editor_load_timestamp

        self.clear_editor()
        self.clear_editor_highlight()
        self.current_editor_file = file_path
        
        cached = self.file_cache.get(file_path)
        if cached is not None:
            content, tag_data, line_numbers_string = cached
            self.clear_editor()
            self.clear_editor_highlight()
            self.code_editor.insert('1.0', content)
            if tag_data:
                self._apply_tags_to_editor(tag_data)
            self.update_line_numbers(line_numbers_string)
            self.app.set_status(f"Editing: {os.path.basename(file_path)} (Cached)")
            self.code_editor.edit_modified(False)
            return
        
        if preloaded_content is not None and preloaded_tag_data is not None and preloaded_line_numbers_string is not None:
            # Apply pre-loaded data instantly
            self.code_editor.insert('1.0', preloaded_content)
            self._apply_tags_to_editor(preloaded_tag_data)
            self.update_line_numbers(preloaded_line_numbers_string)
            self.app.set_status(f"Editing: {os.path.basename(file_path)} (Preloaded)")
            self.code_editor.edit_modified(False)
        else:
            # File not pre-loaded or too large, start worker thread
            self.app.set_status(f"Loading '{os.path.basename(file_path)}'...")
            self.code_editor.insert('1.0', "Loading file and applying syntax highlighting...")
            # Temporarily apply a default tag to the "Loading..." text
            self.code_editor.tag_remove('default', '1.0', tk.END)
            self.code_editor.tag_add('default', '1.0', tk.END)
            self.update_line_numbers() # Display initial line numbers for "Loading" text
            
            # If an old loading thread is still active, it will be ignored by the timestamp check
            self.editor_loading_thread = threading.Thread(
                target=self._load_file_for_editor_worker, 
                args=(file_path, current_request_timestamp), 
                daemon=True
            )
            self.editor_loading_thread.start()

    def _load_file_for_editor_worker(self, file_path, request_timestamp):
        """Worker thread to load file, apply highlighting in memory, and generate line numbers."""
        content = ""
        tag_data = []
        line_numbers_string = ""
        error_info = None

        try:
            if not os.path.exists(file_path):
                error_info = f"⚠️ File does not exist: {os.path.basename(file_path)}"
            elif os.path.getsize(file_path) > 5 * 1024 * 1024: # Limit for editor display (e.g., 5MB)
                error_info = f"⚠️ File too large to edit: {os.path.basename(file_path)} (>5MB)"
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if SYNTAX_HIGHLIGHTING:
                    tag_data = self.apply_syntax_highlighting_in_memory(content, file_path)
                
                num_lines_in_editor = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
                if not content.strip() and num_lines_in_editor == 0:
                    num_lines_in_editor = 1

                line_numbers_string = "\n".join(map(str, range(1, num_lines_in_editor + 1))) + "\n"

        except Exception as e:
            error_info = f"⚠️ Error loading file: {e}"
        
        self.app.after(0, self._apply_loaded_file_data, 
                   file_path, content, tag_data, line_numbers_string, error_info, request_timestamp)

    def _apply_loaded_file_data(self, requested_file_path, content, tag_data, line_numbers_string, error_info, request_timestamp):
        """Applies processed file data to the editor on the main Tkinter thread."""
        if not self.code_editor or not self.line_numbers: return

        # Check if this is still the most recent request
        if request_timestamp != self.editor_load_timestamp:
            self.app.set_status(f"Skipping outdated load for '{os.path.basename(requested_file_path)}'.")
            return

        self.clear_editor()
        self.clear_editor_highlight()
        
        if error_info:
            self.code_editor.insert('1.0', error_info)
            self.app.set_status(f"Editor: {os.path.basename(requested_file_path)} (error)")
            # Ensure default styling if there's an error message
            for tag_name in self.code_editor.tag_names():
                if tag_name.startswith('Token_') or tag_name == 'default' or tag_name == 'unmapped': 
                    self.code_editor.tag_remove(tag_name, '1.0', tk.END)
            self.code_editor.tag_add('default', '1.0', tk.END)
            self.update_line_numbers()
        else:
            self.code_editor.insert('1.0', content)
            self._apply_tags_to_editor(tag_data)
            self.update_line_numbers(line_numbers_string)
            self.app.set_status(f"Editing: {os.path.basename(requested_file_path)}")
 
            self.file_cache.set(requested_file_path, (content, tag_data, line_numbers_string))
            self.code_editor.edit_modified(False) # Reset modified flag after loading

    def save_current_editor_file(self):
        """Save the current content of the code editor back to its file."""
        if not self.current_editor_file or not os.path.isfile(self.current_editor_file):
            messagebox.showwarning("No File", "No file is open in the editor to save.", parent=self.app)
            return

        try:
            content = self.code_editor.get('1.0', tk.END + '-1c')
            with open(self.current_editor_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.app.set_status(f"💾 Changes saved to {os.path.basename(self.current_editor_file)}!")
            messagebox.showinfo("File Saved", f"✅ Successfully saved: {os.path.basename(self.current_editor_file)}", parent=self.app)
            self.code_editor.edit_modified(False) # Reset modified flag after saving
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}", parent=self.app)
            self.app.set_status(f"Error saving {os.path.basename(self.current_editor_file)}")

    def set_font_size(self, new_size):
        """Sets the font size for editor, line numbers, and prompt text."""
        # This method is called by ConfigManager when settings change
        if self.code_editor:
            self.code_editor.config(font=("Consolas", new_size))
        if self.line_numbers:
            self.line_numbers.config(font=("Consolas", new_size))
        if hasattr(self.app.ui_builder, 'prompt_text') and self.app.ui_builder.prompt_text:
            self.app.ui_builder.prompt_text.config(font=("Consolas", new_size))

    def change_font_size(self, delta):
        """Change editor and prompt font size."""
        # Directly update config_manager's font_size and then call set_font_size
        new_size = max(8, min(24, self.config_manager.font_size + delta))
        if new_size != self.config_manager.font_size:
            self.config_manager.font_size = new_size
            self.set_font_size(self.config_manager.font_size)
            
            if hasattr(self.app.ui_builder, 'font_label') and self.app.ui_builder.font_label:
                self.app.ui_builder.font_label.config(text=str(self.config_manager.font_size))
            self.config_manager.save_config()

    def go_to_line_dialog(self):
        """Open a dialog for the user to enter a line number."""
        if not self.current_editor_file or not os.path.isfile(self.current_editor_file):
            messagebox.showwarning("No File Open", "Please open a file in the editor first to use 'Go to Line'.", parent=self.app)
            return
        
        line_number_str = simpledialog.askstring("Go to Line", "Enter line number:", parent=self.app)
        if line_number_str:
            try:
                line_number = int(line_number_str)
                self._goto_line(line_number)
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter a valid integer for the line number.", parent=self.app)

    def _goto_line(self, line_number):
        """Scrolls the editor to the specified line number and highlights it."""
        if not self.current_editor_file or not self.code_editor or not self.line_numbers:
            return

        self.code_editor.tag_remove('highlight_line', '1.0', tk.END) # Clear previous highlight

        try:
            # The number of lines is (index of end-1c).line_part
            num_lines = int(self.code_editor.index('end-1c').split('.')[0])
            if 1 <= line_number <= num_lines:
                # Scroll to the line
                self.code_editor.see(f"{line_number}.0")
                self.line_numbers.see(f"{line_number}.0")

                # Place cursor at the beginning of the line
                self.code_editor.mark_set("insert", f"{line_number}.0")
                self.code_editor.focus_set()

                # Highlight the line
                self.code_editor.tag_add('highlight_line', f"{line_number}.0", f"{line_number}.end")
                self.app.set_status(f"Moved to line {line_number}.")
            else:
                messagebox.showwarning("Invalid Line Number", f"Line number {line_number} is out of range (1-{num_lines}).", parent=self.app)
        except Exception as e:
            messagebox.showerror("Error", f"Could not go to line {line_number}: {e}", parent=self.app)

    def clear_editor(self):
        """Clears the code editor and line numbers."""
        if self.code_editor:
            self.code_editor.delete('1.0', tk.END)
        if self.line_numbers:
            self.line_numbers.config(state=tk.NORMAL)
            self.line_numbers.delete('1.0', tk.END)
            self.line_numbers.config(state=tk.DISABLED)

    def clear_editor_highlight(self):
        """Removes the line highlight from the editor."""
        if self.code_editor:
            self.code_editor.tag_remove('highlight_line', '1.0', tk.END)