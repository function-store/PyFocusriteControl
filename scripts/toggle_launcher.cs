// Source for scripts\toggle.exe — a tiny windowless launcher (Windows subsystem
// = no console, no flash). Use it for hotkey tools (e.g. Logitech G HUB) that
// launch a real .exe but won't run .vbs / .lnk / scripts.
//
// It runs:  pythonw  <repo>\fc.py  <args, or "toggle" if none>
// The exe lives in <repo>\scripts\, so the repo is its parent folder. The Python
// interpreter is auto-detected, so this is portable across machines.
//
// Build it with:  scripts\build-launcher.ps1
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

class ToggleLauncher
{
    static void Main()
    {
        try
        {
            string[] argv = Environment.GetCommandLineArgs();
            string sub = argv.Length > 1
                ? string.Join(" ", argv, 1, argv.Length - 1)
                : "toggle";

            string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string repo = Path.GetFullPath(Path.Combine(exeDir, ".."));
            string fc = Path.Combine(repo, "fc.py");

            bool needsDash3;
            string pyw = ResolvePythonw(out needsDash3);
            string args = (needsDash3 ? "-3 " : "") + "\"" + fc + "\" " + sub;

            ProcessStartInfo psi = new ProcessStartInfo(pyw, args);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WorkingDirectory = repo;
            Process.Start(psi);
        }
        catch { /* windowless: nowhere to report to */ }
    }

    // Find a windowless Python. Prefer a real pythonw.exe (no shebang handling);
    // fall back to the "pyw" launcher on PATH, which needs -3 so it ignores
    // fc.py's unix shebang instead of chasing the MS Store python3 alias.
    static string ResolvePythonw(out bool needsDash3)
    {
        needsDash3 = false;

        string env = Environment.GetEnvironmentVariable("FC_PYTHONW");
        if (!string.IsNullOrEmpty(env) && File.Exists(env)) return env;

        string[] roots =
        {
            Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData), "Programs", "Python"),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
        };
        foreach (string root in roots)
        {
            try
            {
                if (!Directory.Exists(root)) continue;
                string[] dirs = Directory.GetDirectories(root, "Python3*");
                Array.Sort(dirs);
                Array.Reverse(dirs); // newest first
                foreach (string d in dirs)
                {
                    string cand = Path.Combine(d, "pythonw.exe");
                    if (File.Exists(cand)) return cand;
                }
            }
            catch { }
        }

        needsDash3 = true;
        return "pyw";
    }
}
