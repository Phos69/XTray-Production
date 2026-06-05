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
