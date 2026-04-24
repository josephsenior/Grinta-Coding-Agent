"""Launch a child process inside an ephemeral Windows AppContainer.

This helper is invoked by ``sandboxing.ExecutionSandboxPolicy`` for the
``sandboxed_local`` profile on Windows. It is intentionally process-scoped:
every command gets a fresh AppContainer profile, the workspace root is granted
temporary ACL access, then the child is started with stdout/stderr redirected
to temporary files that the host process relays back to the caller.
"""

from __future__ import annotations

import argparse
import ctypes
import msvcrt
import os
import subprocess
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

HRESULT = ctypes.c_long


PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020005
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR),
        ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD),
        ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD),
        ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD),
        ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD),
        ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.POINTER(ctypes.c_byte)),
        ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [('StartupInfo', STARTUPINFO), ('lpAttributeList', wintypes.LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE),
        ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD),
        ('dwThreadId', wintypes.DWORD),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('Sid', wintypes.LPVOID), ('Attributes', wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ('AppContainerSid', wintypes.LPVOID),
        ('Capabilities', ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ('CapabilityCount', wintypes.DWORD),
        ('Reserved', wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
userenv = ctypes.WinDLL('userenv', use_last_error=True)

InitializeProcThreadAttributeList = kernel32.InitializeProcThreadAttributeList
InitializeProcThreadAttributeList.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_size_t),
]
InitializeProcThreadAttributeList.restype = wintypes.BOOL

UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
UpdateProcThreadAttribute.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.c_size_t,
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.LPVOID,
    ctypes.POINTER(ctypes.c_size_t),
]
UpdateProcThreadAttribute.restype = wintypes.BOOL

DeleteProcThreadAttributeList = kernel32.DeleteProcThreadAttributeList
DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
DeleteProcThreadAttributeList.restype = None

CreateProcessW = kernel32.CreateProcessW
CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    wintypes.LPVOID,
    wintypes.LPVOID,
]
CreateProcessW.restype = wintypes.BOOL

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD

GetExitCodeProcess = kernel32.GetExitCodeProcess
GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
GetExitCodeProcess.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

LocalFree = kernel32.LocalFree
LocalFree.argtypes = [wintypes.HLOCAL]
LocalFree.restype = wintypes.HLOCAL

CreateAppContainerProfile = userenv.CreateAppContainerProfile
CreateAppContainerProfile.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPVOID),
]
CreateAppContainerProfile.restype = HRESULT

DeleteAppContainerProfile = userenv.DeleteAppContainerProfile
DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
DeleteAppContainerProfile.restype = HRESULT

DeriveAppContainerSidFromAppContainerName = userenv.DeriveAppContainerSidFromAppContainerName
DeriveAppContainerSidFromAppContainerName.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(wintypes.LPVOID),
]
DeriveAppContainerSidFromAppContainerName.restype = HRESULT

ConvertSidToStringSidW = advapi32.ConvertSidToStringSidW
ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
ConvertSidToStringSidW.restype = wintypes.BOOL

ConvertStringSidToSidW = advapi32.ConvertStringSidToSidW
ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
ConvertStringSidToSidW.restype = wintypes.BOOL


def _check_bool(ok: bool, context: str) -> None:
    if ok:
        return
    raise ctypes.WinError(ctypes.get_last_error(), f'{context} failed')


def _check_hresult(result: int, context: str) -> None:
    if result >= 0:
        return
    raise ctypes.WinError(result & 0xFFFFFFFF, f'{context} failed')


def _sid_to_string(sid: wintypes.LPVOID) -> str:
    string_ptr = wintypes.LPWSTR()
    _check_bool(ConvertSidToStringSidW(sid, ctypes.byref(string_ptr)), 'ConvertSidToStringSidW')
    try:
        return str(string_ptr.value)
    finally:
        if string_ptr:
            LocalFree(string_ptr)


def _grant_workspace_access(workspace: Path, sid_string: str) -> None:
    grant = subprocess.run(
        [
            'icacls',
            str(workspace),
            '/grant',
            f'*{sid_string}:(OI)(CI)F',
            '/T',
            '/C',
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if grant.returncode != 0:
        raise RuntimeError(f'icacls grant failed: {grant.stderr.strip() or grant.stdout.strip()}')


def _revoke_workspace_access(workspace: Path, sid_string: str) -> None:
    subprocess.run(
        [
            'icacls',
            str(workspace),
            '/remove:g',
            f'*{sid_string}',
            '/T',
            '/C',
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


def _make_capabilities(allow_network: bool) -> tuple[ctypes.Array[SID_AND_ATTRIBUTES] | None, list[wintypes.LPVOID]]:
    if not allow_network:
        return None, []

    capability_sid = wintypes.LPVOID()
    _check_bool(
        ConvertStringSidToSidW('S-1-15-3-1', ctypes.byref(capability_sid)),
        'ConvertStringSidToSidW(internetClient)',
    )
    caps = (SID_AND_ATTRIBUTES * 1)()
    caps[0].Sid = capability_sid
    caps[0].Attributes = 0
    return caps, [capability_sid]


def _create_appcontainer(name: str) -> wintypes.LPVOID:
    sid = wintypes.LPVOID()
    result = CreateAppContainerProfile(name, name, 'Grinta sandbox', None, 0, ctypes.byref(sid))
    if result == ERROR_ALREADY_EXISTS:
        _check_hresult(
            DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid)),
            'DeriveAppContainerSidFromAppContainerName',
        )
        return sid
    _check_hresult(result, 'CreateAppContainerProfile')
    return sid


def _launch(argv: list[str], *, cwd: str, workspace: Path, allow_network: bool) -> int:
    profile_name = f'GrintaSandbox_{os.getpid()}_{uuid.uuid4().hex[:8]}'
    sid = _create_appcontainer(profile_name)
    sid_string = _sid_to_string(sid)
    capability_ptrs: list[wintypes.LPVOID] = []
    caps_array: ctypes.Array[SID_AND_ATTRIBUTES] | None = None
    attr_mem = None
    workspace.mkdir(parents=True, exist_ok=True)
    io_root = workspace / '.grinta' / 'sandbox-io'
    io_root.mkdir(parents=True, exist_ok=True)
    stdout_path = io_root / f'{uuid.uuid4().hex}.stdout'
    stderr_path = io_root / f'{uuid.uuid4().hex}.stderr'
    stdout_file = open(stdout_path, 'w+b')
    stderr_file = open(stderr_path, 'w+b')
    stdin_file = open('NUL', 'rb')

    try:
        os.set_handle_inheritable(stdout_file.fileno(), True)
        os.set_handle_inheritable(stderr_file.fileno(), True)
        os.set_handle_inheritable(stdin_file.fileno(), True)
        _grant_workspace_access(workspace, sid_string)

        caps_array, capability_ptrs = _make_capabilities(allow_network)
        security_caps = SECURITY_CAPABILITIES()
        security_caps.AppContainerSid = sid
        security_caps.Capabilities = (
            ctypes.cast(caps_array, ctypes.POINTER(SID_AND_ATTRIBUTES))
            if caps_array is not None
            else None
        )
        security_caps.CapabilityCount = len(caps_array) if caps_array is not None else 0
        security_caps.Reserved = 0

        size = ctypes.c_size_t(0)
        InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attr_mem = ctypes.create_string_buffer(size.value)
        attr_list = ctypes.cast(attr_mem, wintypes.LPVOID)
        _check_bool(
            InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(size)),
            'InitializeProcThreadAttributeList',
        )
        _check_bool(
            UpdateProcThreadAttribute(
                attr_list,
                0,
                PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security_caps),
                ctypes.sizeof(security_caps),
                None,
                None,
            ),
            'UpdateProcThreadAttribute',
        )

        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = wintypes.HANDLE(msvcrt.get_osfhandle(stdin_file.fileno()))
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(msvcrt.get_osfhandle(stdout_file.fileno()))
        startup.StartupInfo.hStdError = wintypes.HANDLE(msvcrt.get_osfhandle(stderr_file.fileno()))
        startup.lpAttributeList = attr_list

        proc_info = PROCESS_INFORMATION()
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        _check_bool(
            CreateProcessW(
                None,
                command_line,
                None,
                None,
                True,
                EXTENDED_STARTUPINFO_PRESENT,
                None,
                cwd,
                ctypes.byref(startup),
                ctypes.byref(proc_info),
            ),
            'CreateProcessW',
        )

        try:
            WaitForSingleObject(proc_info.hProcess, INFINITE)
            exit_code = wintypes.DWORD(1)
            _check_bool(
                GetExitCodeProcess(proc_info.hProcess, ctypes.byref(exit_code)),
                'GetExitCodeProcess',
            )
        finally:
            if proc_info.hThread:
                CloseHandle(proc_info.hThread)
            if proc_info.hProcess:
                CloseHandle(proc_info.hProcess)

        stdout_file.flush()
        stderr_file.flush()
        sys.stdout.write(stdout_path.read_text(encoding='utf-8', errors='replace'))
        sys.stderr.write(stderr_path.read_text(encoding='utf-8', errors='replace'))
        return int(exit_code.value)
    finally:
        stdout_file.close()
        stderr_file.close()
        stdin_file.close()
        if attr_mem is not None:
            try:
                DeleteProcThreadAttributeList(ctypes.cast(attr_mem, wintypes.LPVOID))
            except Exception:
                pass
        for cap_sid in capability_ptrs:
            if cap_sid:
                LocalFree(cap_sid)
        if sid:
            LocalFree(sid)
        _revoke_workspace_access(workspace, sid_string)
        try:
            DeleteAppContainerProfile(profile_name)
        except Exception:
            pass
        for path in (stdout_path, stderr_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    if os.name != 'nt':
        sys.stderr.write('AppContainer runner is only supported on Windows.\n')
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--network', choices=['0', '1'], default='0')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    command = list(ns.command)
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        sys.stderr.write('No child command supplied to AppContainer runner.\n')
        return 2

    workspace = Path(ns.workspace).resolve()
    cwd = str(Path(ns.cwd).resolve())
    return _launch(command, cwd=cwd, workspace=workspace, allow_network=ns.network == '1')


if __name__ == '__main__':
    raise SystemExit(main())