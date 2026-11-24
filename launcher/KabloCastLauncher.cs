using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace KabloCastLauncher
{
    internal static class Program
    {
        [STAThread]
        private static int Main()
        {
            Application.EnableVisualStyles();
            string rootDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar
            );
            string launchScript = Path.Combine(rootDir, "launch_kablocast.py");
            if (!File.Exists(launchScript))
            {
                MessageBox.Show(
                    "launch_kablocast.py not found in:\n" + rootDir,
                    "KabloCast",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }

            string pythonExe = FindVenvPython(rootDir);
            if (string.IsNullOrEmpty(pythonExe))
            {
                string setupBat = Path.Combine(rootDir, "setup.bat");
                if (File.Exists(setupBat))
                {
                    DialogResult choice = MessageBox.Show(
                        "KabloCast virtual environment is not installed yet.\n"
                        + "Run setup.bat now to install dependencies?\n\n"
                        + "(KabloCast sanal ortami henuz kurulmamis. Simdi otomatik kurulsun mu?)",
                        "KabloCast Setup",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Information
                    );
                    if (choice != DialogResult.Yes)
                    {
                        return 0;
                    }
                    if (!RunSetup(rootDir, setupBat))
                    {
                        return 1;
                    }
                    pythonExe = FindVenvPython(rootDir);
                }

                if (string.IsNullOrEmpty(pythonExe))
                {
                    MessageBox.Show(
                        "Python environment (backend\\.venv) was not found.\n"
                        + "Please run setup.bat first.",
                        "KabloCast",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return 1;
                }
            }

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = "\"" + launchScript + "\"",
                    WorkingDirectory = rootDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                Process.Start(psi);
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Failed to launch KabloCast:\n" + ex.Message,
                    "KabloCast",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }
        }

        private static string FindVenvPython(string rootDir)
        {
            string pythonw = Path.Combine(rootDir, "backend", ".venv", "Scripts", "pythonw.exe");
            if (File.Exists(pythonw))
            {
                return pythonw;
            }
            string python = Path.Combine(rootDir, "backend", ".venv", "Scripts", "python.exe");
            if (File.Exists(python))
            {
                return python;
            }
            return string.Empty;
        }

        private static bool RunSetup(string rootDir, string setupBat)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = "/c \"" + setupBat + "\"",
                    WorkingDirectory = rootDir,
                    UseShellExecute = true
                };
                using (Process proc = Process.Start(psi))
                {
                    if (proc == null)
                    {
                        return false;
                    }
                    proc.WaitForExit();
                    return proc.ExitCode == 0;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Setup failed:\n" + ex.Message,
                    "KabloCast Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return false;
            }
        }
    }
}
