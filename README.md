# Project Structure Tool

A powerful GUI application for exploring project structures with advanced folder and file selection capabilities.

## Features

✅ **Interactive Folder/File Checkboxes**
- Click any folder or file to toggle inclusion/exclusion
- Visual feedback with ☑ (included) and ☐ (excluded) checkboxes
- Excluded items appear grayed out

✅ **Cascading Selection**
- Unchecking a folder automatically unchecks all files and subfolders within it
- Checking a folder automatically checks all contents

✅ **Bulk Operations**
- **✓ All** button - Include all folders and files
- **✗ All** button - Exclude all folders and files

✅ **Smart Copy Features**
- Copy individual file prompts
- Copy folder prompts
- Copy full project code (respects exclusions)
- Files in excluded folders are automatically skipped

✅ **Workspace Management**
- Multiple workspace support
- Persistent exclusion settings per workspace
- Fast project scanning with caching

## Running the Application

### Method 1: Python Script (Recommended)
```bash
python main.py
```

### Method 2: Batch File (Windows - with console)
Double-click `ProjectStructureTool.bat`

### Method 3: VBS Script (Windows - no console window)
Double-click `ProjectStructureTool_NoConsole.vbs`

## Requirements

- Python 3.8+
- ttkbootstrap
- pygments
- pyperclip (optional, for clipboard support)

Install dependencies:
```bash
pip install ttkbootstrap pygments pyperclip
```

## Usage

1. **Load a Project**
   - Click "📂 Open" or press Ctrl+O
   - Select your project folder

2. **Select Files/Folders**
   - Click on any folder or file to toggle its checkbox
   - Use ✓ All / ✗ All for bulk operations
   - Excluded items show as ☐ and appear grayed out

3. **Copy Project Code**
   - Click "🗄️ Copy Full Project" or press Ctrl+Alt+C
   - Only included files (☑) will be copied
   - Files in excluded folders are automatically skipped

4. **View Status**
   - Status bar shows how many folders and files are excluded
   - Updates in real-time as you toggle items

## Keyboard Shortcuts

- **Ctrl+O** - Open project
- **F5** - Reload project
- **Ctrl+S** - Save current file
- **Ctrl+C** - Copy selected file prompt
- **Ctrl+Alt+C** - Copy full project code
- **Ctrl+F** - Focus search
- **Ctrl+G** - Go to line

## File Structure

- `main.py` - Application entry point
- `app_core.py` - Core application logic
- `ui_builder.py` - UI components and layout
- `project_scanner.py` - Project scanning and file management
- `prompt_generator.py` - Prompt generation and copying
- `code_editor_manager.py` - Code editor functionality
- `config_manager.py` - Configuration management

## Configuration

Settings are stored in `explorer_config.json`:
- Excluded patterns
- Included file extensions
- Font size
- Recent workspaces
- Folder/file exclusions per workspace

## Notes

- Exclusion settings are saved per workspace
- Cached project data speeds up subsequent loads
- Large projects may take a moment to scan initially
- The application respects .gitignore patterns

## Version

1.0 - Initial release with cascading checkbox functionality
