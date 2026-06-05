using System.Net;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using XTray.Tray.Backend;
using IoPath = System.IO.Path;
using ShapePath = System.Windows.Shapes.Path;

namespace XTray.Tray.UI;

internal sealed partial class TrayIconCache
{
    private const string XTrayTrayGlyphId = "asset:xtray_tray_glyph";
    private const string XTrayTrayGlyphPath = "M30 230 H120 L135 245 H205 L220 230 H310 L295 275 H45 Z";
    private static readonly IReadOnlyDictionary<string, string> BuiltInMdiPaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["mdi:desktop-tower-monitor"] = "M22,18H17A1,1 0 0,1 16,17V7A1,1 0 0,1 17,6H22A1,1 0 0,1 23,7V17A1,1 0 0,1 22,18M22,8H17V9H22V8M22,10H17V11H22V10M9,15V17H10V18H5V17H6V15H2A1,1 0 0,1 1,14V7A1,1 0 0,1 2,6H13A1,1 0 0,1 14,7V14A1,1 0 0,1 13,15H9M12,8H3V13H12V8Z",
        ["mdi:multimedia"] = "M9 13V5C9 3.9 9.9 3 11 3H20C21.1 3 22 3.9 22 5V11H18.57L17.29 9.26C17.23 9.17 17.11 9.17 17.05 9.26L15.06 12C15 12.06 14.88 12.07 14.82 12L13.39 10.25C13.33 10.18 13.22 10.18 13.16 10.25L11.05 12.91C10.97 13 11.04 13.15 11.16 13.15H17.5V15H11C9.89 15 9 14.11 9 13M6 22V21H4V22H2V2H4V3H6V2H8.39C7.54 2.74 7 3.8 7 5V13C7 15.21 8.79 17 11 17H15.7C14.67 17.83 14 19.08 14 20.5C14 21.03 14.11 21.53 14.28 22H6M4 7H6V5H4V7M4 11H6V9H4V11M4 15H6V13H4V15M6 19V17H4V19H6M23 13V15H21V20.5C21 21.88 19.88 23 18.5 23S16 21.88 16 20.5 17.12 18 18.5 18C18.86 18 19.19 18.07 19.5 18.21V13H23Z",
        ["mdi:speaker"] = "M12,12A3,3 0 0,0 9,15A3,3 0 0,0 12,18A3,3 0 0,0 15,15A3,3 0 0,0 12,12M12,20A5,5 0 0,1 7,15A5,5 0 0,1 12,10A5,5 0 0,1 17,15A5,5 0 0,1 12,20M12,4A2,2 0 0,1 14,6A2,2 0 0,1 12,8C10.89,8 10,7.1 10,6C10,4.89 10.89,4 12,4M17,2H7C5.89,2 5,2.89 5,4V20A2,2 0 0,0 7,22H17A2,2 0 0,0 19,20V4C19,2.89 18.1,2 17,2Z",
        ["mdi:television"] = "M21,17H3V5H21M21,3H3A2,2 0 0,0 1,5V17A2,2 0 0,0 3,19H8V21H16V19H21A2,2 0 0,0 23,17V5A2,2 0 0,0 21,3Z",
        ["mdi:television-speaker"] = "M3 3C1.9 3 1 3.9 1 5V17C1 18.1 1.9 19 3 19H8V21H12V17H3V5H21V7H23V5C23 3.9 22.1 3 21 3H3M21 9H16C14.9 9 14 9.9 14 11V20C14 21.1 14.9 22 16 22H21C22.1 22 23 21.1 23 20V11C23 9.9 22.1 9 21 9M18.5 10.5C19.3 10.5 20 11.2 20 12S19.3 13.5 18.5 13.5 17 12.8 17 12 17.7 10.5 18.5 10.5M18.5 20.5C16.8 20.5 15.5 19.2 15.5 17.5C15.5 15.9 16.8 14.5 18.4 14.5H18.5C20.2 14.5 21.5 15.8 21.5 17.5S20.2 20.5 18.5 20.5M18.5 16C17.7 16 17 16.7 17 17.5S17.7 19 18.5 19 20 18.3 20 17.5 19.3 16 18.5 16Z",
        ["mdi:volume-high"] = "M14,3.23V5.29C16.89,6.15 19,8.83 19,12C19,15.17 16.89,17.84 14,18.7V20.77C18,19.86 21,16.28 21,12C21,7.72 18,4.14 14,3.23M16.5,12C16.5,10.23 15.5,8.71 14,7.97V16C15.5,15.29 16.5,13.76 16.5,12M3,9V15H7L12,20V4L7,9H3Z",
        ["mdi:volume-low"] = "M7,9V15H11L16,20V4L11,9H7Z",
        ["mdi:volume-medium"] = "M5,9V15H9L14,20V4L9,9M18.5,12C18.5,10.23 17.5,8.71 16,7.97V16C17.5,15.29 18.5,13.76 18.5,12Z",
        ["mdi:volume-mute"] = "M3,9H7L12,4V20L7,15H3V9M16.59,12L14,9.41L15.41,8L18,10.59L20.59,8L22,9.41L19.41,12L22,14.59L20.59,16L18,13.41L15.41,16L14,14.59L16.59,12Z",
        ["mdi:volume-off"] = "M12,4L9.91,6.09L12,8.18M4.27,3L3,4.27L7.73,9H3V15H7L12,20V13.27L16.25,17.53C15.58,18.04 14.83,18.46 14,18.7V20.77C15.38,20.45 16.63,19.82 17.68,18.96L19.73,21L21,19.73L12,10.73M19,12C19,12.94 18.8,13.82 18.46,14.64L19.97,16.15C20.62,14.91 21,13.5 21,12C21,7.72 18,4.14 14,3.23V5.29C16.89,6.15 19,8.83 19,12M16.5,12C16.5,10.23 15.5,8.71 14,7.97V10.18L16.45,12.63C16.5,12.43 16.5,12.21 16.5,12Z",
    };
    private readonly JsonRpcClient? _backend;
    private readonly string? _cachePath;
    private readonly Dictionary<string, SvgIconData> _icons = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _requested = new(StringComparer.OrdinalIgnoreCase);

    public TrayIconCache(JsonRpcClient? backend = null)
        : this(backend, DefaultCachePath())
    {
    }

    internal TrayIconCache(JsonRpcClient? backend, string? cachePath)
    {
        _backend = backend;
        _cachePath = cachePath;
        SeedBuiltInIcons();
        LoadCachedIcons();
    }

    public async Task WarmAsync(IEnumerable<string> ids)
    {
        if (_backend is null)
        {
            return;
        }
        var wanted = ids
            .Select(NormalizeIconId)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(id => !_icons.ContainsKey(id) && _requested.Add(id))
            .ToArray();
        if (wanted.Length == 0)
        {
            return;
        }
        var result = await _backend.CallAsync(
            "assets.svg",
            new { ids = wanted },
            timeout: TimeSpan.FromSeconds(10)
        );
        var icons = result.ObjectOrEmpty("icons");
        var changed = false;
        foreach (var property in icons.ObjectProperties())
        {
            var svg = property.Value.ValueKind == JsonValueKind.String
                ? property.Value.GetString()
                : null;
            if (TryParse(svg, out var data))
            {
                _icons[NormalizeIconId(property.Name)] = data;
                changed = true;
            }
        }
        if (changed)
        {
            SaveCachedIcons();
        }
    }

    public void Seed(string id, string svg)
    {
        if (TryParse(svg, out var data))
        {
            _icons[NormalizeIconId(id)] = data;
            SaveCachedIcons();
        }
    }

    public FrameworkElement Icon(
        string? id,
        string color,
        double size = 20,
        string fallback = ""
    )
    {
        var normalized = NormalizeIconId(id);
        if (!string.IsNullOrWhiteSpace(normalized) && _icons.TryGetValue(normalized, out var data))
        {
            var path = new ShapePath
            {
                Data = Geometry.Parse(data.PathData),
                Fill = new SolidColorBrush(TrayThemePalette.ParseColor(color, Colors.Black)),
                Stretch = Stretch.Uniform,
                Width = size,
                Height = size,
                SnapsToDevicePixels = true,
            };
            return new Viewbox
            {
                Width = size,
                Height = size,
                Child = path,
            };
        }
        return new TextBlock
        {
            Text = string.IsNullOrWhiteSpace(fallback) ? "?" : fallback,
            Width = size,
            Height = size,
            TextAlignment = TextAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = new SolidColorBrush(TrayThemePalette.ParseColor(color, Colors.Black)),
            FontSize = Math.Max(9, size * 0.5),
            FontWeight = FontWeights.SemiBold,
        };
    }

    public static string NormalizeIconId(string? id)
    {
        var text = (id ?? "").Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            return "";
        }
        if (text.StartsWith("asset:", StringComparison.OrdinalIgnoreCase))
        {
            return text;
        }
        return text.StartsWith("mdi:", StringComparison.OrdinalIgnoreCase) ? text : $"mdi:{text}";
    }

    private static bool TryParse(string? svg, out SvgIconData data)
    {
        data = default;
        if (string.IsNullOrWhiteSpace(svg))
        {
            return false;
        }
        var pathMatch = PathRegex().Match(svg);
        if (!pathMatch.Success)
        {
            return false;
        }
        var pathData = WebUtility.HtmlDecode(pathMatch.Groups["d"].Value);
        if (string.IsNullOrWhiteSpace(pathData))
        {
            return false;
        }
        data = new SvgIconData(pathData, svg);
        return true;
    }

    private void LoadCachedIcons()
    {
        if (string.IsNullOrWhiteSpace(_cachePath) || !File.Exists(_cachePath))
        {
            return;
        }
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(_cachePath));
            foreach (var property in document.RootElement.ObjectProperties())
            {
                var svg = property.Value.ValueKind == JsonValueKind.String
                    ? property.Value.GetString()
                    : null;
                if (TryParse(svg, out var data))
                {
                    _icons[NormalizeIconId(property.Name)] = data;
                }
            }
        }
        catch
        {
            _icons.Clear();
        }
    }

    private void SeedBuiltInIcons()
    {
        _icons[XTrayTrayGlyphId] = new SvgIconData(XTrayTrayGlyphPath, null);
        foreach (var pair in BuiltInMdiPaths)
        {
            _icons[pair.Key] = new SvgIconData(pair.Value, null);
        }
    }

    private void SaveCachedIcons()
    {
        if (string.IsNullOrWhiteSpace(_cachePath))
        {
            return;
        }
        var payload = _icons
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Value.Svg))
            .OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(pair => pair.Key, pair => pair.Value.Svg!, StringComparer.OrdinalIgnoreCase);
        var directory = IoPath.GetDirectoryName(_cachePath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(
            _cachePath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })
        );
    }

    private static string DefaultCachePath()
    {
        var directory = IoPath.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XTray"
        );
        return IoPath.Combine(directory, "tray-icons.json");
    }

    [GeneratedRegex("<path\\b[^>]*\\bd=(['\\\"])(?<d>.*?)\\1", RegexOptions.IgnoreCase | RegexOptions.Singleline)]
    private static partial Regex PathRegex();

    private readonly record struct SvgIconData(string PathData, string? Svg);
}
