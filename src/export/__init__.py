"""Modul eksportu wynikow matchingu do Excel i DOCX."""

from src.export.docx_report import export_weekly_report
from src.export.excel import export_to_excel

__all__ = ["export_to_excel", "export_weekly_report"]
