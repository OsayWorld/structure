import sys
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need fine tuning.
build_exe_options = {
    "packages": [
        "os",
        "sys",
        "tkinter",
        "ttkbootstrap",
        "pygments",
        "pyperclip",
        "json",
        "hashlib",
        "threading",
        "pathlib",
        "dataclasses",
        "re",
        "io",
    ],
    "excludes": ["unittest", "test"],
    "include_files": [],
}

# GUI applications require a different base on Windows
base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="ProjectStructureTool",
    version="1.0",
    description="Project Structure Explorer with Folder/File Selection",
    options={"build_exe": build_exe_options},
    executables=[Executable("main.py", base=base, target_name="ProjectStructureTool.exe")],
)
