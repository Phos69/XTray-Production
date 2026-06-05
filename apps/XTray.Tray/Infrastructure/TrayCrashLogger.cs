using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows.Threading;
using WpfApplication = System.Windows.Application;

namespace XTray.Tray.Infrastructure;

internal static class TrayCrashLogger
{
    private static readonly object Gate = new();
    private static bool _configured;
    private static LogPaths _paths = DefaultPaths();

    public static string LogPath => _paths.LogPath;
    public static string CrashLogPath => _paths.CrashLogPath;

    public static void Configure(WpfApplication app)
    {
        lock (Gate)
        {
            if (_configured)
            {
                return;
            }
            _configured = true;
            EnsureLogDirectory();
            WritePreviousRunWarning();
            WriteInfo("C# tray logging configured");
            WriteRunningMarker();
        }

        app.DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    public static void MarkCleanShutdown()
    {
        try
        {
            WriteInfo("C# tray clean shutdown");
            if (File.Exists(_paths.RunningMarkerPath))
            {
                File.Delete(_paths.RunningMarkerPath);
            }
        }
        catch
        {
            // Crash logging must never become the reason the tray fails to close.
        }
    }

    public static void LogCrash(string source, Exception exception)
    {
        try
        {
            WriteCrash(source, exception.ToString());
        }
        catch
        {
            // Last-chance logging should be best effort only.
        }
    }

    internal static void UsePathsForTests(string directory)
    {
        lock (Gate)
        {
            _paths = new LogPaths(
                directory,
                Path.Combine(directory, "xtray-csharp.log"),
                Path.Combine(directory, "xtray-csharp-crash.log"),
                Path.Combine(directory, "xtray-csharp.running.json")
            );
            _configured = false;
        }
    }

    private static void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs args)
    {
        LogCrash("dispatcher unhandled exception", args.Exception);
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs args)
    {
        try
        {
            var detail = args.ExceptionObject is Exception exception
                ? exception.ToString()
                : args.ExceptionObject?.ToString() ?? "(no exception object)";
            WriteCrash($"appdomain unhandled exception terminating={args.IsTerminating}", detail);
        }
        catch
        {
            // Last-chance logging should be best effort only.
        }
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs args)
    {
        LogCrash("task unobserved exception", args.Exception);
    }

    private static void WritePreviousRunWarning()
    {
        try
        {
            if (!File.Exists(_paths.RunningMarkerPath))
            {
                return;
            }
            var marker = File.ReadAllText(_paths.RunningMarkerPath);
            WriteInfo($"previous C# tray run ended unexpectedly: {marker}");
        }
        catch
        {
            // Ignore corrupt or unreadable markers.
        }
    }

    private static void WriteRunningMarker()
    {
        var process = Process.GetCurrentProcess();
        var marker = new
        {
            component = "tray-csharp",
            pid = Environment.ProcessId,
            started_at = DateTimeOffset.Now.ToString("o"),
            executable = Redact(Environment.ProcessPath ?? process.MainModule?.FileName ?? string.Empty),
            argv = Redact(Environment.CommandLine),
            version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "unknown",
        };
        File.WriteAllText(
            _paths.RunningMarkerPath,
            JsonSerializer.Serialize(marker, new JsonSerializerOptions { WriteIndented = true })
        );
    }

    private static void WriteInfo(string message)
    {
        EnsureLogDirectory();
        File.AppendAllText(
            _paths.LogPath,
            $"{Timestamp()} INFO [pid={Environment.ProcessId}] {message}{Environment.NewLine}"
        );
    }

    private static void WriteCrash(string source, string detail)
    {
        EnsureLogDirectory();
        var header =
            $"{Timestamp()} ERROR [pid={Environment.ProcessId}] {source} version={Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "unknown"}";
        File.AppendAllText(
            _paths.LogPath,
            $"{header}{Environment.NewLine}{Redact(detail)}{Environment.NewLine}"
        );
        File.AppendAllText(
            _paths.CrashLogPath,
            $"{Environment.NewLine}--- {header} ---{Environment.NewLine}{Redact(detail)}{Environment.NewLine}"
        );
    }

    private static void EnsureLogDirectory() => Directory.CreateDirectory(_paths.Directory);

    private static string Timestamp() => DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss.fff zzz");

    private static string Redact(string value)
    {
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!string.IsNullOrWhiteSpace(profile))
        {
            value = value.Replace(profile, "%USERPROFILE%", StringComparison.OrdinalIgnoreCase);
        }
        return value;
    }

    private static LogPaths DefaultPaths()
    {
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XTray",
            "logs"
        );
        return new LogPaths(
            directory,
            Path.Combine(directory, "xtray-csharp.log"),
            Path.Combine(directory, "xtray-csharp-crash.log"),
            Path.Combine(directory, "xtray-csharp.running.json")
        );
    }

    private sealed record LogPaths(
        string Directory,
        string LogPath,
        string CrashLogPath,
        string RunningMarkerPath
    );
}
