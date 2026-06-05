using System.IO;
using System.Text.Json;
using System.Windows;

namespace XTray.Tray.UI;

internal sealed class TrayWindowStateStore
{
    private readonly string? _path;
    private readonly Dictionary<string, WindowBounds> _states = new(StringComparer.OrdinalIgnoreCase);
    private bool _loaded;

    public TrayWindowStateStore(string? path)
    {
        _path = path;
    }

    public static TrayWindowStateStore Default()
    {
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XTray"
        );
        return new TrayWindowStateStore(Path.Combine(directory, "tray-window-state.json"));
    }

    public static TrayWindowStateStore Disabled { get; } = new(null);

    public bool HasState(string key)
    {
        EnsureLoaded();
        return _states.ContainsKey(key);
    }

    public bool Attach(Window window, string key)
    {
        var restored = Apply(window, key);
        window.LocationChanged += (_, _) => Save(window, key);
        window.SizeChanged += (_, _) => Save(window, key);
        window.StateChanged += (_, _) => Save(window, key);
        window.Closed += (_, _) => Save(window, key);
        return restored;
    }

    public bool Apply(Window window, string key)
    {
        EnsureLoaded();
        if (!_states.TryGetValue(key, out var bounds))
        {
            return false;
        }

        var workArea = SystemParameters.WorkArea;
        window.Width = Math.Clamp(bounds.Width, window.MinWidth, Math.Max(window.MinWidth, workArea.Width));
        window.Height = Math.Clamp(bounds.Height, window.MinHeight, Math.Max(window.MinHeight, workArea.Height));
        window.Left = Math.Clamp(bounds.Left, workArea.Left, Math.Max(workArea.Left, workArea.Right - window.Width));
        window.Top = Math.Clamp(bounds.Top, workArea.Top, Math.Max(workArea.Top, workArea.Bottom - window.Height));
        return true;
    }

    public void Save(Window window, string key)
    {
        if (string.IsNullOrWhiteSpace(_path) || window.WindowState == WindowState.Minimized)
        {
            return;
        }
        if (!IsFinite(window.Left) || !IsFinite(window.Top) || !IsFinite(window.Width) || !IsFinite(window.Height))
        {
            return;
        }

        EnsureLoaded();
        _states[key] = new WindowBounds(window.Left, window.Top, window.Width, window.Height);
        var directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(
            _path,
            JsonSerializer.Serialize(_states, new JsonSerializerOptions { WriteIndented = true })
        );
    }

    private void EnsureLoaded()
    {
        if (_loaded)
        {
            return;
        }
        _loaded = true;
        if (string.IsNullOrWhiteSpace(_path) || !File.Exists(_path))
        {
            return;
        }
        try
        {
            var loaded = JsonSerializer.Deserialize<Dictionary<string, WindowBounds>>(
                File.ReadAllText(_path)
            );
            if (loaded is null)
            {
                return;
            }
            foreach (var (key, bounds) in loaded)
            {
                if (bounds.IsValid)
                {
                    _states[key] = bounds;
                }
            }
        }
        catch
        {
            _states.Clear();
        }
    }

    private static bool IsFinite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);

    internal sealed record WindowBounds(double Left, double Top, double Width, double Height)
    {
        public bool IsValid => IsFinite(Left) && IsFinite(Top) && Width > 0 && Height > 0;
    }
}
