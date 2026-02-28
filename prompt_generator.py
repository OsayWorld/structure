# prompt_generator.py
import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import time
import io
import re
import hashlib
from typing import Optional

# Pygments imports from app_core for lexer guessing
try:
    from pygments import lex
    from pygments.lexers import get_lexer_for_filename, guess_lexer_for_filename, TextLexer
    from pygments.token import Token
    SYNTAX_HIGHLIGHTING = True
except ImportError:
    SYNTAX_HIGHLIGHTING = False

class PromptGenerator:
    SECRET_PATTERNS = [
        (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
        (r'(?i)aws_secret_access_key\s*=\s*["\']?[0-9a-zA-Z/+]{40}["\']?', "AWS Secret Key"),
        (r'(?i)api[_-]?key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}["\']?', "Generic API Key"),
        (r'(?i)secret\s*[:=]\s*["\']?.{8,}["\']?', "Generic Secret"),
        (r'(?i)bearer\s+[A-Za-z0-9\-\._~\+\/]+=*', "Bearer Token"),
        (r'(?i)-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----', "Private Key Block"),
        (r'(?i)firebase[_-]?api[_-]?key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{10,}["\']?', "Firebase Key"),
        (r'(?i)postgres(ql)?:\/\/[^ \n]+', "Database URL"),
    ]

    DEFAULT_TOKEN_BUDGET = 32000

    def __init__(self, app_instance, config_manager, project_scanner, CLIPBOARD_AVAILABLE, SYNTAX_HIGHLIGHTING_FLAG):
        self.app = app_instance
        self.config_manager = config_manager
        self.project_scanner = project_scanner 

        self.CLIPBOARD_AVAILABLE = CLIPBOARD_AVAILABLE
        self.SYNTAX_HIGHLIGHTING = SYNTAX_HIGHLIGHTING_FLAG

        self.ui_builder = None # Will be set by set_dependencies
        self.prompt_text_widget = None # Will be set by UIBuilder

        # Threading state for prompt generation
        self.prompt_generation_thread = None
        self.full_copy_thread = None

        self.FULL_COPY_SIZE_WARNING_THRESHOLD = 5 * 1024 * 1024 # 5 MB for full project copy warning
        self.FULL_COPY_FILE_COUNT_WARNING_THRESHOLD = 500 # 500 files for full project copy warning

    def set_dependencies(self, ui_builder):
        """Set the UIBuilder dependency after initialization."""
        self.ui_builder = ui_builder

    def set_prompt_text_widget(self, widget):
        """Set the actual Tkinter Text widget for the prompt area."""
        self.prompt_text_widget = widget

    def clear_prompt_text(self):
        """Clears the prompt text area."""
        if self.prompt_text_widget:
            self.prompt_text_widget.delete('1.0', tk.END)

    def generate_prompt(self, file_paths, post_generation_callback=None):
        """
        Initiate prompt generation in a separate thread.
        `post_generation_callback` is called on the main thread after the prompt is updated.
        """
        if self.prompt_generation_thread and self.prompt_generation_thread.is_alive():
            self.app.set_status("A prompt is already being generated. Please wait.")
            return
        
        if self.prompt_text_widget:
            self.prompt_text_widget.delete('1.0', tk.END)
            self.prompt_text_widget.insert('1.0', "Generating prompt, please wait...")
        self.app.set_status("Generating prompt...")
        
        # Access UI settings via ui_builder
        include_structure = self.ui_builder.include_structure.get() if self.ui_builder else True
        strip_comments = self.ui_builder.strip_comments.get() if self.ui_builder else False
        template = self.ui_builder.template_var.get() if self.ui_builder else "Standard"
        max_prompt_file_length = self.config_manager.max_prompt_file_length

        self.prompt_generation_thread = threading.Thread(
            target=self._generate_prompt_worker, 
            args=(file_paths, template, include_structure, strip_comments, max_prompt_file_length, post_generation_callback), 
            daemon=True
        )
        self.prompt_generation_thread.start()

    def generate_project_prompt_budgeted(self):
        if not hasattr(self.project_scanner, 'project_path') or not self.project_scanner.project_path:
            messagebox.showwarning("No Project", "Please load a project first.", parent=self.app)
            return

        files = self.project_scanner.get_all_files()
        if not files:
            messagebox.showwarning("No Files", "No eligible files found in the project.", parent=self.app)
            return

        self.generate_prompt_with_budget(files[:50])

    def generate_prompt_with_budget(self, file_paths, token_budget: Optional[int] = None, post_generation_callback=None):
        if self.prompt_generation_thread and self.prompt_generation_thread.is_alive():
            self.app.set_status("A prompt is already being generated. Please wait.")
            return

        if self.prompt_text_widget:
            self.prompt_text_widget.delete('1.0', tk.END)
            self.prompt_text_widget.insert('1.0', "Generating prompt (token budget), please wait...")
        self.app.set_status("Generating prompt (token budget)...")

        include_structure = self.ui_builder.include_structure.get() if self.ui_builder else True
        strip_comments = self.ui_builder.strip_comments.get() if self.ui_builder else False
        template = self.ui_builder.template_var.get() if self.ui_builder else "Standard"
        max_prompt_file_length = self.config_manager.max_prompt_file_length

        if not token_budget or token_budget <= 0:
            token_budget = self.DEFAULT_TOKEN_BUDGET

        self.prompt_generation_thread = threading.Thread(
            target=self._generate_prompt_budgeted_worker,
            args=(file_paths, template, include_structure, strip_comments, max_prompt_file_length, token_budget, post_generation_callback),
            daemon=True,
        )
        self.prompt_generation_thread.start()

    def _generate_prompt_worker(self, file_paths, template, include_structure, strip_comments, max_prompt_file_length, post_generation_callback):
        """Worker thread for generating prompt content."""
        prompt_parts = []
        try:
            prompt_parts.append(self.get_template_header(template))
            
            if include_structure and hasattr(self.project_scanner, 'project_path') and self.project_scanner.project_path:
                prompt_parts.append(self.get_project_structure())
            
            prompt_parts.append("\n" + "="*60 + "\n")
            prompt_parts.append("📁 FILES:\n")
            prompt_parts.append("="*60 + "\n\n")
            
            for file_path in file_paths:
                try:
                    if not os.path.exists(file_path) or os.path.isdir(file_path):
                        prompt_parts.append(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path} (Skipped: Not a valid file or does not exist)\n\n")
                        continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    if max_prompt_file_length > 0 and len(content) > max_prompt_file_length:
                        content = content[:max_prompt_file_length]
                        content += "\n... (file content truncated)"
                    
                    if strip_comments:
                        content = self.remove_comments(content, file_path)
                    
                    rel_path = os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path
                    
                    lexer_name = self._get_pygments_lexer(file_path, content[:1024]).name.lower().replace('lexer', '').strip()
                    if not lexer_name or lexer_name == "text":
                        lexer_name = "text"
                    
                    prompt_parts.append(f"### FILE: {rel_path}\n")
                    prompt_parts.append(f"```{lexer_name}\n")
                    prompt_parts.append(content)
                    prompt_parts.append("\n```\n\n")
                    
                except Exception as e:
                    prompt_parts.append(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path} (Error: {e})\n\n")
            
            prompt_parts.append(self.get_template_footer(template))
            final_prompt = "".join(prompt_parts)
            self.app.after(0, self._update_prompt_text_area, final_prompt, "✅ Prompt generated!", post_generation_callback)
            
        except Exception as e:
            final_prompt = f"Error generating prompt: {e}"
            self.app.after(0, self._update_prompt_text_area, final_prompt, "❌ Error generating prompt.", post_generation_callback)

    def _generate_prompt_budgeted_worker(
        self,
        file_paths,
        template,
        include_structure,
        strip_comments,
        max_prompt_file_length,
        token_budget,
        post_generation_callback,
    ):
        prompt_parts = []
        try:
            prompt_parts.append(self.get_template_header(template))

            if include_structure and hasattr(self.project_scanner, 'project_path') and self.project_scanner.project_path:
                prompt_parts.append(self.get_project_structure())

            prompt_parts.append("\n" + "=" * 60 + "\n")
            prompt_parts.append("📁 FILES:\n")
            prompt_parts.append("=" * 60 + "\n\n")

            used_tokens = self.estimate_tokens("".join(prompt_parts))
            omitted_files = 0
            included_files = 0

            for file_path in file_paths:
                if used_tokens >= token_budget:
                    omitted_files += 1
                    continue

                try:
                    if not os.path.exists(file_path) or os.path.isdir(file_path):
                        rel_path = os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path
                        block = f"### FILE: {rel_path} (Skipped: Not a valid file or does not exist)\n\n"
                        block_tokens = self.estimate_tokens(block)
                        if used_tokens + block_tokens <= token_budget:
                            prompt_parts.append(block)
                            used_tokens += block_tokens
                        else:
                            omitted_files += 1
                        continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    if max_prompt_file_length > 0 and len(content) > max_prompt_file_length:
                        content = content[:max_prompt_file_length] + "\n... (file content truncated)"

                    if strip_comments:
                        content = self.remove_comments(content, file_path)

                    rel_path = os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path

                    lexer_name = self._get_pygments_lexer(file_path, content[:1024]).name.lower().replace('lexer', '').strip()
                    if not lexer_name or lexer_name == "text":
                        lexer_name = "text"

                    header = f"### FILE: {rel_path}\n```{lexer_name}\n"
                    footer = "\n```\n\n"

                    remaining_tokens = max(0, token_budget - used_tokens)
                    overhead_tokens = self.estimate_tokens(header + footer)
                    remaining_for_content_tokens = max(0, remaining_tokens - overhead_tokens)

                    if remaining_for_content_tokens <= 0:
                        omitted_files += 1
                        continue

                    max_content_chars = remaining_for_content_tokens * 4
                    content_to_add = content
                    if len(content_to_add) > max_content_chars:
                        content_to_add = content_to_add[:max(0, max_content_chars)] + "\n... (truncated to fit token budget)"

                    block = header + content_to_add + footer
                    block_tokens = self.estimate_tokens(block)
                    if used_tokens + block_tokens > token_budget:
                        omitted_files += 1
                        continue

                    prompt_parts.append(block)
                    used_tokens += block_tokens
                    included_files += 1
                except Exception as e:
                    rel_path = os.path.relpath(file_path, self.project_scanner.project_path) if self.project_scanner.project_path else file_path
                    block = f"### FILE: {rel_path} (Error: {e})\n\n"
                    block_tokens = self.estimate_tokens(block)
                    if used_tokens + block_tokens <= token_budget:
                        prompt_parts.append(block)
                        used_tokens += block_tokens
                    else:
                        omitted_files += 1

            footer_text = self.get_template_footer(template)
            footer_tokens = self.estimate_tokens(footer_text)
            if used_tokens + footer_tokens <= token_budget:
                prompt_parts.append(footer_text)
            else:
                prompt_parts.append("\n" + "=" * 60 + "\n")
                prompt_parts.append("Prompt footer omitted due to token budget.\n")

            if omitted_files:
                prompt_parts.append("\n" + "=" * 60 + "\n")
                prompt_parts.append(f"Token budget reached: included {included_files} file(s), omitted {omitted_files} file(s).\n")

            final_prompt = "".join(prompt_parts)
            status = f"✅ Prompt generated (budget ~{token_budget:,} tokens)."
            self.app.after(0, self._update_prompt_text_area, final_prompt, status, post_generation_callback)
        except Exception as e:
            final_prompt = f"Error generating prompt: {e}"
            self.app.after(0, self._update_prompt_text_area, final_prompt, "❌ Error generating prompt.", post_generation_callback)

    def _update_prompt_text_area(self, content, status_message, post_generation_callback=None):
        """
        Update the prompt text area and status bar on the main thread.
        If `post_generation_callback` is provided, it's called after the text is updated.
        """
        if self.prompt_text_widget:
            self.prompt_text_widget.delete('1.0', tk.END)
            self.prompt_text_widget.insert('1.0', content)
        self.app.set_status(status_message)
        if post_generation_callback:
            post_generation_callback()

    def get_template_header(self, template):
        """Get template header"""
        headers = {
            "Standard": "🤖 AI CODING ASSISTANT\n" + "="*40 + "\n\nPlease analyze the following code:\n\n",
            "Debug": "🐛 DEBUG REQUEST\n" + "="*40 + "\n\nPlease help debug this code:\n\n",
            "Review": "👀 CODE REVIEW\n" + "="*40 + "\n\nPlease review this code:\n\n",
            "Refactor": "♻️ REFACTOR REQUEST\n" + "="*40 + "\n\nPlease suggest refactoring:\n\n"
        }
        return headers.get(template, headers["Standard"])

    def get_template_footer(self, template):
        """Get template footer"""
        footers = {
            "Standard": "\n" + "="*60 + "\nPlease provide analysis and suggestions.",
            "Debug": "\n" + "="*60 + "\nFocus on finding and fixing bugs.",
            "Review": "\n" + "="*60 + "\nProvide detailed code review feedback.",
            "Refactor": "\n" + "="*60 + "\nSuggest improvements and refactoring."
        }
        return footers.get(template, footers["Standard"])

    def get_project_structure(self):
        """Generate project structure for prompts (limited depth)"""
        try:
            structure = "\n📁 PROJECT STRUCTURE:\n" + "="*40 + "\n"
            structure += f"Project: {os.path.basename(self.project_scanner.project_path)}\n"
            structure += self._build_limited_tree(self.project_scanner.project_path, "", 0, max_depth=3, max_items_per_dir=15)
            return structure + "\n"
        except Exception as e:
            return f"\n📁 PROJECT STRUCTURE: Error - {e}\n"

    def _build_limited_tree(self, path, prefix, depth, max_depth=2, max_items_per_dir=15):
        """Build ASCII tree with depth and item limits, applying current filters."""
        if depth > max_depth:
            return ""
        
        tree = ""
        try:
            items_raw = os.listdir(path)
            
            filtered_items = []
            for item in items_raw:
                item_path = os.path.join(path, item)
                if item in self.config_manager.excluded_patterns or os.path.basename(item_path) in self.config_manager.excluded_patterns:
                    continue
                
                if os.path.isdir(item_path):
                    filtered_items.append(item)
                else:
                    ext = os.path.splitext(item)[1].lower()
                    if not self.config_manager.included_extensions or ext in self.config_manager.included_extensions or (ext == '' and 'no ext' in self.config_manager.included_extensions):
                        if item.startswith('.') and item not in {'.gitignore', '.env.example', '.dockerignore', 'Dockerfile', 'LICENSE', 'README'}:
                            continue
                        filtered_items.append(item)
            
            filtered_items.sort()
            
            for i, item in enumerate(filtered_items):
                if i >= max_items_per_dir: 
                    tree += f"{prefix}└── ... ({len(filtered_items) - i} more items hidden)\n"
                    break

                item_path = os.path.join(path, item)
                is_last = i == len(filtered_items) - 1
                
                connector = "└── " if is_last else "├── "
                tree += f"{prefix}{connector}"
                
                if os.path.isdir(item_path):
                    tree += f"📁 {item}/\n"
                    if depth < max_depth:
                        extension = "    " if is_last else "│   "
                        tree += self._build_limited_tree(item_path, prefix + extension, depth + 1, max_depth, max_items_per_dir)
                else:
                    icon_text = self.project_scanner.get_file_icon(item)
                    tree += f"{icon_text} {item}\n"
                    
        except (PermissionError, OSError):
            tree += f"{prefix}└── ⚠️ Access denied\n"
        
        return tree

    def _get_pygments_lexer(self, file_path, content_sample=""):
        """Wrapper to get Pygments lexer, depends on SYNTAX_HIGHLIGHTING being True."""
        if not self.SYNTAX_HIGHLIGHTING:
            return TextLexer()

        try:
            return get_lexer_for_filename(file_path, stripall=True)
        except Exception:
            try:
                if content_sample:
                    return guess_lexer_for_filename(file_path, content_sample, stripall=True)
                return TextLexer()
            except Exception:
                # Corrected the typo here: changed 'Texter()' to 'TextLexer()'
                return TextLexer()

    def remove_comments(self, content, file_path):
        """Remove comments from content based on file type."""
        ext = os.path.splitext(file_path)[1].lower()
        filename_lower = os.path.basename(file_path).lower()

        if ext == '.py':
            lines = content.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith('#'):
                    continue
                if '#' in line:
                    match = re.search(r'(?<!["\'])#.*', line)
                    if match:
                        line = line[:match.start()].rstrip()
                cleaned_lines.append(line)
            content = '\n'.join(cleaned_lines)

        elif ext in ['.js', '.jsx', '.ts', '.tsx', '.c', '.cpp', '.java', '.php', '.go', '.rs', '.swift']:
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL) 
            content = re.sub(r'//.*', '', content)

        elif ext in ['.html', '.xml', '.vue', '.md']:
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)

        elif ext == '.css':
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

        elif ext in ['.yml', '.yaml', '.rb', '.sh'] or filename_lower in ['dockerfile', 'makefile', '.env']:
            lines = content.split('\n')
            cleaned_lines = []
            for i, line in enumerate(lines):
                stripped_line = line.strip()
                if stripped_line.startswith('#!/') and i == 0:
                    cleaned_lines.append(line)
                    continue
                if stripped_line.startswith('#'):
                    continue
                if '#' in line:
                    match = re.search(r'(?<!["\'])#.*', line)
                    if match:
                        line = line[:match.start()].rstrip()
                cleaned_lines.append(line)
            content = '\n'.join(cleaned_lines)
            
        elif ext == '.ini':
            lines = content.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith(';'):
                    continue
                if ';' in line:
                    line = line.split(';', 1)[0].rstrip()
                cleaned_lines.append(line)
            content = '\n'.join(cleaned_lines)

        return content.strip()

    def copy_selected_prompt(self, post_copy_action=False):
        """
        Copy selected item as prompt.
        If `post_copy_action` is True, `copy_current_prompt` will be called
        as a callback after prompt generation.
        """
        if not self.ui_builder: # Ensure ui_builder is set
            messagebox.showwarning("Initialization Error", "UI Builder not initialized yet.", parent=self.app)
            return

        try:
            tree_sel = self.ui_builder.tree.selection() if self.ui_builder.tree else []
            list_sel = self.ui_builder.file_list.selection() if self.ui_builder.file_list else []
            
            file_path_to_prompt = None

            if tree_sel:
                item_id = tree_sel[0] 
                values = self.ui_builder.tree.item(item_id, "values")
                if values and len(values) > 0:
                    file_path_to_prompt = values[0]
            elif list_sel:
                item_id = list_sel[0] 
                values = self.ui_builder.file_list.item(item_id, "values")
                if values and len(values) >= 3:
                    file_path_to_prompt = values[2]
            
            if file_path_to_prompt and os.path.isfile(file_path_to_prompt):
                callback = self.copy_current_prompt if post_copy_action else None
                self.generate_prompt([file_path_to_prompt], post_generation_callback=callback)
            else:
                messagebox.showwarning("No File Selected", "Please select a file to generate a prompt for.", parent=self.app)
                
        except Exception as e:
            print(f"Error copying selected prompt: {e}")
            messagebox.showerror("Error", f"Failed to copy prompt for selected item: {e}", parent=self.app)

    def copy_current_prompt(self):
        """Copy current prompt to clipboard"""
        try:
            if not self.prompt_text_widget: return
            prompt = self.prompt_text_widget.get('1.0', tk.END).strip()
            if prompt:
                if self.CLIPBOARD_AVAILABLE:
                    import pyperclip # Import here to ensure it's available
                    pyperclip.copy(prompt)
                    self.app.set_status("📋 Prompt copied to clipboard!")
                else:
                    messagebox.showinfo("Clipboard Not Available", "Pyyperclip is not installed. Prompt copied to clipboard failed. Please install pyperclip for clipboard functionality.\n\nPrompt content is in the 'Generated Prompt' area.", parent=self.app)
            else:
                self.app.set_status("No prompt content to copy.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy prompt: {e}", parent=self.app)

    def save_prompt_to_file(self):
        """Save prompt to file"""
        try:
            if not self.prompt_text_widget: return
            prompt = self.prompt_text_widget.get('1.0', tk.END).strip()
            if not prompt:
                messagebox.showwarning("Warning", "No prompt to save!", parent=self.app)
                return
                
            filename = filedialog.asksaveasfilename(
                title="Save Prompt",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("Markdown files", "*.md"), ("All files", "*.*")],
                parent=self.app
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                self.app.set_status(f"💾 Prompt saved to {os.path.basename(filename)}")
                messagebox.showinfo("Prompt Saved", f"✅ Prompt successfully saved to: {os.path.basename(filename)}", parent=self.app)
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save prompt: {e}", parent=self.app)

    def copy_folder_prompt(self, post_copy_action=False):
        """
        Copy folder prompt.
        If `post_copy_action` is True, `copy_current_prompt` will be called
        as a callback after prompt generation.
        """
        if not self.ui_builder:
            messagebox.showwarning("Initialization Error", "UI Builder not initialized yet.", parent=self.app)
            return

        try:
            selection = self.ui_builder.tree.selection() if self.ui_builder.tree else []
            if selection:
                item_id = selection[0] 
                values = self.ui_builder.tree.item(item_id, "values")
                if values and len(values) > 0:
                    folder_path = values[0]
                    if os.path.isdir(folder_path):
                        files = self.project_scanner.get_folder_files(folder_path)
                        if files:
                            if len(files) > 20: # Limit for folder prompt to keep it manageable
                                result = messagebox.askyesno("Large Folder Prompt", 
                                                           f"The selected folder and its subfolders contain {len(files)} eligible files. This prompt will be limited to the first 20 files, and individual file contents might be truncated to {self.config_manager.max_prompt_file_length} characters. Continue?", parent=self.app)
                                if not result:
                                    return
                            
                            callback = self.copy_current_prompt if post_copy_action else None
                            self.generate_prompt(files[:20], post_generation_callback=callback) # Apply folder prompt specific file count truncation
                        else:
                            messagebox.showwarning("No Files", "No eligible files found in this folder or its subfolders to generate a prompt.", parent=self.app)
                    else:
                        messagebox.showwarning("Not a Folder", "Please select a folder to copy its content as a prompt.", parent=self.app)
                else:
                    messagebox.showwarning("No Folder", "Please select a folder to copy its content as a prompt.", parent=self.app)
        except Exception as e:
            print(f"Error copying folder prompt: {e}")
            messagebox.showerror("Error", f"Failed to copy folder prompt: {e}", parent=self.app)

    def copy_project_prompt(self, post_copy_action=False):
        """
        Copy entire project prompt (with truncation).
        If `post_copy_action` is True, `copy_current_prompt` will be called
        as a callback after prompt generation.
        """
        try:
            if not hasattr(self.project_scanner, 'project_path') or not self.project_scanner.project_path:
                messagebox.showwarning("No Project", "Please load a project first.", parent=self.app)
                return
            
            files = self.project_scanner.get_all_files()
            if files:
                if len(files) > 50: # Arbitrary limit for 'project prompt' to keep it manageable
                    result = messagebox.askyesno("Large Project Prompt", 
                                               f"Project has {len(files)} eligible files. The generated prompt will be limited to the first 50 files, and individual file contents might be truncated to {self.config_manager.max_prompt_file_length} characters. Continue?", parent=self.app)
                    if not result:
                        return
                
                callback = self.copy_current_prompt if post_copy_action else None
                self.generate_prompt(files[:50], post_generation_callback=callback) # Apply project prompt specific file count truncation
            else:
                messagebox.showwarning("No Files", "No eligible files found in the project to generate a prompt.", parent=self.app)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy project prompt: {e}", parent=self.app)

    def copy_full_project_code(self):
        """
        New feature: Copy the *entire* project code without truncation.
        Includes project structure and full content of all eligible files.
        Respects folder exclusions set by the user.
        """
        if not hasattr(self.project_scanner, 'project_path') or not self.project_scanner.project_path:
            messagebox.showwarning("No Project", "Please load a project first to copy its code.", parent=self.app)
            return

        # Get files respecting folder and file exclusions
        all_files_paths = self.project_scanner.get_all_files(respect_exclusions=True)
        total_content_size = sum(os.path.getsize(f) for f in all_files_paths if os.path.exists(f))

        if not all_files_paths:
            messagebox.showinfo("No Files", "No eligible files found in the project to copy (all items may be excluded).", parent=self.app)
            return

        # Show exclusion info if folders or files are excluded
        excluded_folder_count = len(self.project_scanner.excluded_folders)
        excluded_file_count = len(self.project_scanner.excluded_files)
        warning_message = ""
        if excluded_folder_count > 0 or excluded_file_count > 0:
            warning_message += f"Note: {excluded_folder_count} folder(s) and {excluded_file_count} file(s) are excluded and will not be copied.\n\n"
        
        if total_content_size > self.FULL_COPY_SIZE_WARNING_THRESHOLD:
            warning_message += f"The total size of project files ({self.project_scanner.format_size(total_content_size)}) exceeds the recommended copy limit of {self.project_scanner.format_size(self.FULL_COPY_SIZE_WARNING_THRESHOLD)}.\n"
        if len(all_files_paths) > self.FULL_COPY_FILE_COUNT_WARNING_THRESHOLD:
            warning_message += f"The project contains {len(all_files_paths)} files, which may be too many for some applications' clipboard limits.\n"
        
        if warning_message:
            warning_message += "\nProceed with copying the full project code? Note that clipboard limitations might still truncate very large content."
            if not messagebox.askyesno("Large Project Code Copy", warning_message, parent=self.app):
                return
        
        self.app.set_status("🗄️ Preparing full project code for copy (this may take a moment for large projects)...")
        
        if self.full_copy_thread and self.full_copy_thread.is_alive():
            self.app.set_status("Full project copy is already in progress. Please wait.")
            return

        # Run the heavy content generation in a separate thread
        self.full_copy_thread = threading.Thread(target=self._generate_and_copy_full_project_content_worker, args=(all_files_paths,), daemon=True)
        self.full_copy_thread.start()

    def _generate_and_copy_full_project_content_worker(self, all_files_paths):
        """Worker thread to generate the full project content string and copy it."""
        try:
            output_buffer = io.StringIO()

            output_buffer.write("📦 FULL PROJECT CODE BASE 📦\n")
            output_buffer.write("=" * 70 + "\n\n")
            # Use a slightly deeper tree for full project view, but still with limits
            output_buffer.write(self._build_limited_tree(self.project_scanner.project_path, "", 0, max_depth=4, max_items_per_dir=25)) 
            output_buffer.write("\n" + "=" * 70 + "\n")
            output_buffer.write("ALL PROJECT FILES (Untruncated, Comments Included):\n")
            output_buffer.write("=" * 70 + "\n\n")

            for file_path in all_files_paths:
                try:
                    if not os.path.exists(file_path) or os.path.isdir(file_path):
                        output_buffer.write(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path)} (Skipped: Not a valid file or does not exist)\n\n")
                        continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    rel_path = os.path.relpath(file_path, self.project_scanner.project_path)
                    lexer_name = self._get_pygments_lexer(file_path, content[:1024]).name.lower().replace('lexer', '').strip()
                    if not lexer_name or lexer_name == "text":
                        lexer_name = "text"
                    
                    output_buffer.write(f"### FILE: {rel_path}\n")
                    output_buffer.write(f"```{lexer_name}\n")
                    output_buffer.write(content)
                    output_buffer.write("\n```\n\n")
                except Exception as e:
                    output_buffer.write(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path)} (Error reading file: {e})\n\n")
            
            full_content = output_buffer.getvalue()

            self.app.after(0, self._finalize_full_project_copy, full_content)

        except Exception as e:
            self.app.after(0, lambda: messagebox.showerror("Error", f"Failed to generate full project code: {e}", parent=self.app))
            self.app.after(0, lambda: self.app.set_status("❌ Error generating full project code."))

    def _finalize_full_project_copy(self, full_content):
        """Finalizes the full project copy operation on the main thread."""
        if self.CLIPBOARD_AVAILABLE:
            try:
                import pyperclip
                pyperclip.copy(full_content)
                self.app.set_status("✅ Full project code copied to clipboard!")
                messagebox.showinfo("Full Project Copied", "✅ The complete project code has been copied to your clipboard. Be aware that very large content might still be truncated by the operating system's clipboard or the receiving application.", parent=self.app)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy to clipboard: {e}\n\nThe content is very large and might exceed clipboard limits. Trying to save to a file instead.", parent=self.app)
                self.app.set_status("❌ Failed to copy full project code to clipboard.")
                # Offer to save to file if clipboard fails
                self._save_large_content_to_file(full_content, "full_project_code.txt")
        else:
            messagebox.showinfo("Clipboard Not Available", "Clipboard features are disabled. Generated full project code is too large to display directly.", parent=self.app)
            self.app.set_status("❌ Clipboard not available for full project copy.")
            # Offer to save to file
            self._save_large_content_to_file(full_content, "full_project_code.txt")

    def _save_large_content_to_file(self, content, default_filename):
        """Helper to save large content to a file if clipboard fails or is unavailable."""
        if messagebox.askyesno("Save Content to File?", "Would you like to save the generated content to a file instead?", parent=self.app):
            filename = filedialog.asksaveasfilename(
                title="Save Full Project Code",
                defaultextension=".txt",
                initialfile=default_filename,
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                parent=self.app
            )
            if filename:
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(content)
                    self.app.set_status(f"💾 Full project code saved to {os.path.basename(filename)}")
                    messagebox.showinfo("Saved", f"✅ Content successfully saved to: {os.path.basename(filename)}", parent=self.app)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save file: {e}", parent=self.app)
                    self.app.set_status("❌ Error saving content to file.")

    def generate_smart_prompt(self):
        """Initiate smart prompt generation in a separate thread."""
        if not hasattr(self.project_scanner, 'project_path') or not self.project_scanner.project_path:
            messagebox.showwarning("No Project", "Please load a project first.", parent=self.app)
            return

        if self.prompt_generation_thread and self.prompt_generation_thread.is_alive():
            self.app.set_status("A prompt is already being generated. Please wait.")
            return
            
        if self.prompt_text_widget:
            self.prompt_text_widget.delete('1.0', tk.END)
            self.prompt_text_widget.insert('1.0', "Generating smart prompt, please wait...")
        self.app.set_status("🧠 Analyzing project and generating smart prompt...")
        
        self.prompt_generation_thread = threading.Thread(
            target=self._generate_smart_prompt_worker, 
            args=(self.config_manager.max_prompt_file_length,), 
            daemon=True
        )
        self.prompt_generation_thread.start()

    def _generate_smart_prompt_worker(self, max_prompt_file_length):
        """Worker thread for generating smart prompt content."""
        try:
            analysis = self.analyze_project_simple()
            prompt = self.create_smart_prompt(analysis, max_prompt_file_length)
            # No specific post-generation callback for smart prompt is currently requested.
            self.app.after(0, self._update_prompt_text_area, prompt, "🎨 Smart prompt generated!")
        except Exception as e:
            final_prompt = f"Error generating smart prompt: {e}"
            self.app.after(0, self._update_prompt_text_area, final_prompt, "❌ Error generating smart prompt.")

    def analyze_project_simple(self):
        """Simple project analysis based on scanned data."""
        analysis = {
            'languages': {},
            'key_files': [],
            'total_files': 0
        }
        
        try:
            for item_data in self.project_scanner.scanned_file_list_data:
                full_path = item_data[3]
                file = os.path.basename(full_path)
                
                analysis['total_files'] += 1
                
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content_sample = f.read(1024) # Read first 1KB for lexer guessing
                except Exception:
                    content_sample = ""

                lexer_instance = self._get_pygments_lexer(full_path, content_sample)
                lang = lexer_instance.name if hasattr(lexer_instance, 'name') and lexer_instance.name != 'Text' else 'Unknown'
                
                analysis['languages'][lang] = analysis['languages'].get(lang, 0) + 1
                
                if self.is_key_file(file):
                    analysis['key_files'].append(full_path)
        except Exception as e:
            print(f"Analysis error: {e}")
            self.app.set_status(f"Error during project analysis: {e}")
        
        return analysis

    def is_key_file(self, filename):
        """Check if file is important for smart prompt analysis."""
        key_files = {
            'main.py', 'app.py', 'index.js', 'index.html', 'readme.md',
            'package.json', 'requirements.txt', 'setup.py', 'config.py',
            'server.js', 'webpack.config.js', 'dockerfile', 'makefile', '.env',
            'license', 'changelog.md', 'contributing.md', 'security.md',
            'tsconfig.json', '.eslintrc', '.prettierrc', 'vite.config.js',
            'compose.yaml', 'docker-compose.yaml', 'k8s.yaml', 'chart.yaml'
        }
        return filename.lower() in key_files

    def create_smart_prompt(self, analysis, max_prompt_file_length):
        """Create smart prompt from analysis."""
        prompt_parts = []
        prompt_parts.append("🧠 SMART PROJECT ANALYSIS & REQUEST\n")
        prompt_parts.append("="*50 + "\n\n")
        
        prompt_parts.append("📊 PROJECT OVERVIEW:\n")
        prompt_parts.append(f"• Total Eligible Files Analyzed: {analysis['total_files']}\n")
        if analysis['languages']:
            # Sort languages by count descending, then alphabetically for ties
            sorted_languages = sorted(analysis['languages'].items(), key=lambda item: (-item[1], item[0]))
            lang_summary = ", ".join([f"{lang} ({count})" for lang, count in sorted_languages])
            prompt_parts.append(f"• Languages Detected (Count): {lang_summary}\n")
        frameworks = self.detect_frameworks()
        if frameworks:
            prompt_parts.append(f"• Framework Signals: {', '.join(frameworks)}\n")
        prompt_parts.append(f"• Key Files Identified: {len(analysis['key_files'])}\n\n")
        
        if hasattr(self.project_scanner, 'project_path') and self.project_scanner.project_path:
            prompt_parts.append(self.get_project_structure())
        
        prompt_parts.append("\n🔑 KEY FILES (Content Sample):\n" + "="*40 + "\n\n")
        
        for file_path in analysis['key_files'][:10]: # Limit key files to sample
            try:
                if not os.path.exists(file_path) or os.path.isdir(file_path):
                    prompt_parts.append(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path)} (Skipped: Not a valid file or does not exist)\n\n")
                    continue

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Apply truncation for smart prompt to keep it concise
                if max_prompt_file_length > 0 and len(content) > max_prompt_file_length:
                    content = content[:max_prompt_file_length]
                    content += "\n... (file content truncated for smart prompt)"
                elif len(content) > 2000: # Further truncate if still too long after max_prompt_file_length or if max_prompt_file_length is not set
                    content = content[:2000] + "\n... (further truncated for smart prompt overview)"

                rel_path = os.path.relpath(file_path, self.project_scanner.project_path)
                
                lexer_name = self._get_pygments_lexer(file_path, content[:1024]).name.lower().replace('lexer', '').strip()
                if not lexer_name or lexer_name == "text":
                    lexer_name = "text"
                
                prompt_parts.append(f"### FILE: {rel_path}\n")
                prompt_parts.append(f"```{lexer_name}\n")
                prompt_parts.append(content)
                prompt_parts.append("\n```\n\n")
            except Exception as e:
                print(f"Error reading key file {file_path}: {e}")
                prompt_parts.append(f"### FILE: {os.path.relpath(file_path, self.project_scanner.project_path)} (Error reading file: {e})\n\n")
        
        prompt_parts.append("\n🎯 ANALYSIS REQUEST:\n" + "="*30 + "\n")
        prompt_parts.append("Please analyze this project based on the provided overview and key file samples, and provide a comprehensive response covering the following:\n")
        prompt_parts.append("1. **High-Level Architecture Overview**: Describe the main components, their interactions, and overall design patterns.\n")
        prompt_parts.append("2. **Code Quality and Maintainability Assessment**: Evaluate factors like readability, modularity, error handling, and adherence to common coding standards.\n")
        prompt_parts.append("3. **Improvement, Optimization, and Refactoring Suggestions**: Provide actionable recommendations for enhancing performance, reducing complexity, and making the codebase more robust.\n")
        prompt_parts.append("4. **Best Practices and Potential Security Concerns**: Point out areas where industry best practices could be better applied and highlight any immediate security vulnerabilities or risks.\n")
        prompt_parts.append("5. **Suggested Next Steps**: Outline a prioritized list of actions or further analysis that would be beneficial.\n")
        
        return "".join(prompt_parts)

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def show_prompt_token_estimate(self):
        if not self.prompt_text_widget:
            return
        prompt = self.prompt_text_widget.get("1.0", tk.END).strip()
        tokens = self.estimate_tokens(prompt)
        messagebox.showinfo(
            "Token Estimate",
            f"📏 Approx tokens: {tokens:,}\n\nTip: 100k tokens is huge. Use big-context models for full project dumps.",
            parent=self.app,
        )

    def scan_for_secrets(self, text: str):
        hits = []
        for pattern, label in self.SECRET_PATTERNS:
            for m in re.finditer(pattern, text):
                sample = m.group(0)
                sample_hash = hashlib.sha256(sample.encode("utf-8", errors="ignore")).hexdigest()[:10]
                hits.append((label, sample_hash))
        return hits

    def scan_project_for_secrets(self):
        if not hasattr(self.project_scanner, 'project_path') or not self.project_scanner.project_path:
            messagebox.showwarning("No Project", "Load a project first.", parent=self.app)
            return

        files = self.project_scanner.get_all_files()
        found = []

        for fp in files:
            try:
                if not os.path.isfile(fp):
                    continue
                if os.path.getsize(fp) > 2 * 1024 * 1024:
                    continue
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                hits = self.scan_for_secrets(content)
                if hits:
                    found.append((fp, hits))
            except Exception:
                continue

        if not found:
            messagebox.showinfo("Secret Scan", "✅ No obvious secrets detected.", parent=self.app)
            return

        report = ["🔐 SECRET SCAN REPORT\n", "=" * 60, "\n"]
        for fp, hits in found[:80]:
            rel = os.path.relpath(fp, self.project_scanner.project_path)
            report.append(f"\n📄 {rel}\n")
            for label, sample_hash in hits[:10]:
                report.append(f"  • {label} (hash:{sample_hash})\n")

        msg = "".join(report)
        self._update_prompt_text_area(msg, "⚠️ Secrets found. Review report.")

    def _sample_file_contains(self, keyword: str, max_files: int = 80, max_bytes: int = 4096) -> bool:
        if not self.project_scanner.project_path:
            return False
        keyword_l = keyword.lower()
        scanned = self.project_scanner.scanned_file_list_data[:max_files]
        for item_data in scanned:
            fp = item_data[3]
            try:
                if not os.path.isfile(fp):
                    continue
                if os.path.getsize(fp) > 2 * 1024 * 1024:
                    continue
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    chunk = f.read(max_bytes)
                if keyword_l in chunk.lower():
                    return True
            except Exception:
                continue
        return False

    def detect_frameworks(self):
        if not self.project_scanner.project_path:
            return []

        files = [os.path.basename(p).lower() for p in self.project_scanner.get_all_files()]
        frameworks = set()

        def has(name: str) -> bool:
            return name.lower() in files

        if has("requirements.txt") or has("pyproject.toml"):
            frameworks.add("Python Project")

        if "django" in " ".join(files):
            frameworks.add("Django (possible)")

        if "flask" in " ".join(files) or self._sample_file_contains("flask"):
            frameworks.add("Flask (possible)")

        if "fastapi" in " ".join(files) or self._sample_file_contains("fastapi"):
            frameworks.add("FastAPI (possible)")

        if has("package.json"):
            frameworks.add("Node.js Project")
        if has("vite.config.js") or has("vite.config.ts"):
            frameworks.add("Vite (possible)")
        if has("electron.js") or "electron" in " ".join(files):
            frameworks.add("Electron (possible)")
        if any(f.endswith(".tsx") or f.endswith(".jsx") for f in files):
            frameworks.add("React-style frontend (possible)")

        return sorted(frameworks)