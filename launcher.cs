using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace YawYaw {
    static class Program {
        [STAThread]
        static void Main(string[] args) {
            try {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                
                string pythonw = Path.Combine(baseDir, "runtime", "pythonw.exe");
                if (!File.Exists(pythonw)) {
                    pythonw = Path.Combine(baseDir, "runtime", "python.exe");
                }
                if (!File.Exists(pythonw)) {
                    pythonw = Path.Combine(baseDir, "venv", "Scripts", "pythonw.exe");
                }
                if (!File.Exists(pythonw)) {
                    pythonw = Path.Combine(baseDir, "venv", "Scripts", "python.exe");
                }
                
                string script = Path.Combine(baseDir, "desktop_app.py");
                if (!File.Exists(script)) {
                    MessageBox.Show("Could not find desktop_app.py in:\n" + baseDir, "Yaw-Yaw Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                
                if (!File.Exists(pythonw)) {
                    MessageBox.Show("Could not find Python runtime in:\n" + baseDir + "\nPlease reinstall Yaw-Yaw.", "Yaw-Yaw Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                
                ProcessStartInfo startInfo = new ProcessStartInfo();
                startInfo.FileName = pythonw;
                string scriptArg = "\"" + script + "\"";
                if (args.Length > 0) {
                    scriptArg += " " + string.Join(" ", args);
                } else {
                    scriptArg += " --offline";
                }
                startInfo.Arguments = scriptArg;
                startInfo.WorkingDirectory = baseDir;
                startInfo.UseShellExecute = false;
                startInfo.CreateNoWindow = true;
                
                // Force fully offline operation
                startInfo.EnvironmentVariables["HF_HUB_OFFLINE"] = "1";
                startInfo.EnvironmentVariables["TRANSFORMERS_OFFLINE"] = "1";
                startInfo.EnvironmentVariables["HF_HUB_DISABLE_TELEMETRY"] = "1";
                startInfo.EnvironmentVariables["DO_NOT_TRACK"] = "1";
                startInfo.EnvironmentVariables["KOKORO_BASE_DIR"] = Path.Combine(baseDir, "kokoro-data");
                
                Process.Start(startInfo);
            } catch (Exception ex) {
                MessageBox.Show("Failed to launch Yaw-Yaw:\n" + ex.Message, "Yaw-Yaw Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
