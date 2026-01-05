"""
Architecture guard tests for Retrovue.
Ensures proper layer boundaries are maintained.
"""

from pathlib import Path


class TestArchitectureGuard:
    """Test that architecture layer boundaries are respected."""
    
    def test_api_layer_imports(self):
        """Test that API layer doesn't import GUI modules."""
        repo_root = Path(__file__).parent.parent
        api_dir = repo_root / "src" / "retrovue" / "api"
        
        # Forbidden imports for API layer (GUI-related)
        forbidden_patterns = [
            'pyside6', 'pyqt6', 'qt', 'tkinter', 'wx', 'kivy',
            'matplotlib', 'plotly', 'bokeh', 'streamlit'
        ]
        
        # More specific patterns that should be forbidden
        forbidden_imports = [
            'import dash', 'from dash', 'import plotly', 'from plotly',
            'import matplotlib', 'from matplotlib', 'import bokeh', 'from bokeh',
            'import streamlit', 'from streamlit', 'import pyside6', 'from pyside6',
            'import pyqt6', 'from pyqt6', 'import tkinter', 'from tkinter'
        ]
        
        violations = []
        for py_file in api_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            try:
                with open(py_file, encoding='utf-8') as f:
                    content = f.read()
                    
                # Check for specific import statements
                for forbidden_import in forbidden_imports:
                    if forbidden_import in content:
                        violations.append(f"{py_file}: {forbidden_import}")
                        
                # Check for module names in import statements (more specific)
                for pattern in forbidden_patterns:
                    if f"import {pattern}" in content or f"from {pattern}" in content:
                        violations.append(f"{py_file}: imports {pattern}")
            except Exception as e:
                print(f"Warning: Could not read {py_file}: {e}")
        
        assert not violations, f"API layer has forbidden GUI imports: {violations}"
    
    def test_domain_layer_imports(self):
        """Test that domain layer doesn't import web/GUI modules."""
        repo_root = Path(__file__).parent.parent
        domain_dir = repo_root / "src" / "retrovue" / "domain"
        
        # Forbidden imports for domain layer
        forbidden_patterns = [
            'fastapi',
            'uvicorn', 
            'jinja2',
            'starlette',
            'pyside6',
            'pyqt6',
            'qt',
            'tkinter',
            'wx',
        ]
        
        violations = []
        for py_file in domain_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            try:
                with open(py_file, encoding='utf-8') as f:
                    content = f.read()
                    
                for pattern in forbidden_patterns:
                    if pattern in content.lower():
                        violations.append(f"{py_file}: contains {pattern}")
            except Exception as e:
                print(f"Warning: Could not read {py_file}: {e}")
        
        assert not violations, f"Domain layer has forbidden imports: {violations}"
    
    def test_infra_layer_imports(self):
        """Test that infrastructure layer doesn't import GUI modules."""
        repo_root = Path(__file__).parent.parent
        infra_dir = repo_root / "src" / "retrovue" / "infra"
        
        # Forbidden imports for infra layer
        forbidden_patterns = [
            'pyside6',
            'pyqt6',
            'qt',
            'tkinter',
            'wx',
            'fastapi',  # Infra should not directly import web framework
            'uvicorn',
        ]
        
        violations = []
        for py_file in infra_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            try:
                with open(py_file, encoding='utf-8') as f:
                    content = f.read()
                    
                for pattern in forbidden_patterns:
                    if pattern in content.lower():
                        violations.append(f"{py_file}: contains {pattern}")
            except Exception as e:
                print(f"Warning: Could not read {py_file}: {e}")
        
        assert not violations, f"Infrastructure layer has forbidden imports: {violations}"
    
    def test_no_gui_directories(self):
        """Test that no GUI-specific directories exist."""
        repo_root = Path(__file__).parent.parent
        src_dir = repo_root / "src" / "retrovue"
        
        # Check for forbidden directory names
        forbidden_dirs = [
            'gui', 'qt', 'pyside', 'tkinter', 'wx', 'desktop', 'ui'
        ]
        
        violations = []
        for item in src_dir.iterdir():
            if item.is_dir() and item.name.lower() in forbidden_dirs:
                violations.append(f"Forbidden directory: {item}")
        
        assert not violations, f"Found forbidden GUI directories: {violations}"
    
    def test_no_gui_files(self):
        """Test that no GUI-specific files exist."""
        repo_root = Path(__file__).parent.parent
        src_dir = repo_root / "src" / "retrovue"
        
        # Check for forbidden file patterns
        forbidden_patterns = [
            '*.ui',  # Qt UI files
            '*.qrc',  # Qt resource files
            'qrc_*.py',  # Generated Qt resource files
            '*_gui.py',  # GUI files
            '*_qt.py',  # Qt files
            '*_pyside.py',  # PySide files
        ]
        
        violations = []
        for pattern in forbidden_patterns:
            for file_path in src_dir.rglob(pattern):
                violations.append(f"Forbidden file: {file_path}")
        
        assert not violations, f"Found forbidden GUI files: {violations}"
