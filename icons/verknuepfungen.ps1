# Legt Verknuepfungen fuer Harness und Fernsteuerung an (Startmenue + Desktop), mit Icon und eigener Taskleisten-ID.
#   powershell -ExecutionPolicy Bypass -File icons\verknuepfungen.ps1
$ErrorActionPreference = "Stop"
$kit = Split-Path $PSScriptRoot -Parent
$pyw = (Get-Command pythonw).Source

Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, Pack=4)] public struct PKEY { public Guid g; public uint pid; }
[StructLayout(LayoutKind.Sequential)] public struct PV { public ushort vt; ushort a,b,c; public IntPtr p; IntPtr q; }
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore { void GetCount(out uint c); void GetAt(uint i, out PKEY k); void GetValue(ref PKEY k, out PV v);
  void SetValue(ref PKEY k, ref PV v); void Commit(); }
[ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPersistFile { void GetClassID(out Guid g); [PreserveSig] int IsDirty(); void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m);
  void Save([MarshalAs(UnmanagedType.LPWStr)] string f, bool r); void SaveCompleted(string f); void GetCurFile(out IntPtr f); }
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
public static class AppId {
  public static void Set(string lnk, string id) {
    var o = new ShellLink(); ((IPersistFile)o).Load(lnk, 2);
    var k = new PKEY { g = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    var v = new PV { vt = 31, p = Marshal.StringToCoTaskMemUni(id) };
    ((IPropertyStore)o).SetValue(ref k, ref v); ((IPropertyStore)o).Commit();
    ((IPersistFile)o).Save(lnk, true); Marshal.FreeCoTaskMem(v.p); }
}
"@

$sh = New-Object -ComObject WScript.Shell
$start = Join-Path ([Environment]::GetFolderPath("Programs")) "RoboForge"
New-Item -ItemType Directory -Force $start | Out-Null
$desk = [Environment]::GetFolderPath("Desktop")
foreach ($a in @(@{n="RoboForge Harness"; s="ros.py"; i="harness"}, @{n="RoboForge Fernsteuerung"; s="fernsteuerung.py"; i="fernsteuerung"},
                 @{n="Physical AI Harness"; s="physical_ai_harness.py"; i="plattform"})) {
  foreach ($dir in @($start, $desk)) {
    $lnk = Join-Path $dir "$($a.n).lnk"
    $l = $sh.CreateShortcut($lnk)
    $l.TargetPath = $pyw
    $l.Arguments = "`"$(Join-Path $kit $a.s)`""
    $l.WorkingDirectory = $kit
    $l.IconLocation = "$(Join-Path $kit "icons\$($a.i).ico"),0"
    $l.Description = $a.n
    $l.Save()
    [AppId]::Set($lnk, "RoboForge.$($a.i)")
    Write-Output "ok: $lnk"
  }
}
