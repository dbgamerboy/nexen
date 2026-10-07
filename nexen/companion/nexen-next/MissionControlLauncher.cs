using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// Shell exe for NEXEN MISSION CONTROL. It only starts the Python app; updates never need a rebuild.
static class Program
{
    [STAThread]
    static void Main()
    {
        string dir = Path.GetDirectoryName(Application.ExecutablePath);
        string py = @"H:\NEXEN_RUNTIME\python-recovery\Scripts\pythonw.exe";
        string script = Path.Combine(dir, "nexen_next.py");
        if (!File.Exists(py) || !File.Exists(script))
        {
            MessageBox.Show("Missing:\n" + (File.Exists(py) ? "" : py + "\n") + (File.Exists(script) ? "" : script), "NEXEN MISSION CONTROL");
            return;
        }
        foreach (var p in Process.GetProcessesByName("pythonw"))
        {
            if (p.MainWindowTitle == "NEXEN MISSION CONTROL") { return; } // already open
        }
        var psi = new ProcessStartInfo(py, "\"" + script + "\"") { WorkingDirectory = dir, UseShellExecute = false, CreateNoWindow = true };
        Process.Start(psi);
    }
}
