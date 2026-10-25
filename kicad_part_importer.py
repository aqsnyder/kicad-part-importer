#!/usr/bin/env python
"""
kicad-part-importer: import vendor part downloads into a categorized KiCad library.

This tool manages a KiCad component library by:
1. Processing zip files containing KiCad symbols, footprints, and 3D models
   (TI / Ultra Librarian, SamacSys and SnapEDA downloads)
2. Organizing components into categorized libraries
3. Linking each footprint to its 3D model, and checking every model path
4. Updating project-specific library settings
5. Providing git integration for version control (it pushes only with --push
   or git_push = true in the library's config file)
6. Migrating components from older symbol libraries and schematics

The tool is independent of any library: it works on the library named by
--library, $KICAD_PART_IMPORTER_LIBRARY_ROOT, or the nearest folder at or above
the current directory holding a kicad-part-importer.toml / .json (else the
current directory). `--init` creates a library and writes that file.

Usage:
    kicad-part-importer <zip_file> [options]
    python kicad_part_importer.py <zip_file> [options]

Commands:
    --init                   Create a library here (or in --library DIR): config file + folders
    --init-libraries         Create the empty category libraries and folders (no config file)
    --add-to-project         Add libraries to a project's sym-lib-table / fp-lib-table
    --migrate [FILE]         Move symbols from other .kicad_sym files into the categories
    --migrate-schematic FILE Move the custom parts a schematic uses into the categories
    --check-3d [--fix-3d]    Check (and fix) every footprint's 3D model path in the library
    --show-config            Print the effective settings as JSON

Zip import without prompts, and 3D-model linking (see docs/cli.md):
    --category KEY           Library to add to (key, library name or menu number)
    --link-3d                Point each footprint's (model ...) at the library's model folder
    --verify-3d              Load the touched footprints in KiCad and report models that do not load
    --yes / --dry-run / --json, --keep-zip / --delete-zip, --overwrite

Configuration (see docs/configuration.md): --library DIR, --config FILE,
--library-prefix, --symbol-dir, --footprint-dir, --model-dir, --model-search-dir,
--library-mount, --model-prefix, --project-dir, --commit / --no-commit,
--push / --no-push; KICAD_PART_IMPORTER_* variables.
"""

import os
import sys
import re
import glob
import zipfile
import shutil
import argparse
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import tempfile
import contextlib

# The helper modules live next to this one; keep them importable under python -I too.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import kicad_lib_3d as lib3d  # noqa: E402
import kicad_lib_config as libcfg  # noqa: E402

__version__ = "0.1.0"

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3

EMPTY_SYMBOL_LIBRARY = '(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)\n)'


def _read_kicad_text(path):
    """Read a KiCad text file; return (text with LF line ends, the file's EOL)."""
    raw = lib3d.read_text(path)
    return raw.replace('\r\n', '\n'), lib3d.eol_of(raw)


def _write_kicad_text(path, text, eol='\n'):
    """Write text (LF line ends) with the given EOL and no newline translation, so a
    file keeps its line endings on Windows instead of turning into CRLF."""
    text = text.replace('\r\n', '\n')
    lib3d.write_text(path, text if eol == '\n' else text.replace('\n', eol))


def _top_level_symbol_names(text):
    """Names of the depth-1 (symbol "...") blocks of a .kicad_sym, string-aware and
    independent of indentation (extract_symbols_from_library needs one tab)."""
    names, depth, i, n = [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '(':
            depth += 1
            if depth == 2:
                m = re.match(r'\(symbol\s+"((?:[^"\\]|\\.)*)"', text[i:i + 300])
                if m:
                    names.append(m.group(1))
        elif c == ')':
            depth -= 1
        i += 1
    return names


def _guard_console_encoding():
    """Printing the check marks on a cp1252 console or pipe would raise
    UnicodeEncodeError, possibly halfway through an import. Replace unencodable
    characters instead (UTF-8 consoles are unaffected)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            '✓✗⚠'.encode(stream.encoding or 'ascii')
        except (UnicodeEncodeError, LookupError):
            try:
                stream.reconfigure(errors='replace')
            except AttributeError:
                pass


class LibraryManager:
    """Manages a categorized KiCad library: imports, 3D models, project tables, git."""

    def __init__(self, base_path: str = None, config: Optional[libcfg.LibraryConfig] = None):
        """Initialize the library manager with a library root, or a full configuration.

        base_path alone uses the default layout and naming for that root (the
        current directory when neither is given)."""
        if config is None:
            config = libcfg.LibraryConfig(base_path if base_path is not None else Path.cwd())
        elif base_path is not None and Path(base_path).resolve() != Path(config.library_root).resolve():
            raise ValueError("base_path and config.library_root name different folders")
        self.config = config
        self.base_path = Path(config.library_root)
        self.lib_sym_path = self.base_path / config.symbol_dir
        self.lib_fp_path = self.base_path / config.footprint_dir
        self.models_3d_path = self.base_path / config.model_dir

        # Library categories, in menu order
        self.libraries = {
            c.key: {"name": c.name, "sym_file": c.sym_file, "fp_dir": c.fp_dir, "description": c.description}
            for c in config.categories
        }

    def _category_pretty_dirs(self):
        """The category footprint libraries present: <footprint_dir>/<library_prefix>*.pretty."""
        return sorted(self.lib_fp_path.glob(glob.escape(self.config.library_prefix) + '*.pretty'))

    def library_exists(self) -> bool:
        """True when the library root holds the symbol or the footprint folder,
        i.e. it has been initialized (--init / --init-libraries) or migrated."""
        return self.lib_sym_path.is_dir() or self.lib_fp_path.is_dir()

    def _commit_message(self, message: str) -> str:
        return self.config.git_message_prefix + message

    def display_library_menu(self, component_name: str = None, datasheet: str = None, footprint: str = None) -> None:
        """Display the library selection menu"""
        print("\n" + "="*60)
        print("KiCad Part Importer - Library Selection")
        print("="*60)
        print("Select a library to add the component to:")
        print()

        for i, (key, lib_info) in enumerate(self.libraries.items(), 1):
            title = key.replace('_', ' ').title()
            print(f"{i:2d}. {title}: {lib_info['description']}" if lib_info['description'] else f"{i:2d}. {title}")

        print()
        print(" 0. Skip (don't add to any library)")
        print("="*60)

        if component_name:
            print(f"\nComponent: {component_name}")
            if datasheet:
                print(f"Datasheet: {datasheet}")
            if footprint:
                print(f"Footprint: {footprint}")
            print()

    def get_library_selection(self) -> Optional[str]:
        """Get library selection from user. Returns None to skip, raises KeyboardInterrupt to stop."""
        while True:
            try:
                choice = input(f"\nEnter your choice (0-{len(self.libraries)}): ").strip()
                choice_num = int(choice)

                if choice_num == 0:
                    return None
                elif 1 <= choice_num <= len(self.libraries):
                    return list(self.libraries.keys())[choice_num - 1]
                else:
                    print(f"Invalid choice. Please enter a number between 0 and {len(self.libraries)}")
            except ValueError:
                print("Invalid input. Please enter a number.")
            # KeyboardInterrupt is NOT caught here - it propagates up to stop the loop

    def extract_zip_contents(self, zip_path: str) -> Tuple[Path, List[str]]:
        """Extract zip file and return temporary directory and file list"""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # Get list of extracted files
            extracted_files = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    extracted_files.append(Path(root) / file)

            return temp_dir, extracted_files
        except zipfile.BadZipFile:
            print(f"Error: {zip_path} is not a valid zip file")
            sys.exit(1)
        except Exception as e:
            print(f"Error extracting zip file: {e}")
            sys.exit(1)

    def categorize_files(self, files: List[Path]) -> Dict[str, List[Path]]:
        """Categorize files by type (symbols, footprints, 3d_models)"""
        categorized = {
            'symbols': [],
            'footprints': [],
            '3d_models': []
        }

        for file_path in files:
            file_ext = file_path.suffix.lower()
            file_name = file_path.name.lower()

            if file_ext == '.kicad_sym':
                categorized['symbols'].append(file_path)
            elif file_ext == '.kicad_mod':
                categorized['footprints'].append(file_path)
            elif file_ext in ['.step', '.stp', '.stl', '.3d'] or '3d' in file_name:
                categorized['3d_models'].append(file_path)

        return categorized

    def add_symbol_to_library(self, symbol_file: Path, library_key: str) -> bool:
        """Add symbol to the specified library"""
        try:
            target_sym_file = self.lib_sym_path / self.libraries[library_key]['sym_file']

            # Read the symbol file content
            symbol_content = _read_kicad_text(symbol_file)[0].strip()

            # Extract symbols using the simple approach: everything between outer parentheses
            symbols_to_add = ""

            if symbol_content.startswith('(kicad_symbol_lib'):
                # This is a complete library file, extract everything between the outer parentheses
                # Find the first opening parenthesis after the library header
                first_paren = symbol_content.find('(symbol "')
                if first_paren == -1:
                    # No symbols found, might be an empty library
                    return True

                # Find the last closing parenthesis (end of the library)
                last_paren = symbol_content.rfind(')')
                if last_paren == -1:
                    return True

                # Extract everything between the first symbol and the last closing parenthesis
                symbols_to_add = symbol_content[first_paren:last_paren]

            else:
                # This might be a single symbol, use it as-is
                symbols_to_add = symbol_content

            # Read existing library content
            existing_content = ""
            eol = '\n'
            if target_sym_file.exists():
                existing_content, eol = _read_kicad_text(target_sym_file)
                existing_content = existing_content.strip()

            # Prepare the updated library content
            if existing_content and existing_content != EMPTY_SYMBOL_LIBRARY:
                # Library already exists and has content, add symbols before the closing parenthesis
                if existing_content.endswith(')'):
                    # Remove the closing parenthesis, add symbols, then add it back
                    content_without_close = existing_content[:-1]
                    updated_content = f"{content_without_close}\n{symbols_to_add}\n)"
                else:
                    # Fallback: just append
                    updated_content = f"{existing_content}\n{symbols_to_add}"
            else:
                # Create new library with proper structure
                updated_content = f"""(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
{symbols_to_add}
)"""

            # Write the updated content (keeping the library file's line endings)
            _write_kicad_text(target_sym_file, updated_content, eol)

            print(f"✓ Added symbol(s) from {symbol_file.name} to {library_key}")
            return True

        except Exception as e:
            print(f"✗ Error adding symbol {symbol_file.name}: {e}")
            return False

    def add_footprint_to_library(self, footprint_file: Path, library_key: str) -> bool:
        """Add footprint to the specified library"""
        try:
            target_fp_dir = self.lib_fp_path / self.libraries[library_key]['fp_dir']
            target_fp_dir.mkdir(parents=True, exist_ok=True)

            target_file = target_fp_dir / footprint_file.name
            shutil.copy2(footprint_file, target_file)

            print(f"✓ Added footprint {footprint_file.name} to {library_key}")
            return True

        except Exception as e:
            print(f"✗ Error adding footprint {footprint_file.name}: {e}")
            return False

    def add_3d_model(self, model_file: Path) -> bool:
        """Add 3D model to the model folder"""
        try:
            target_file = self.models_3d_path / model_file.name
            shutil.copy2(model_file, target_file)

            print(f"✓ Added 3D model {model_file.name}")
            return True

        except Exception as e:
            print(f"✗ Error adding 3D model {model_file.name}: {e}")
            return False

    def display_project_library_menu(self) -> None:
        """Display the project library selection menu"""
        print("\n" + "="*60)
        print("Project Library Integration")
        print("="*60)
        print("Select libraries to add to project settings:")
        print()

        for i, (key, lib_info) in enumerate(self.libraries.items(), 1):
            title = key.replace('_', ' ').title()
            print(f"{i:2d}. {title}: {lib_info['description']}" if lib_info['description'] else f"{i:2d}. {title}")

        print()
        print(" 0. Add all libraries")
        print("="*60)

    def get_project_library_selection(self) -> List[str]:
        """Get project library selection from user"""
        while True:
            try:
                choice = input(f"\nEnter your choice (0-{len(self.libraries)}, comma-separated for multiple): ").strip()

                if choice == "0":
                    return list(self.libraries.keys())

                # Parse comma-separated choices
                choices = [c.strip() for c in choice.split(',')]
                valid_choices = []

                for choice_str in choices:
                    choice_num = int(choice_str)
                    if 1 <= choice_num <= len(self.libraries):
                        valid_choices.append(list(self.libraries.keys())[choice_num - 1])
                    else:
                        print(f"Invalid choice: {choice_str}. Please enter numbers between 1 and {len(self.libraries)}")
                        break
                else:
                    # All choices were valid
                    return valid_choices

            except ValueError:
                print("Invalid input. Please enter numbers separated by commas.")
            # KeyboardInterrupt is NOT caught here - it propagates up

    def update_project_settings(self) -> bool:
        """Update project-specific library settings"""
        try:
            # Look for sym-lib-table and fp-lib-table in the project folder
            # (default: the folder that holds the library root)
            parent_dir = Path(self.config.project_dir)
            sym_lib_table = parent_dir / "sym-lib-table"
            fp_lib_table = parent_dir / "fp-lib-table"

            if not sym_lib_table.exists() or not fp_lib_table.exists():
                print("⚠ Project library tables not found. Skipping project integration.")
                return False

            # Display library selection menu
            self.display_project_library_menu()
            selected_libraries = self.get_project_library_selection()

            if not selected_libraries:
                print("No libraries selected. Skipping project integration.")
                return False

            print(f"\nSelected libraries: {', '.join(selected_libraries)}")

            # Add symbol libraries to sym-lib-table
            self._update_sym_lib_table(sym_lib_table, selected_libraries)

            # Add footprint libraries to fp-lib-table
            self._update_fp_lib_table(fp_lib_table, selected_libraries)

            print("✓ Updated project library settings")
            return True

        except Exception as e:
            print(f"✗ Error updating project settings: {e}")
            return False

    def library_uri(self, path: Path) -> str:
        """How a project's library table reaches ``path`` (a file or folder in the
        library): ``<library_mount>/<path in the library>``, the same mount the
        footprints' model paths use (``${KIPRJMOD}/...`` or ``${VAR}/...``)."""
        rel = Path(path).resolve().relative_to(self.base_path.resolve()).as_posix()
        return f"{self.config.library_mount}/{rel}"

    @staticmethod
    def _table_names(table_content: str) -> set:
        """Library names already in a sym-lib-table / fp-lib-table."""
        return {m.replace('\\"', '"') for m in re.findall(r'\(lib\s+\(name\s+"((?:[^"\\]|\\.)*)"\)', table_content)}

    def _update_lib_table(self, table: Path, selected_libraries: List[str], kind: str) -> None:
        """Add the selected category libraries to a project library table.

        kind is 'symbol' (sym-lib-table, <name>.kicad_sym) or 'footprint'
        (fp-lib-table, <name>.pretty). Libraries already listed by name are
        left alone; new entries go before the table's closing parenthesis."""
        is_sym = kind == 'symbol'
        try:
            table_content = ""
            if table.exists():
                with open(table, 'r', encoding='utf-8', newline='') as f:
                    table_content = f.read()
            eol = '\r\n' if '\r\n' in table_content else '\n'
            table_content = table_content.replace('\r\n', '\n')
            existing_entries = self._table_names(table_content)

            new_entries = []
            for lib_key in selected_libraries:
                lib_info = self.libraries[lib_key]
                lib_name = lib_info['name']
                if lib_name in existing_entries:
                    print(f"    - {kind.capitalize()} library already exists: {lib_name}")
                    continue
                target = self.lib_sym_path / lib_info['sym_file'] if is_sym else self.lib_fp_path / lib_info['fp_dir']
                uri = self.library_uri(target)
                descr = lib_info['description'].replace('\\', '\\\\').replace('"', '\\"')
                new_entries.append(f'  (lib (name "{lib_name}")(type "KiCad")(uri "{uri}")(options "")(descr "{descr}"))')
                print(f"    + Adding {kind} library: {lib_name}")

            if not new_entries:
                print(f"  - No new {kind} libraries to add")
                return
            if table_content.strip():
                # Insert the new entries before the line that closes the table
                lines = table_content.split('\n')
                last_closing_idx = -1
                for i in range(len(lines) - 1, -1, -1):
                    if ')' in lines[i] and not lines[i].strip().startswith('('):
                        last_closing_idx = i
                        break
                if last_closing_idx >= 0:
                    lines[last_closing_idx:last_closing_idx] = new_entries
                else:
                    lines.extend([''] + new_entries)
                text = '\n'.join(lines)
            else:
                head = 'sym_lib_table' if is_sym else 'fp_lib_table'
                text = f"({head}\n  (version 7)\n" + '\n'.join(new_entries) + "\n)\n"
            with open(table, 'w', encoding='utf-8', newline='') as f:
                f.write(text.replace('\n', eol))
            print(f"  ✓ Added {len(new_entries)} {kind} libraries to project")
        except Exception as e:
            print(f"  ✗ Error updating {kind} library table: {e}")

    def _update_sym_lib_table(self, sym_lib_table: Path, selected_libraries: List[str]) -> None:
        """Update symbol library table"""
        self._update_lib_table(sym_lib_table, selected_libraries, 'symbol')

    def _update_fp_lib_table(self, fp_lib_table: Path, selected_libraries: List[str]) -> None:
        """Update footprint library table"""
        self._update_lib_table(fp_lib_table, selected_libraries, 'footprint')

    def _git(self, *args):
        """Run one git command in the library root. Its output is captured and
        printed through print(), so it lands in order with the tool's own lines
        (and on stderr with --json, keeping stdout for the JSON report)."""
        r = subprocess.run(['git'] + list(args), cwd=self.base_path, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        for out in (r.stdout, r.stderr):
            if out and out.strip():
                print(out.rstrip())
        if r.returncode:
            raise subprocess.CalledProcessError(r.returncode, ['git'] + list(args))
        return r

    def commit_changes(self, message: str) -> bool:
        """Stage everything under the library root (`git add .`) and commit it
        with ``message`` (after the configured git_message_prefix)."""
        try:
            # Stage all changes
            self._git('add', '.')

            commit_msg = self._commit_message(message)

            # Commit changes
            self._git('commit', '-m', commit_msg)

            print(f"✓ Committed changes: {commit_msg}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"✗ Error committing changes: {e}")
            return False
        except FileNotFoundError:
            print("✗ Git not found. Please ensure git is installed and the directory is a git repository.")
            return False

    def push_changes(self) -> bool:
        """Push changes to remote repository (only ever called for --push)"""
        try:
            self._git('push')
            print("✓ Pushed changes to remote repository")
            return True

        except subprocess.CalledProcessError as e:
            print(f"✗ Error pushing changes: {e}")
            return False
        except FileNotFoundError:
            print("✗ Git not found. Please ensure git is installed.")
            return False

    def initialize_libraries(self) -> bool:
        """Initialize empty library files (and the library folders) if they don't exist"""
        try:
            print("Initializing library files...")

            for folder in (self.lib_sym_path, self.lib_fp_path, self.models_3d_path):
                folder.mkdir(parents=True, exist_ok=True)

            # Initialize symbol libraries
            for lib_key, lib_info in self.libraries.items():
                sym_file = self.lib_sym_path / lib_info['sym_file']
                if not sym_file.exists():
                    # Create empty symbol library with proper structure
                    with open(sym_file, 'w', encoding='utf-8') as f:
                        f.write(EMPTY_SYMBOL_LIBRARY)
                    print(f"  ✓ Created symbol library: {lib_info['sym_file']}")
                else:
                    print(f"  - Symbol library already exists: {lib_info['sym_file']}")

            # Initialize footprint library directories
            for lib_key, lib_info in self.libraries.items():
                fp_dir = self.lib_fp_path / lib_info['fp_dir']
                if not fp_dir.exists():
                    fp_dir.mkdir(parents=True, exist_ok=True)
                    print(f"  ✓ Created footprint directory: {lib_info['fp_dir']}")
                else:
                    print(f"  - Footprint directory already exists: {lib_info['fp_dir']}")

            print("✓ Library initialization complete")
            return True

        except Exception as e:
            print(f"✗ Error initializing libraries: {e}")
            return False

    def ask_delete_zip_file(self, zip_path: str) -> None:
        """Ask user if they want to delete the zip file after processing"""
        try:
            zip_file = Path(zip_path)
            if not zip_file.exists():
                return

            print("\n" + "="*60)
            print("Cleanup")
            print("="*60)
            print(f"Zip file: {zip_file.name}")
            print(f"Location: {zip_file}")
            print()

            while True:
                try:
                    choice = input("Delete the zip file? (y/n): ").strip().lower()
                    if choice in ['y', 'yes']:
                        zip_file.unlink()
                        print(f"✓ Deleted {zip_file.name}")
                        break
                    elif choice in ['n', 'no']:
                        print(f"✓ Kept {zip_file.name}")
                        break
                    else:
                        print("Please enter 'y' for yes or 'n' for no")
                except KeyboardInterrupt:
                    print(f"\n⚠ Keeping {zip_file.name}")
                    break

        except Exception as e:
            print(f"✗ Error handling zip file deletion: {e}")

    def extract_symbol_info(self, symbol_content: str) -> Dict[str, str]:
        """Extract symbol information including datasheet and footprint"""
        info = {
            'name': '',
            'datasheet': '',
            'footprint': '',
            'content': symbol_content
        }

        lines = symbol_content.split('\n')
        for i, line in enumerate(lines):
            # Extract symbol name
            if line.strip().startswith('(symbol "'):
                name_start = line.find('"') + 1
                name_end = line.find('"', name_start)
                if name_start > 0 and name_end > name_start:
                    info['name'] = line[name_start:name_end]

            # Extract datasheet URL
            elif 'property "Datasheet"' in line:
                # Look for the URL in the current line
                if 'http' in line:
                    url_start = line.find('http')
                    if url_start != -1:
                        # Find the end of the URL (before closing quote or parenthesis)
                        url_end = line.find('"', url_start)
                        if url_end == -1:
                            url_end = line.find(')', url_start)
                        if url_end != -1:
                            info['datasheet'] = line[url_start:url_end]

            # Extract footprint
            elif 'property "Footprint"' in line:
                # Look for footprint name in quotes in current line
                if '"' in line:
                    # Find the second quote (after "Footprint")
                    first_quote = line.find('"')
                    if first_quote != -1:
                        second_quote = line.find('"', first_quote + 1)
                        if second_quote != -1:
                            third_quote = line.find('"', second_quote + 1)
                            if third_quote != -1:
                                fourth_quote = line.find('"', third_quote + 1)
                                if fourth_quote != -1:
                                    info['footprint'] = line[third_quote + 1:fourth_quote]

        return info

    def find_footprint_file(self, footprint_name: str) -> Optional[Path]:
        """Find footprint file by name in existing footprint libraries"""
        # Search in all existing footprint directories
        for fp_dir in self.lib_fp_path.iterdir():
            if fp_dir.is_dir() and fp_dir.name.endswith('.pretty'):
                for fp_file in fp_dir.glob('*.kicad_mod'):
                    if fp_file.stem == footprint_name:
                        return fp_file
        return None

    def migrate_symbols(self) -> bool:
        """Migrate symbols from existing .kicad_sym files to categorized libraries"""
        migrated_count = 0
        try:
            print("Symbol Migration Tool")
            print("="*60)

            # Find all .kicad_sym files in the symbol directory
            sym_files = list(self.lib_sym_path.glob('*.kicad_sym'))

            # Filter out the new categorized libraries
            exclude_files = {lib_info['sym_file'] for lib_info in self.libraries.values()}
            source_files = [f for f in sym_files if f.name not in exclude_files]

            if not source_files:
                print("No source symbol files found to migrate.")
                return True

            print(f"Found {len(source_files)} source symbol files:")
            for i, file in enumerate(source_files, 1):
                print(f"  {i}. {file.name}")

            for source_file in source_files:
                try:
                    print("\n" + "="*60)
                    print(f"Processing: {source_file.name}")
                    print("="*60)

                    # Read and parse the source file
                    with open(source_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()

                    if not content.startswith('(kicad_symbol_lib'):
                        print(f"  ⚠ Skipping {source_file.name} - not a valid symbol library")
                        continue

                    # Extract individual symbols
                    symbols = self.extract_symbols_from_library(content)

                    if not symbols:
                        print(f"  - No symbols found in {source_file.name}")
                        continue

                    print(f"  Found {len(symbols)} symbol(s)")

                    # Process each symbol
                    for symbol_content in symbols:
                        try:
                            symbol_info = self.extract_symbol_info(symbol_content)

                            if not symbol_info['name']:
                                print("  ⚠ Skipping symbol - no name found")
                                continue

                            # Display library selection menu
                            self.display_library_menu(symbol_info['name'], symbol_info['datasheet'], symbol_info['footprint'])
                            selected_library = self.get_library_selection()

                            if selected_library is None:
                                print(f"  - Skipping {symbol_info['name']}")
                                continue

                            # Add symbol to selected library
                            if self.add_symbol_to_library_direct(symbol_content, selected_library):
                                print(f"  ✓ Added {symbol_info['name']} to {selected_library}")

                                # Handle footprint if specified
                                if symbol_info['footprint']:
                                    self.migrate_footprint(symbol_info['footprint'], selected_library)

                                migrated_count += 1
                            else:
                                print(f"  ✗ Failed to add {symbol_info['name']}")

                        except KeyboardInterrupt:
                            print("\n\n⚠ Stopping migration (Ctrl+C)")
                            raise  # Re-raise to break out of file loop
                        except Exception as e:
                            print(f"  ✗ Error processing symbol: {e}")
                            continue

                except KeyboardInterrupt:
                    print("  Finished processing current file, stopping...")
                    break  # Break out of files loop
                except Exception as e:
                    print(f"  ✗ Error processing file {source_file.name}: {e}")
                    continue

            print("\n" + "="*60)
            print("Migration Complete")
            print("="*60)
            print(f"✓ Migrated {migrated_count} symbol(s)")

            return True

        except KeyboardInterrupt:
            print("\n⚠ Migration interrupted by user")
            print(f"✓ Migrated {migrated_count} symbol(s) before interruption")
            return True
        except Exception as e:
            print(f"✗ Error during migration: {e}")
            return False

    def migrate_single_file(self, file_path: str) -> bool:
        """Migrate symbols from a single .kicad_sym file"""
        migrated_count = 0
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                print(f"Error: File '{file_path}' not found")
                return False

            if not file_path.suffix.lower() == '.kicad_sym':
                print(f"Error: File '{file_path}' is not a .kicad_sym file")
                return False

            print("Single File Migration Tool")
            print("="*60)
            print(f"Processing: {file_path.name}")
            print("="*60)

            # Read and parse the source file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            if not content.startswith('(kicad_symbol_lib'):
                print(f"  ⚠ Skipping {file_path.name} - not a valid symbol library")
                return False

            # Extract individual symbols
            symbols = self.extract_symbols_from_library(content)

            if not symbols:
                print(f"  - No symbols found in {file_path.name}")
                return True

            print(f"  Found {len(symbols)} symbol(s)")

            # Process each symbol
            for symbol_content in symbols:
                try:
                    symbol_info = self.extract_symbol_info(symbol_content)

                    if not symbol_info['name']:
                        print("  ⚠ Skipping symbol - no name found")
                        continue

                    # Display library selection menu
                    self.display_library_menu(symbol_info['name'], symbol_info['datasheet'], symbol_info['footprint'])
                    selected_library = self.get_library_selection()

                    if selected_library is None:
                        print(f"  - Skipping {symbol_info['name']}")
                        continue

                    # Add symbol to selected library
                    if self.add_symbol_to_library_direct(symbol_content, selected_library):
                        print(f"  ✓ Added {symbol_info['name']} to {selected_library}")

                        # Handle footprint if specified
                        if symbol_info['footprint']:
                            self.migrate_footprint(symbol_info['footprint'], selected_library)

                        migrated_count += 1
                    else:
                        print(f"  ✗ Failed to add {symbol_info['name']}")

                except KeyboardInterrupt:
                    print("\n\n⚠ Stopping migration (Ctrl+C)")
                    break  # Break out of symbols loop
                except Exception as e:
                    print(f"  ✗ Error processing symbol: {e}")
                    continue

            print("\n" + "="*60)
            print("Migration Complete")
            print("="*60)
            print(f"✓ Migrated {migrated_count} symbol(s)")

            return True

        except KeyboardInterrupt:
            print("\n⚠ Migration interrupted by user")
            print(f"✓ Migrated {migrated_count} symbol(s) before interruption")
            return True
        except Exception as e:
            print(f"✗ Error during migration: {e}")
            return False

    def extract_symbols_from_library(self, content: str) -> List[str]:
        """Extract individual symbols from a library file"""
        symbols = []

        # Find all top-level symbol starts (indented with single tab, not double tab)
        symbol_starts = []
        lines = content.split('\n')
        for i, line in enumerate(lines):
            # Match symbols that are indented with exactly one tab (top-level symbols)
            if line.strip().startswith('(symbol "') and line.startswith('\t') and not line.startswith('\t\t'):
                symbol_starts.append(i)

        # Extract each symbol
        for i, start_line in enumerate(symbol_starts):
            # Find the end of this symbol
            end_line = start_line
            paren_count = 0
            in_symbol = False

            for j in range(start_line, len(lines)):
                line = lines[j]

                # Count parentheses
                for char in line:
                    if char == '(':
                        paren_count += 1
                        if '(symbol "' in line and line.startswith('\t') and not line.startswith('\t\t'):
                            in_symbol = True
                    elif char == ')':
                        paren_count -= 1
                        if in_symbol and paren_count == 0:
                            end_line = j
                            break

                if in_symbol and paren_count == 0:
                    break

            # Extract the symbol content
            symbol_lines = lines[start_line:end_line + 1]
            symbol_content = '\n'.join(symbol_lines)
            symbols.append(symbol_content)

        return symbols

    def add_symbol_to_library_direct(self, symbol_content: str, library_key: str) -> bool:
        """Add symbol directly to library (for migration)"""
        try:
            target_sym_file = self.lib_sym_path / self.libraries[library_key]['sym_file']

            # Read existing library content
            existing_content = ""
            eol = '\n'
            if target_sym_file.exists():
                existing_content, eol = _read_kicad_text(target_sym_file)
                existing_content = existing_content.strip()

            # Prepare the updated library content
            if existing_content and existing_content != EMPTY_SYMBOL_LIBRARY:
                # Library already exists and has content, add symbol before the closing parenthesis
                if existing_content.endswith(')'):
                    content_without_close = existing_content[:-1]
                    updated_content = f"{content_without_close}\n{symbol_content}\n)"
                else:
                    updated_content = f"{existing_content}\n{symbol_content}"
            else:
                # Create new library with proper structure
                updated_content = f"""(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
{symbol_content}
)"""

            # Write the updated content (keeping the library file's line endings)
            _write_kicad_text(target_sym_file, updated_content, eol)

            return True

        except Exception as e:
            print(f"  ✗ Error adding symbol: {e}")
            return False

    def migrate_footprint(self, footprint_name: str, library_key: str) -> None:
        """Migrate footprint to the appropriate library directory"""
        try:
            # Find the footprint file
            footprint_file = self.find_footprint_file(footprint_name)

            if not footprint_file:
                print(f"    ⚠ Footprint {footprint_name} not found")
                return

            # Copy to target library directory
            target_fp_dir = self.lib_fp_path / self.libraries[library_key]['fp_dir']
            target_fp_dir.mkdir(parents=True, exist_ok=True)

            target_file = target_fp_dir / footprint_file.name
            shutil.copy2(footprint_file, target_file)

            print(f"    ✓ Moved footprint {footprint_name} to {library_key}")

        except Exception as e:
            print(f"    ✗ Error migrating footprint {footprint_name}: {e}")

    def parse_lib_table(self, lib_table_path: Path) -> Dict[str, str]:
        """Parse a lib-table file and return mapping of library name to URI"""
        lib_map = {}
        try:
            if not lib_table_path.exists():
                return lib_map

            with open(lib_table_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse each library entry
            # Format: (lib (name "LibName")(type "KiCad")(uri "path/to/lib")(options "")(descr ""))
            lib_pattern = r'\(lib\s+\(name\s+"([^"]+)"\)\s*\(type\s+"([^"]+)"\)\s*\(uri\s+"([^"]+)"\)'
            matches = re.findall(lib_pattern, content)

            for name, lib_type, uri in matches:
                lib_map[name] = uri

            return lib_map

        except Exception as e:
            print(f"Error parsing {lib_table_path}: {e}")
            return lib_map

    def extract_schematic_components(self, schematic_path: Path) -> List[Dict[str, str]]:
        """Extract all symbol and footprint references from a schematic file (skipping lib_symbols section)"""
        components = []

        try:
            with open(schematic_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Skip the lib_symbols section - find where it starts and ends
            content_without_lib_symbols = self._remove_lib_symbols_section(content)

            # Find all symbol instances at top level (1 tab indentation)
            # These are the actual placed components, not the embedded definitions
            # Pattern matches symbol blocks that start with single tab
            lines = content_without_lib_symbols.split('\n')

            current_symbol = []
            in_symbol = False
            paren_depth = 0
            seen_lib_ids = set()

            for line in lines:
                # Check for symbol start at 1 level of indentation (single tab)
                if line.startswith('\t(symbol') and not line.startswith('\t\t'):
                    in_symbol = True
                    current_symbol = [line]
                    paren_depth = line.count('(') - line.count(')')
                elif in_symbol:
                    current_symbol.append(line)
                    paren_depth += line.count('(') - line.count(')')

                    if paren_depth <= 0:
                        # End of symbol block
                        symbol_text = '\n'.join(current_symbol)

                        # Extract lib_id
                        lib_id_match = re.search(r'\(lib_id\s+"([^"]+)"\)', symbol_text)
                        if lib_id_match:
                            lib_id = lib_id_match.group(1)

                            if lib_id not in seen_lib_ids:
                                seen_lib_ids.add(lib_id)

                                # Parse library:symbol format
                                if ':' in lib_id:
                                    lib_name, sym_name = lib_id.split(':', 1)
                                else:
                                    lib_name = lib_id
                                    sym_name = lib_id

                                # Extract footprint from this symbol instance
                                footprint = self._find_footprint_in_symbol_block(symbol_text)

                                components.append({
                                    'lib_id': lib_id,
                                    'lib_name': lib_name,
                                    'sym_name': sym_name,
                                    'footprint': footprint
                                })

                        in_symbol = False
                        current_symbol = []

            return components

        except Exception as e:
            print(f"Error extracting components from {schematic_path}: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _remove_lib_symbols_section(self, content: str) -> str:
        """Remove the lib_symbols section from schematic content"""
        lines = content.split('\n')
        result_lines = []
        in_lib_symbols = False
        paren_depth = 0

        for line in lines:
            if '\t(lib_symbols' in line and not in_lib_symbols:
                in_lib_symbols = True
                paren_depth = line.count('(') - line.count(')')
                continue

            if in_lib_symbols:
                paren_depth += line.count('(') - line.count(')')
                if paren_depth <= 0:
                    in_lib_symbols = False
                continue

            result_lines.append(line)

        return '\n'.join(result_lines)

    def _find_footprint_in_symbol_block(self, symbol_text: str) -> str:
        """Find the footprint property within a symbol instance block"""
        # Look for (property "Footprint" "value" ...) in the symbol block
        match = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', symbol_text)
        if match:
            return match.group(1)
        return ""

    def resolve_library_path(self, uri: str, project_dir: Path) -> Path:
        """Resolve library URI to actual file path"""
        # Replace ${KIPRJMOD} with project directory
        resolved = uri.replace('${KIPRJMOD}', str(project_dir))
        return Path(resolved)

    def read_symbol_from_library(self, sym_lib_path: Path, symbol_name: str) -> Optional[str]:
        """Read a specific symbol from a symbol library file"""
        try:
            if not sym_lib_path.exists():
                return None

            with open(sym_lib_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract the symbol definition
            symbols = self.extract_symbols_from_library(content)

            for symbol_content in symbols:
                # Check if this is the symbol we're looking for
                if f'(symbol "{symbol_name}"' in symbol_content:
                    return symbol_content

            return None

        except Exception as e:
            print(f"Error reading symbol from {sym_lib_path}: {e}")
            return None

    def read_footprint_from_library(self, fp_lib_path: Path, footprint_name: str) -> Optional[Tuple[str, Path]]:
        """Read a specific footprint from a footprint library directory"""
        try:
            if not fp_lib_path.exists():
                return None

            # Footprint libraries are directories with .kicad_mod files
            fp_file = fp_lib_path / f"{footprint_name}.kicad_mod"
            if fp_file.exists():
                with open(fp_file, 'r', encoding='utf-8') as f:
                    return f.read(), fp_file

            # Try to find footprint with different naming
            for mod_file in fp_lib_path.glob('*.kicad_mod'):
                if mod_file.stem == footprint_name:
                    with open(mod_file, 'r', encoding='utf-8') as f:
                        return f.read(), mod_file

            return None

        except Exception as e:
            print(f"Error reading footprint from {fp_lib_path}: {e}")
            return None

    def custom_schematic_components(self, components: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """The components a schematic migration considers: not from a stock KiCad
        library, and not already in a category library (by name or prefix)."""
        standard_libs = set(self.config.stock_symbol_libraries)
        category_names = {lib_info['sym_file'].replace('.kicad_sym', '') for lib_info in self.libraries.values()}
        prefix = self.config.library_prefix
        return [
            c for c in components
            if c['lib_name'] not in standard_libs
            and c['lib_name'] not in category_names
            and not (prefix and c['lib_name'].startswith(prefix))  # any library with the category prefix
        ]

    def migrate_schematic(self, schematic_path: str) -> bool:
        """Migrate symbols and footprints from a schematic to categorized libraries"""
        migrations = []
        migrated_count = 0
        try:
            schematic_path = Path(schematic_path)

            if not schematic_path.exists():
                print(f"Error: Schematic file '{schematic_path}' not found")
                return False

            if not schematic_path.suffix.lower() == '.kicad_sch':
                print(f"Error: File '{schematic_path}' is not a .kicad_sch file")
                return False

            print("\n" + "="*70)
            print("Schematic Migration Tool")
            print("="*70)
            print(f"Processing: {schematic_path.name}")
            print("="*70)

            # Get project directory (parent of schematic or where lib tables are)
            project_dir = schematic_path.parent

            # Read library tables from project directory
            sym_lib_table_path = project_dir / "sym-lib-table"
            fp_lib_table_path = project_dir / "fp-lib-table"

            if not sym_lib_table_path.exists():
                print(f"⚠ Symbol library table not found: {sym_lib_table_path}")
            if not fp_lib_table_path.exists():
                print(f"⚠ Footprint library table not found: {fp_lib_table_path}")

            # Parse library tables
            print("\nReading library tables...")
            sym_lib_map = self.parse_lib_table(sym_lib_table_path)
            fp_lib_map = self.parse_lib_table(fp_lib_table_path)

            print(f"  Found {len(sym_lib_map)} symbol libraries")
            print(f"  Found {len(fp_lib_map)} footprint libraries")

            # Extract components from schematic
            print("\nExtracting components from schematic...")
            components = self.extract_schematic_components(schematic_path)

            if not components:
                print("  No custom components found to migrate.")
                return True

            print(f"  Found {len(components)} unique symbol references")

            # Filter out standard KiCad libraries (Device, power, Connector, etc.)
            # and components already in a category library
            custom_components = self.custom_schematic_components(components)

            if not custom_components:
                print("  No custom components found to migrate (all are either standard KiCad or already in a category library).")
                return True

            print(f"  Found {len(custom_components)} custom components to consider for migration")

            # Process each component
            for component in custom_components:
                try:
                    lib_id = component['lib_id']
                    lib_name = component['lib_name']
                    sym_name = component['sym_name']
                    footprint = component['footprint']

                    print("\n" + "-"*60)
                    print(f"Component: {lib_id}")
                    print("-"*60)

                    # Get symbol library path
                    sym_uri = sym_lib_map.get(lib_name, '')
                    if sym_uri:
                        sym_lib_path = self.resolve_library_path(sym_uri, project_dir)
                        print(f"  Symbol library: {sym_lib_path}")
                    else:
                        print(f"  ⚠ Symbol library '{lib_name}' not found in sym-lib-table")
                        sym_lib_path = None

                    # Get footprint library path
                    fp_lib_name = ''
                    fp_name = ''
                    if footprint and ':' in footprint:
                        fp_lib_name, fp_name = footprint.split(':', 1)
                    elif footprint:
                        fp_lib_name = footprint
                        fp_name = footprint

                    fp_uri = fp_lib_map.get(fp_lib_name, '') if fp_lib_name else ''
                    if fp_uri:
                        fp_lib_path = self.resolve_library_path(fp_uri, project_dir)
                        print(f"  Footprint library: {fp_lib_path}")
                        print(f"  Footprint: {fp_name}")
                    else:
                        if fp_lib_name:
                            print(f"  ⚠ Footprint library '{fp_lib_name}' not found in fp-lib-table")
                        fp_lib_path = None

                    # Display library selection menu
                    self.display_library_menu(sym_name, '', footprint)
                    selected_library = self.get_library_selection()

                    if selected_library is None:
                        print(f"  - Skipping {sym_name}")
                        continue

                    # Migrate symbol
                    if sym_lib_path and sym_lib_path.exists():
                        symbol_content = self.read_symbol_from_library(sym_lib_path, sym_name)
                        if symbol_content:
                            if self.add_symbol_to_library_direct(symbol_content, selected_library):
                                print(f"  ✓ Migrated symbol {sym_name} to {selected_library}")
                            else:
                                print(f"  ✗ Failed to migrate symbol {sym_name}")
                        else:
                            print(f"  ⚠ Could not read symbol {sym_name} from source library")

                    # Migrate footprint
                    if fp_lib_path and fp_lib_path.exists() and fp_name:
                        fp_result = self.read_footprint_from_library(fp_lib_path, fp_name)
                        if fp_result:
                            fp_content, fp_source = fp_result
                            target_fp_dir = self.lib_fp_path / self.libraries[selected_library]['fp_dir']
                            target_fp_dir.mkdir(parents=True, exist_ok=True)
                            target_fp_file = target_fp_dir / f"{fp_name}.kicad_mod"

                            with open(target_fp_file, 'w', encoding='utf-8') as f:
                                f.write(fp_content)

                            print(f"  ✓ Migrated footprint {fp_name} to {selected_library}")
                        else:
                            print(f"  ⚠ Could not read footprint {fp_name} from source library")

                    # Record migration for schematic update
                    new_sym_lib = self.libraries[selected_library]['sym_file'].replace('.kicad_sym', '')
                    new_fp_lib = self.libraries[selected_library]['fp_dir'].replace('.pretty', '')

                    migrations.append({
                        'old_lib_id': lib_id,
                        'new_lib_id': f"{new_sym_lib}:{sym_name}",
                        'old_footprint': footprint,
                        'new_footprint': f"{new_fp_lib}:{fp_name}" if fp_name else ''
                    })

                    migrated_count += 1

                except KeyboardInterrupt:
                    print("\n\n⚠ Stopping migration (Ctrl+C) - will update schematic with completed migrations...")
                    break  # Break out of component loop, continue to update schematic
                except Exception as e:
                    print(f"  ✗ Error processing component {component.get('lib_id', 'unknown')}: {e}")
                    continue

            # Update schematic file
            if migrations:
                print("\n" + "="*70)
                print("Updating schematic file...")
                print("="*70)

                if self._update_schematic_references(schematic_path, migrations):
                    print("✓ Updated schematic references")
                else:
                    print("⚠ Failed to update some schematic references")

            print("\n" + "="*70)
            print("Migration Complete")
            print("="*70)
            print(f"✓ Migrated {migrated_count} component(s)")

            return True

        except KeyboardInterrupt:
            print("\n⚠ Migration interrupted by user")
            # Still update schematic with whatever was migrated
            if migrations:
                print(f"\nUpdating schematic with {len(migrations)} completed migration(s)...")
                if self._update_schematic_references(schematic_path, migrations):
                    print("✓ Updated schematic references")
                else:
                    print("⚠ Failed to update some schematic references")
            print(f"✓ Migrated {migrated_count} component(s) before interruption")
            return True
        except Exception as e:
            print(f"✗ Error during schematic migration: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _update_schematic_references(self, schematic_path: Path, migrations: List[Dict[str, str]]) -> bool:
        """Update schematic file with new library references (including lib_symbols section)"""
        try:
            with open(schematic_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content

            for migration in migrations:
                old_lib_id = migration['old_lib_id']
                new_lib_id = migration['new_lib_id']
                old_footprint = migration['old_footprint']
                new_footprint = migration['new_footprint']

                # Update lib_id references in symbol instances
                if old_lib_id and new_lib_id:
                    content = content.replace(f'(lib_id "{old_lib_id}")', f'(lib_id "{new_lib_id}")')
                    # Also update the symbol definition name in lib_symbols section
                    content = content.replace(f'(symbol "{old_lib_id}"', f'(symbol "{new_lib_id}"')

                # Update footprint references
                if old_footprint and new_footprint:
                    content = content.replace(f'"Footprint" "{old_footprint}"', f'"Footprint" "{new_footprint}"')

            # Only write if changes were made
            if content != original_content:
                # Create backup
                backup_path = schematic_path.with_suffix('.kicad_sch.bak')
                shutil.copy2(schematic_path, backup_path)
                print(f"  Created backup: {backup_path.name}")

                with open(schematic_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                return True
            else:
                print("  No changes needed in schematic file")
                return True

        except Exception as e:
            print(f"Error updating schematic: {e}")
            return False

    def process_zip_file(self, zip_path: str, add_to_project: bool = False,
                         commit: bool = False, push: bool = False) -> None:
        """Main method to process a zip file"""
        print(f"Processing zip file: {zip_path}")

        # Extract zip contents
        temp_dir, extracted_files = self.extract_zip_contents(zip_path)

        try:
            # Categorize files
            categorized_files = self.categorize_files(extracted_files)

            print("\nFound files:")
            print(f"  - Symbols: {len(categorized_files['symbols'])}")
            print(f"  - Footprints: {len(categorized_files['footprints'])}")
            print(f"  - 3D Models: {len(categorized_files['3d_models'])}")

            if not any(categorized_files.values()):
                print("No KiCad files found in the zip archive.")
                return

            # Display library selection menu
            self.display_library_menu()
            selected_library = self.get_library_selection()

            if selected_library is None:
                print("Skipping library addition.")
                return

            print(f"\nSelected library: {selected_library}")

            # Process files
            success_count = 0
            total_files = len(categorized_files['symbols']) + len(categorized_files['footprints']) + len(categorized_files['3d_models'])

            # Add symbols to library
            for symbol_file in categorized_files['symbols']:
                if self.add_symbol_to_library(symbol_file, selected_library):
                    success_count += 1

            # Add footprints to library
            for footprint_file in categorized_files['footprints']:
                if self.add_footprint_to_library(footprint_file, selected_library):
                    success_count += 1

            # Add 3D models
            for model_file in categorized_files['3d_models']:
                if self.add_3d_model(model_file):
                    success_count += 1

            print(f"\n✓ Successfully processed {success_count}/{total_files} files")

            # Update project settings if requested
            if add_to_project:
                self.update_project_settings()

            # Commit changes if requested
            if commit:
                self.commit_changes(f"Add components from {Path(zip_path).name}")

            # Push changes if requested
            if push:
                self.push_changes()

            # Ask if user wants to delete the zip file
            self.ask_delete_zip_file(zip_path)

        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Zip import with a plan: no prompts unless interactive, --dry-run,
    # --json, refusals before any write, optional 3D-model linking.
    # Used when any of these options is given; a bare
    # `kicad-part-importer part.zip` still runs process_zip_file above.
    # ------------------------------------------------------------------

    def resolve_category(self, value: str) -> Optional[str]:
        """Accept a category key ('power_management'), its library name
        ('lib_power_management' with the default prefix) or its menu number ('5')."""
        if value is None:
            return None
        v = value.strip()
        keys = list(self.libraries.keys())
        if v.isdigit() and 1 <= int(v) <= len(keys):
            return keys[int(v) - 1]
        if v in self.libraries:
            return v
        for key, info in self.libraries.items():
            if info['name'] == v:
                return key
        prefix = self.config.library_prefix
        if prefix and v.startswith(prefix):
            v = v[len(prefix):]
        return v if v in self.libraries else None

    def _rel(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.base_path.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _library_symbol_names(self) -> Dict[str, List[str]]:
        """Symbol names per category library key."""
        out = {}
        for key, info in self.libraries.items():
            p = self.lib_sym_path / info['sym_file']
            out[key] = _top_level_symbol_names(_read_kicad_text(p)[0]) if p.exists() else []
        return out

    def plan_zip_import(self, extracted: Path, library_key: str, link_3d: bool = False,
                        overwrite: bool = False, model_prefix: Optional[str] = None) -> Dict:
        """Read everything, decide every write, refuse conflicts. Writes nothing.

        model_prefix defaults to the configured one."""
        if model_prefix is None:
            model_prefix = self.config.model_prefix
        model_dir = self.config.model_dir
        files = sorted(p for p in Path(extracted).rglob('*') if p.is_file())
        sym_files = [p for p in files if p.suffix.lower() == '.kicad_sym']
        fp_files = [p for p in files if p.suffix.lower() == '.kicad_mod']
        model_files = [p for p in files if lib3d.is_model_file(p)]
        ignored = [p.relative_to(extracted).as_posix() for p in files
                   if p not in sym_files and p not in fp_files and p not in model_files]
        lib = self.libraries[library_key]
        lib_name = lib['name']
        fp_dir = self.lib_fp_path / lib['fp_dir']
        plan = {'category': library_key, 'symbols': [], 'footprints': [], 'models': [],
                'ignored_files': ignored, 'warnings': [], 'errors': []}
        for kind, group in (('footprint', fp_files), ('3D model', model_files)):
            names = [p.name.lower() for p in group]
            for dup in sorted({n for n in names if names.count(n) > 1}):
                plan['errors'].append("the zip holds two %s files named %s" % (kind, dup))

        # Symbols: refuse a name the target library already has (appending it
        # again would leave two symbols of one name in the library).
        existing = self._library_symbol_names()
        seen = set()
        for sf in sym_files:
            text = _read_kicad_text(sf)[0]
            names = _top_level_symbol_names(text)
            fp_props = re.findall(r'\(property\s+"Footprint"\s+"([^"]*)"', text)
            for i, name in enumerate(names):
                row = {'name': name, 'source': sf.relative_to(extracted).as_posix(),
                       'target': self._rel(self.lib_sym_path / lib['sym_file']), 'action': 'append',
                       'footprint_field': fp_props[i] if i < len(fp_props) else None}
                if name in existing.get(library_key, []) or name in seen:
                    row['action'] = 'refused'
                    plan['errors'].append("symbol %s already exists in %s (remove or rename it first)" % (name, lib_name))
                for other, onames in existing.items():
                    if other != library_key and name in onames:
                        plan['warnings'].append("symbol %s also exists in %s" % (name, self.libraries[other]['name']))
                fpf = row['footprint_field']
                if fpf and ':' not in fpf:
                    plan['warnings'].append("symbol %s: Footprint field '%s' has no library prefix (KiCad needs %s:%s)"
                                            % (name, fpf, lib_name, fpf))
                elif fpf and fpf.split(':', 1)[0] != lib_name:
                    plan['warnings'].append("symbol %s: Footprint field '%s' names library '%s', not %s"
                                            % (name, fpf, fpf.split(':', 1)[0], lib_name))
                seen.add(name)
                plan['symbols'].append(row)
            if not names:
                plan['warnings'].append("%s holds no symbols" % sf.name)

        # Models: same name in the model folder -> reuse if identical, else
        # refuse unless --overwrite (the prompting import overwrites silently).
        model_target_name = {}
        for mf in model_files:
            spelled = lib3d.spelling_in(self.models_3d_path, mf.name)
            target = self.models_3d_path / (spelled or mf.name)
            row = {'name': mf.name, 'source': mf.relative_to(extracted).as_posix(),
                   'target': self._rel(target), 'action': 'add'}
            if spelled:
                if target.read_bytes() == mf.read_bytes():
                    row['action'] = 'identical'
                elif overwrite:
                    row['action'] = 'replace'
                else:
                    row['action'] = 'refused'
                    plan['errors'].append("%s/%s exists with different content (use --overwrite to replace)"
                                          % (model_dir, spelled))
            model_target_name[mf.name] = spelled or mf.name
            plan['models'].append(row)
        zip_models = sorted(model_target_name)

        # Footprints (+ model links)
        for ff in fp_files:
            text = lib3d.read_text(ff)
            new_text = text
            target = fp_dir / ff.name
            row = {'name': ff.stem, 'source': ff.relative_to(extracted).as_posix(),
                   'target': self._rel(target), 'action': 'add', 'model': None}
            declared = lib3d.footprint_name(text)
            if declared and declared != ff.stem:
                plan['warnings'].append("footprint file %s declares the name '%s'" % (ff.name, declared))
            for other in self._category_pretty_dirs():
                if other != fp_dir and (other / ff.name).is_file():
                    plan['warnings'].append("footprint %s also exists in %s" % (ff.stem, other.name))
            if link_3d:
                refs = lib3d.model_refs(text)
                choice, rule = lib3d.match_model(ff.stem, refs, zip_models)
                m = {'before': refs, 'after': refs, 'action': 'keep', 'rule': rule}
                if choice:
                    path = lib3d.model_ref_for(model_target_name[choice], model_prefix)
                    named = [r for r in refs if lib3d.model_basename(r).lower() == choice.lower()]
                    if refs and not named:
                        plan['warnings'].append("footprint %s names %s, not %s; left as is"
                                                % (ff.stem, ', '.join(refs), choice))
                    else:
                        new_text, m['action'] = lib3d.set_model_path(
                            text, path, replace=lambda o, c=choice: lib3d.model_basename(o).lower() == c.lower())
                else:
                    # No model in the zip: point at the model folder if the file is already there.
                    for r in refs:
                        kind, found = lib3d.classify_ref(r, self.config)
                        if kind in ('case', 'bare', 'absolute', 'other-var') and found:
                            new_text, act = lib3d.fix_ref(new_text, r, self.config.library_mount + '/' + found)
                            if act != 'keep':
                                m['action'] = act
                        elif kind != 'ok' and kind != 'stock':
                            plan['warnings'].append("footprint %s: model %s is not in %s/" % (ff.stem, r, model_dir))
                    if not refs:
                        plan['warnings'].append("footprint %s: no 3D model (%s)" % (ff.stem, rule))
                m['after'] = lib3d.model_refs(new_text)
                row['model'] = m
            if target.exists():
                if target.read_bytes() == new_text.encode('utf-8'):
                    row['action'] = 'identical'
                elif overwrite:
                    row['action'] = 'replace'
                else:
                    row['action'] = 'refused'
                    plan['errors'].append("%s exists with different content (use --overwrite to replace)"
                                          % self._rel(target))
            row['_text'] = new_text
            plan['footprints'].append(row)

        if not (sym_files or fp_files or model_files):
            plan['errors'].append("no .kicad_sym, .kicad_mod or 3D model files in the zip")
        return plan

    def apply_zip_plan(self, plan: Dict, extracted: Path) -> List[str]:
        """Do the writes of a plan without errors; return library-relative paths written."""
        written = []
        key = plan['category']
        for sf in sorted({row['source'] for row in plan['symbols']}):
            if not self.add_symbol_to_library(Path(extracted) / sf, key):
                raise RuntimeError("could not add symbols from %s" % sf)
            written.append(self._rel(self.lib_sym_path / self.libraries[key]['sym_file']))
        for row in plan['footprints']:
            if row['action'] in ('add', 'replace'):
                target = self.base_path / row['target']
                target.parent.mkdir(parents=True, exist_ok=True)
                lib3d.write_text(target, row['_text'])
                print(f"✓ Added footprint {target.name} to {key}")
                written.append(row['target'])
        for row in plan['models']:
            if row['action'] in ('add', 'replace'):
                target = self.base_path / row['target']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(extracted) / row['source'], target)
                print(f"✓ Added 3D model {target.name}")
                written.append(row['target'])
        return sorted(set(written))

    def _stage_for_verify(self, plan: Dict, extracted: Path, stage: Path) -> Tuple[List[Path], List[Path]]:
        """Dry-run verification: write the planned footprints and the zip's models
        into a scratch library so KiCad can load them without touching the real one."""
        lib = self.libraries[plan['category']]
        fps = []
        for row in plan['footprints']:
            p = stage / self.config.footprint_dir / lib['fp_dir'] / Path(row['target']).name
            p.parent.mkdir(parents=True, exist_ok=True)
            lib3d.write_text(p, row['_text'])
            fps.append(p)
        for row in plan['models']:
            p = stage / self.config.model_dir / Path(row['target']).name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(extracted) / row['source'], p)
        return fps, [stage, self.base_path]

    def _verify(self, footprints, roots, kicad_bin):
        return lib3d.verify_in_kicad(footprints, roots, kicad_bin, library_mount=self.config.library_mount)

    def git_commit_paths(self, paths: List[str], message: str) -> bool:
        """Commit exactly these paths (commit_changes stages everything with `git add .`)."""
        message = self._commit_message(message)
        try:
            self._git('add', '--', *paths)
            self._git('commit', '-m', message, '--', *paths)
            print(f"✓ Committed {len(paths)} file(s): {message}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"✗ Error committing changes: {e}")
            return False

    def import_zip(self, zip_path: str, opts) -> Tuple[Dict, int]:
        """Plan, refuse or apply, optionally verify. Returns (report, exit code)."""
        report = {'command': 'import', 'zip': str(zip_path), 'library_root': str(self.base_path),
                  'dry_run': bool(opts.dry_run), 'link_3d': bool(opts.link_3d), 'written': []}
        key = self.resolve_category(opts.category) if opts.category else None
        if opts.category and not key:
            report['errors'] = ["unknown category %r (one of: %s)" % (opts.category, ', '.join(self.libraries))]
            return report, EXIT_USAGE
        if opts.verify_3d:
            try:  # find KiCad before writing anything
                lib3d.find_kicad(opts.kicad_bin)
            except RuntimeError as e:
                report['errors'] = [str(e)]
                return report, EXIT_USAGE
        try:
            zf = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError) as e:
            report['errors'] = ["cannot read zip: %s" % e]
            return report, EXIT_USAGE
        temp_dir = Path(tempfile.mkdtemp(prefix='kpi_zip_'))
        try:
            with zf:
                zf.extractall(temp_dir)
            if key is None:
                if not opts.interactive:
                    report['errors'] = ["--category is required without prompts (one of: %s)"
                                        % ', '.join(self.libraries)]
                    return report, EXIT_USAGE
                self.display_library_menu()
                key = self.get_library_selection()
                if key is None:
                    report['errors'] = ["skipped at the library menu"]
                    return report, EXIT_OK
            plan = self.plan_zip_import(temp_dir, key, link_3d=opts.link_3d, overwrite=opts.overwrite)
            report.update({k: v for k, v in plan.items()})
            _print_plan(self, plan, zip_path)
            for w in plan['warnings']:
                print(f"⚠ {w}")
            if plan['errors']:
                for e in plan['errors']:
                    print(f"✗ {e}")
                print("Nothing written.")
                return report, EXIT_REFUSED
            code = EXIT_OK
            try:
                if opts.dry_run:
                    print("Dry run: nothing written.")
                    report['written'] = []
                    if opts.verify_3d:
                        with tempfile.TemporaryDirectory(prefix='kpi_stage_') as stage:
                            fps, roots = self._stage_for_verify(plan, temp_dir, Path(stage))
                            report['verify_3d'] = self._verify(fps, roots, opts.kicad_bin)
                else:
                    report['written'] = self.apply_zip_plan(plan, temp_dir)
                    if opts.verify_3d:
                        fps = [self.base_path / r['target'] for r in plan['footprints']]
                        report['verify_3d'] = self._verify(fps, [self.base_path], opts.kicad_bin)
            except RuntimeError as e:  # the KiCad check did not run; keep the report of what was written
                print(f"✗ {e}")
                report.setdefault('errors', []).append(str(e))
                code = EXIT_FAIL
            v = report.get('verify_3d')
            if v:
                for f in v['failed']:
                    print(f"✗ 3D model did not load: {Path(f['footprint']).name}: {f['reason']}")
                _print_verify_summary(v)
                if v['failed'] or v['load_errors']:
                    code = EXIT_FAIL
            if not opts.dry_run:
                if opts.add_to_project:
                    self.update_project_settings()
                if opts.commit and report['written']:
                    self.git_commit_paths(report['written'], f"Add components from {Path(zip_path).name}")
                if opts.push:
                    self.push_changes()
                if opts.delete_zip and code != EXIT_OK:
                    print(f"⚠ Kept {Path(zip_path).name}: the import did not finish cleanly")
                    report['zip_action'] = 'kept'
                elif opts.delete_zip:
                    Path(zip_path).unlink()
                    report['zip_action'] = 'deleted'
                elif opts.keep_zip or not opts.interactive:
                    report['zip_action'] = 'kept'
                else:
                    self.ask_delete_zip_file(zip_path)
                    report['zip_action'] = 'kept' if Path(zip_path).exists() else 'deleted'
            return report, code
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            for row in report.get('footprints', []):
                row.pop('_text', None)

    def check_3d(self, opts) -> Tuple[Dict, int]:
        """--check-3d: classify every model path; --fix-3d rewrites the fixable ones."""
        if opts.verify_3d:
            try:  # find KiCad before writing anything
                lib3d.find_kicad(opts.kicad_bin)
            except RuntimeError as e:
                print(f"✗ {e}")
                return {'command': 'check-3d', 'errors': [str(e)]}, EXIT_USAGE
        rep = lib3d.check_library(self.config, all_libs=opts.all_footprint_libs)
        rep['command'] = 'check-3d'
        rep['dry_run'] = bool(opts.dry_run)
        rows = rep.pop('rows')
        kinds = ', '.join(f"{k} {n}" for k, n in sorted(rep['counts'].items())) or 'none'
        print(f"Footprints checked: {rep['footprints']}; model references: {kinds}")
        for r in rep['problems']:
            if r['fix_action'] == 'remove':
                fix = f"  -> remove (the footprint already names {r['fix']})"
            else:
                fix = f"  -> {r['fix']}" if r['fix'] else ""
            print(f"  {r['kind']:9s} {r['footprint']}: {r['ref']}{fix}")
        remaining = rep['problems']
        if opts.fix_3d:
            rep['changed'] = lib3d.apply_fixes(self.config, rep['fixable'], dry_run=opts.dry_run)
            n_rm = sum(1 for r in rep['fixable'] if r['fix_action'] == 'remove')
            verb = "Would change" if opts.dry_run else "Changed"
            print(f"{verb} {len(rep['changed'])} footprint file(s): "
                  f"{len(rep['fixable']) - n_rm} path(s) rewritten, {n_rm} dead duplicate reference(s) removed")
            remaining = rep['unfixable']
        if opts.verify_3d:
            fps = sorted({self.base_path / r['footprint'] for r in rows})
            rep['verify_3d'] = self._verify(fps, [self.base_path], opts.kicad_bin)
            v = rep['verify_3d']
            _print_verify_summary(v)
            if v['failed']:
                return rep, EXIT_FAIL
        return rep, (EXIT_FAIL if remaining else EXIT_OK)


def _print_verify_summary(v) -> None:
    """One line for a KiCad 3D check. A footprint can carry several (model ...)
    blocks; one that fails next to one that loads leaves the part with its body."""
    failed_fps = {f['footprint'] for f in v['failed']}
    no_body = set(v.get('no_body', failed_fps))
    detail = (f" ({len(no_body)} of them with no 3D body, {len(failed_fps - no_body)} with a dead extra "
              f"reference next to one that loads)") if failed_fps else ""
    print(f"3D check: {len(v['loaded'])} loaded, {len(failed_fps)} with a model that did not load{detail}, "
          f"{len(v['no_model'])} without a model (KiCad {v['kicad_version']})")


def _print_plan(manager, plan, zip_path) -> None:
    """The plan of a zip import, one line per write (the --json report has the details)."""
    lib = manager.libraries[plan['category']]
    print(f"Plan: {Path(zip_path).name} -> {plan['category']} ({lib['name']})")
    for s in plan['symbols']:
        print(f"  symbol     {s['name']:<22} {s['action']:<9} {s['target']}")
    for f in plan['footprints']:
        print(f"  footprint  {f['name']:<22} {f['action']:<9} {f['target']}")
        m = f.get('model')
        if not m:
            continue
        if m['action'] == 'keep':
            what = ('keep ' + ', '.join(m['after'])) if m['after'] else 'none'
        elif m['action'] == 'rewrite':
            what = 'rewrite %s -> %s' % (', '.join(m['before']), ', '.join(m['after']))
        else:
            what = '%s %s' % (m['action'], ', '.join(m['after']))
        print(f"             model: {what} ({m['rule']})")
    for r in plan['models']:
        print(f"  3D model   {r['name']:<22} {r['action']:<9} {r['target']}")
    if plan['ignored_files']:
        print(f"  ignored    {', '.join(plan['ignored_files'])}")


def _new_mode_requested(args) -> bool:
    return any([args.category, args.yes, args.dry_run, args.json, args.link_3d, args.verify_3d,
                args.keep_zip, args.delete_zip, args.overwrite])


def _run_new_mode(manager, args) -> int:
    """Run --check-3d or a planned zip import; print JSON when asked. Returns the exit code."""
    args.interactive = not (args.yes or args.dry_run or args.json)
    if not args.interactive:
        bad = [f for f, on in (('--add-to-project', args.add_to_project), ('--migrate', args.migrate),
                               ('--migrate-schematic', args.migrate_schematic)) if on]
        if bad:
            verb = 'asks' if len(bad) == 1 else 'ask'
            print(f"✗ {', '.join(bad)} {verb} questions; run without --yes/--dry-run/--json", file=sys.stderr)
            return EXIT_USAGE
    if args.keep_zip and args.delete_zip:
        print("✗ --keep-zip and --delete-zip together", file=sys.stderr)
        return EXIT_USAGE
    out = contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext()
    with out:
        try:
            if args.check_3d:
                report, code = manager.check_3d(args)
            else:
                if not args.input_file or not args.input_file.lower().endswith('.zip'):
                    print("✗ these options need a .zip file (or --check-3d)")
                    return EXIT_USAGE
                if not os.path.exists(args.input_file):
                    print(f"Error: File '{args.input_file}' not found")
                    return EXIT_USAGE
                report, code = manager.import_zip(args.input_file, args)
                if code == EXIT_USAGE:
                    for e in report.get('errors', []):
                        print(f"✗ {e}")
        except RuntimeError as e:  # KiCad missing or its check failed to run
            print(f"✗ {e}")
            report, code = {'errors': [str(e)]}, EXIT_FAIL
    report['exit_code'] = code
    report['ok'] = code == EXIT_OK
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    return code


_EPILOG = """
Examples:
  kicad-part-importer --init                         create a library here: config file + folders
  kicad-part-importer --init --library-prefix acme_  ... or describe an existing acme_* library
  kicad-part-importer part.zip                       import with prompts
  kicad-part-importer part.zip --category power_management --link-3d --yes
  kicad-part-importer part.zip --category 5 --link-3d --dry-run --json
  kicad-part-importer --check-3d                     check every footprint's 3D model path
  kicad-part-importer --check-3d --fix-3d --verify-3d --yes
  kicad-part-importer --add-to-project --project-dir ../my_board
  kicad-part-importer --migrate old_parts.kicad_sym
  kicad-part-importer --migrate-schematic ../power.kicad_sch --commit
  kicad-part-importer --show-config

Which library: --library DIR, else $KICAD_PART_IMPORTER_LIBRARY_ROOT, else the
nearest folder at or above the current directory that holds a
kicad-part-importer.toml / .json, else the current directory.
Settings: flags > KICAD_PART_IMPORTER_* variables > that config file > defaults.

Exit codes: 0 ok, 1 failed, 2 usage, 3 refused (nothing written).
Documentation: https://github.com/aqsnyder/kicad-part-importer/tree/main/docs
"""


def build_parser() -> argparse.ArgumentParser:
    env = libcfg.ENV_PREFIX
    parser = argparse.ArgumentParser(
        prog="kicad-part-importer",
        description="Import vendor part zips (TI / Ultra Librarian, SamacSys, SnapEDA) into a categorized "
                    "KiCad library and link every footprint to its 3D model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument('input_file', nargs='?', metavar='FILE',
                        help='Part zip to import (prompts for the category unless --category is given), or a '
                             '.kicad_sym file to migrate')
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    cmd = parser.add_argument_group('commands')
    cmd.add_argument('--init', action='store_true',
                     help='Create a library in the library root (--library, else the current directory): write '
                          'kicad-part-importer.toml from the settings in effect (unless the folder has a config '
                          'file already), then create the folders and empty category libraries. In a folder '
                          'that already holds <prefix>* libraries, those become the categories')
    cmd.add_argument('--init-libraries', action='store_true',
                     help="Create the folders and the empty category libraries that don't exist yet (no "
                          "config file)")
    cmd.add_argument('--add-to-project', action='store_true',
                     help="Add category libraries (asks which) to the project's sym-lib-table and fp-lib-table")
    cmd.add_argument('--migrate', action='store_true',
                     help='Move symbols from FILE, or from every other .kicad_sym in the symbol folder, into '
                          'the categories (asks for each)')
    cmd.add_argument('--migrate-schematic', metavar='SCHEMATIC',
                     help='Move the custom parts a .kicad_sch uses into the categories and rewrite its '
                          'references (asks for each; keeps a .kicad_sch.bak)')
    cmd.add_argument('--show-config', action='store_true',
                     help='Print the effective settings as JSON and exit')

    imp = parser.add_argument_group('zip import without prompts (any of these makes the import a planned run)')
    imp.add_argument('--category', metavar='KEY',
                     help='Category to import into: key (power_management), library name (lib_power_management) '
                          'or menu number (5)')
    imp.add_argument('--link-3d', action='store_true',
                     help="Point each footprint's (model ...) at the library's copy of its model")
    imp.add_argument('--overwrite', action='store_true',
                     help='Replace an existing footprint or 3D model whose content differs (default: refuse)')
    imp.add_argument('--yes', action='store_true', help='Never prompt; --category is then required')
    imp.add_argument('--dry-run', action='store_true',
                     help='Plan and check only; write nothing, commit nothing (no prompts)')
    imp.add_argument('--json', action='store_true',
                     help='Print one JSON report on stdout, logs on stderr (no prompts)')
    imp.add_argument('--keep-zip', action='store_true', help='Keep the zip without asking')
    imp.add_argument('--delete-zip', action='store_true',
                     help='Delete the zip after a clean import (kept when the exit code is not 0)')

    d3 = parser.add_argument_group('3D models')
    d3.add_argument('--verify-3d', action='store_true',
                    help='Load the imported or checked footprints in KiCad (kicad-cli STEP export) and report '
                         'every model that does not load')
    d3.add_argument('--kicad-bin', metavar='DIR',
                    help="KiCad's bin folder, holding kicad-cli (env KICAD_BIN; default: the KiCad 10 / 9 "
                         "install on Windows, then kicad-cli on PATH). When given, nothing else is searched")
    d3.add_argument('--check-3d', action='store_true',
                    help="Check every footprint's 3D model path in the category footprint libraries; exit 1 "
                         "while problems remain. Never commits")
    d3.add_argument('--fix-3d', action='store_true',
                    help='With --check-3d: rewrite fixable paths to the library form (or remove a dead '
                         'duplicate reference)')
    d3.add_argument('--all-footprint-libs', action='store_true',
                    help='With --check-3d: check every .pretty in the footprint folder, not only the '
                         'category libraries')

    cfg = parser.add_argument_group(
        'library and settings (flags override %s* variables, which override the config file)' % env)
    cfg.add_argument('--library', '--library-root', dest='library_root', metavar='DIR',
                     help='The library root (env %sLIBRARY_ROOT; default: the nearest folder at or above the '
                          'current directory holding a config file, else the current directory)' % env)
    cfg.add_argument('--config', metavar='FILE',
                     help='Config file to read instead of the one in the library root (env %sCONFIG; .toml '
                          'or .json). With --init: a template for the new library' % env)
    cfg.add_argument('--config-format', choices=('toml', 'json'),
                     help='Format of the file --init writes (default: toml when Python can read TOML, else json)')
    cfg.add_argument('--library-prefix', metavar='PREFIX',
                     help='Name prefix of the category libraries (env %sLIBRARY_PREFIX; default: %s)'
                          % (env, libcfg.DEFAULT_LIBRARY_PREFIX))
    cfg.add_argument('--symbol-dir', metavar='DIR',
                     help='Symbol library folder in the library root (env %sSYMBOL_DIR; default: %s)'
                          % (env, libcfg.DEFAULT_SYMBOL_DIR))
    cfg.add_argument('--footprint-dir', metavar='DIR',
                     help='Footprint library folder in the library root (env %sFOOTPRINT_DIR; default: %s)'
                          % (env, libcfg.DEFAULT_FOOTPRINT_DIR))
    cfg.add_argument('--model-dir', metavar='DIR',
                     help='3D model folder in the library root (env %sMODEL_DIR; default: %s)'
                          % (env, libcfg.DEFAULT_MODEL_DIR))
    cfg.add_argument('--model-search-dir', metavar='DIR', action='append',
                     help='Another folder in the library root where --fix-3d looks for models; repeat for '
                          'more (env %sMODEL_SEARCH_DIRS, separated by the OS path separator; default: none)'
                          % env)
    cfg.add_argument('--library-mount', metavar='MOUNT',
                     help='How projects reach the library root in model paths, starting with a path variable '
                          '(env %sLIBRARY_MOUNT; default: ${KIPRJMOD}/<path from the project folder to the '
                          'library root>)' % env)
    cfg.add_argument('--model-prefix', metavar='PREFIX',
                     help='Model path --link-3d writes before the file name (env %sMODEL_PREFIX; default: '
                          '<library mount>/<model folder>)' % env)
    cfg.add_argument('--project-dir', metavar='DIR',
                     help="Folder holding the project's sym-lib-table / fp-lib-table (env %sPROJECT_DIR; "
                          "default: the folder that holds the library root)" % env)

    git = parser.add_argument_group('git (default: git_commit / git_push in the config file, else off)')
    git.add_argument('--commit', dest='commit', action='store_const', const=True, default=None,
                     help='Commit after the work (env %sGIT_COMMIT). A planned import commits exactly the files '
                          'it wrote; other commands stage the library root (git add .)' % env)
    git.add_argument('--no-commit', dest='commit', action='store_const', const=False,
                     help='Do not commit, whatever the config file says')
    git.add_argument('--push', dest='push', action='store_const', const=True, default=None,
                     help='Run git push afterwards (env %sGIT_PUSH). Never done otherwise' % env)
    git.add_argument('--no-push', dest='push', action='store_const', const=False,
                     help='Do not push, whatever the config file says')
    return parser


def _cli_settings(args) -> Dict:
    """The settings given on the command line (None = not given), for resolve_config."""
    return {
        'config': args.config, 'library_root': args.library_root, 'library_prefix': args.library_prefix,
        'symbol_dir': args.symbol_dir, 'footprint_dir': args.footprint_dir, 'model_dir': args.model_dir,
        'model_search_dirs': args.model_search_dir, 'library_mount': args.library_mount,
        'model_prefix': args.model_prefix, 'project_dir': args.project_dir,
    }


def _given_settings(cli, environ=None) -> set:
    """Names of the settings given by a flag or a KICAD_PART_IMPORTER_* variable."""
    environ = os.environ if environ is None else environ
    names = {k for k, v in cli.items() if v is not None and k != 'config'}
    names |= {n for n in libcfg.ENV_SETTINGS if libcfg.ENV_PREFIX + n.upper() in environ}
    return names


def _with_categories(cfg, categories):
    """cfg with other categories (named <prefix><key> unless a category says otherwise)."""
    return libcfg.LibraryConfig(
        library_root=cfg.library_root, library_prefix=cfg.library_prefix, symbol_dir=cfg.symbol_dir,
        footprint_dir=cfg.footprint_dir, model_dir=cfg.model_dir, model_search_dirs=cfg.model_search_dirs,
        project_dir=cfg.project_dir, library_mount=cfg.library_mount, model_prefix=cfg.model_prefix,
        categories=categories, stock_symbol_libraries=cfg.stock_symbol_libraries, git_commit=cfg.git_commit,
        git_push=cfg.git_push, git_message_prefix=cfg.git_message_prefix, config_file=cfg.config_file,
        library_root_source=cfg.library_root_source)


def _resolve_git(args, config) -> None:
    """--commit / --no-commit and --push / --no-push, else the config's git_commit / git_push."""
    args.commit = config.git_commit if args.commit is None else args.commit
    args.push = config.git_push if args.push is None else args.push


def run_init(args) -> int:
    """--init: write a starter config file into the library root (unless it has
    one), then create the folders and the empty category libraries."""
    cli = _cli_settings(args)
    explicit_config = bool(args.config or os.environ.get(libcfg.CONFIG_ENV))
    try:
        cfg = libcfg.resolve_config(cli, discover=False)
    except libcfg.ConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return EXIT_USAGE
    root = Path(cfg.library_root)
    if cfg.library_root_source == 'current directory':
        outer = libcfg.find_library_root(Path(os.path.abspath(str(root))).parent)
        if outer is not None:
            print(f"✗ {root} is inside the library {outer} ({libcfg.config_files_in(outer)[0].name} there). "
                  f"Pass --library DIR to create a separate library here anyway.", file=sys.stderr)
            return EXIT_USAGE
    existing = libcfg.config_files_in(root)
    if existing:
        if explicit_config:
            print(f"✗ {existing[0]} already exists; --init --config only seeds a library without one",
                  file=sys.stderr)
            return EXIT_USAGE
        flags = sorted(k for k, v in cli.items() if v is not None and k not in ('config', 'library_root'))
        if flags:
            print(f"✗ {existing[0]} already exists and --init does not change it: edit the file, or run "
                  f"again without the settings flags ({', '.join(flags)})", file=sys.stderr)
            return EXIT_USAGE
        print(f"Library root: {root}")
        print(f"- {existing[0].name} already exists; kept it (edit it to change the settings)")
        given = sorted(_given_settings(cli) - {'library_root'})
        if given:
            print(f"⚠ KICAD_PART_IMPORTER_* variables override {existing[0].name} for this run: "
                  f"{', '.join(given)}")
    else:
        print(f"Library root: {root}")
        if cfg.config_file is None:  # no template: describe the libraries already there, if any
            found = libcfg.infer_categories(root, cfg.symbol_dir, cfg.footprint_dir, cfg.library_prefix)
            if found:
                cfg = _with_categories(cfg, found)
                print(f"Found {len(found)} existing libraries named {cfg.library_prefix}*; they become the "
                      f"categories: {', '.join(c.key for c in cfg.categories)}")
        try:
            path, fmt = libcfg.write_starter_config(cfg, explicit=_given_settings(cli), fmt=args.config_format,
                                                    version=__version__)
        except (OSError, libcfg.ConfigError) as e:
            print(f"✗ cannot write the config file: {e}", file=sys.stderr)
            return EXIT_FAIL
        print(f"✓ Wrote {path.name}: prefix '{cfg.library_prefix}', {len(cfg.categories)} categories, "
              f"mount {cfg.library_mount}")
        # Read it back, as every later command will (and fail loudly if it cannot be).
        environ = {k: v for k, v in os.environ.items() if k != libcfg.CONFIG_ENV}
        try:
            cfg = libcfg.resolve_config({'library_root': str(root)}, environ=environ, discover=False)
        except libcfg.ConfigError as e:
            print(f"✗ {e}", file=sys.stderr)
            return EXIT_FAIL
    manager = LibraryManager(config=cfg)
    _resolve_git(args, cfg)
    if not manager.initialize_libraries():
        return EXIT_FAIL
    if args.commit:
        manager.commit_changes("Initialize the part library")
    if args.push:
        manager.push_changes()
    first = cfg.categories[0].key
    print("\nNext:")
    print("  kicad-part-importer --show-config")
    print(f"  kicad-part-importer part.zip --category {first} --link-3d --dry-run")
    print("  kicad-part-importer --add-to-project --project-dir <folder with sym-lib-table>")
    return EXIT_OK


def _not_a_library(config) -> str:
    return (f"{config.library_root} is not a part library: it has no {config.symbol_dir}/ or "
            f"{config.footprint_dir}/ folder (library root from: {config.library_root_source}). Run the "
            f"command inside your library, pass --library DIR, or create one there with --init.")


def main(argv=None):
    """Main entry point"""
    parser = build_parser()
    args = parser.parse_args(argv)
    _guard_console_encoding()

    if args.init:
        others = [f for f, on in (('FILE', args.input_file), ('--init-libraries', args.init_libraries),
                                  ('--add-to-project', args.add_to_project), ('--migrate', args.migrate),
                                  ('--migrate-schematic', args.migrate_schematic),
                                  ('--check-3d', args.check_3d), ('--show-config', args.show_config))
                  if on]
        if others or _new_mode_requested(args):
            print("✗ --init runs alone (name the folder with --library DIR); got %s"
                  % ', '.join(others or ['zip import options']), file=sys.stderr)
            sys.exit(EXIT_USAGE)
        sys.exit(run_init(args))

    try:
        config = libcfg.resolve_config(_cli_settings(args))
    except libcfg.ConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if args.show_config:
        print(json.dumps(config.to_dict(), indent=1))
        return

    # Create library manager
    manager = LibraryManager(config=config)

    explicit_git = [f for f, on in (('--commit', args.commit), ('--push', args.push)) if on]
    _resolve_git(args, config)
    if (args.fix_3d or args.all_footprint_libs) and not args.check_3d:
        # Without this they would be ignored and a zip would go to the prompting import.
        print("✗ --fix-3d and --all-footprint-libs need --check-3d", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if args.check_3d:
        if explicit_git:
            print(f"⚠ {' and '.join(explicit_git)} do not apply to --check-3d: it never commits or pushes",
                  file=sys.stderr)
        args.commit = args.push = False
    if args.check_3d or _new_mode_requested(args):
        if not manager.library_exists():
            msg = _not_a_library(config)
            print(f"✗ {msg}", file=sys.stderr)
            if args.json:
                print(json.dumps({'errors': [msg], 'library_root': str(config.library_root),
                                  'exit_code': EXIT_USAGE, 'ok': False}, indent=1))
            sys.exit(EXIT_USAGE)
        sys.exit(_run_new_mode(manager, args))

    # Handle --init-libraries option
    if args.init_libraries:
        success = manager.initialize_libraries()
        if success and args.commit:
            manager.commit_changes("Initialize library files")
        if success and args.push:
            manager.push_changes()
        return

    if (args.migrate_schematic or args.migrate or args.add_to_project or args.input_file) \
            and not manager.library_exists():
        print(f"✗ {_not_a_library(config)}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Handle --migrate-schematic option
    if args.migrate_schematic:
        schematic_file = args.migrate_schematic
        if not os.path.exists(schematic_file):
            print(f"Error: Schematic file '{schematic_file}' not found")
            sys.exit(1)

        success = manager.migrate_schematic(schematic_file)
        if success and args.commit:
            manager.commit_changes(f"Migrate components from {os.path.basename(schematic_file)}")
        if success and args.push:
            manager.push_changes()
        return

    # Handle --migrate option
    if args.migrate:
        if args.input_file:
            # Migrate specific file
            success = manager.migrate_single_file(args.input_file)
        else:
            # Migrate all files
            success = manager.migrate_symbols()

        if success and args.commit:
            manager.commit_changes("Migrate symbols to categorized libraries")
        if success and args.push:
            manager.push_changes()
        return

    # If only --add-to-project is specified, just update project settings
    if args.add_to_project and not args.input_file:
        print("Updating project library settings...")
        success = manager.update_project_settings()
        if success and args.commit:
            manager.commit_changes("Update project library settings")
        if success and args.push:
            manager.push_changes()
        return

    # If input file is provided, process it
    if args.input_file:
        # Validate file exists
        if not os.path.exists(args.input_file):
            print(f"Error: File '{args.input_file}' not found")
            sys.exit(1)

        # Check if it's a zip file or kicad_sym file
        if args.input_file.lower().endswith('.zip'):
            # Process zip file
            manager.process_zip_file(
                args.input_file,
                add_to_project=args.add_to_project,
                commit=args.commit,
                push=args.push
            )
        elif args.input_file.lower().endswith('.kicad_sym'):
            # Process single symbol file
            success = manager.migrate_single_file(args.input_file)
            if success and args.commit:
                manager.commit_changes(f"Migrate symbols from {os.path.basename(args.input_file)}")
            if success and args.push:
                manager.push_changes()
        else:
            print("Error: Unsupported file type. Please provide a .zip or .kicad_sym file")
            sys.exit(1)
    else:
        # No input file and no other options specified
        print("Error: nothing to do. Give a part zip, or a command such as --init, --check-3d, "
              "--add-to-project or --migrate")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
