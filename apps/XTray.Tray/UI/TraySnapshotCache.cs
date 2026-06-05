using System.IO;
using System.Text.Json;
using XTray.Tray.Backend;

namespace XTray.Tray.UI;

internal sealed class TraySnapshotCache
{
    private readonly string? _path;

    public TraySnapshotCache(string? path)
    {
        _path = path;
    }

    public static TraySnapshotCache Default()
    {
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XTray"
        );
        return new TraySnapshotCache(Path.Combine(directory, "tray-snapshot.json"));
    }

    public static TraySnapshotCache Disabled { get; } = new(null);

    public TraySnapshot? TryLoad()
    {
        if (string.IsNullOrWhiteSpace(_path) || !File.Exists(_path))
        {
            return null;
        }
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(_path));
            var snapshot = new TraySnapshot(document.RootElement);
            return snapshot.HasPendingDeviceData ? null : snapshot;
        }
        catch
        {
            return null;
        }
    }

    public void Save(TraySnapshot snapshot)
    {
        if (string.IsNullOrWhiteSpace(_path) || snapshot.HasPendingDeviceData)
        {
            return;
        }
        var directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(_path, snapshot.Root.GetRawText());
    }
}
