#!/usr/bin/env pwsh
Set-Location "c:\Users\GIGABYTE\Desktop\Forge"
python -m pytest -xvs backend/tests/unit/controller/test_error_recovery.py::TestRecoverFilesystemError::test_file_not_found_recovery --tb=short
