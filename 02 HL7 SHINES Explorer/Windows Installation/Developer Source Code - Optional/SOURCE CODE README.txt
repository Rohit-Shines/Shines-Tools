HL7 SHINES EXPLORER 1.2.0 - SOURCE CODE
========================================

This folder contains the complete cross-platform Python source used by
the one-click Windows installer and the Intel-Mac fallback installer.

Main source:
  src/hl7_shines/

Automated tests:
  tests/

Developer test command from this folder:

  macOS/Linux:
    PYTHONPATH=src python3 -m unittest discover -s tests -v

  Windows PowerShell:
    $env:PYTHONPATH = "src"
    python -m unittest discover -s tests -v

The application uses the Python standard library, including Tkinter.
No patient data is uploaded by the application; files are processed locally.
