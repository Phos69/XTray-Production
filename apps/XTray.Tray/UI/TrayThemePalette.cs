using System.Globalization;
using System.Text.Json;
using System.Windows.Media;
using XTray.Tray.Backend;
using Brush = System.Windows.Media.Brush;
using Color = System.Windows.Media.Color;
using ColorConverter = System.Windows.Media.ColorConverter;

namespace XTray.Tray.UI;

internal sealed class TrayThemePalette
{
    private readonly JsonElement _theme;
    private readonly JsonElement _tray;
    private readonly JsonElement _palette;
    private readonly JsonElement _metrics;

    private TrayThemePalette(JsonElement theme)
    {
        _theme = theme.ValueKind == JsonValueKind.Object ? theme.Clone() : EmptyObject();
        _tray = _theme.ObjectOrEmpty("tray");
        _palette = _theme.ObjectOrEmpty("palette");
        _metrics = _theme.ObjectOrEmpty("metrics");
    }

    public static TrayThemePalette FromSettings(JsonElement settings)
    {
        return new TrayThemePalette(settings.ObjectOrEmpty("theme_data"));
    }

    public string Name => _theme.StringOr("name", "vibrant");
    public string Surface => Tray("surface", "rgba(249, 249, 249, 245)");
    public string Control => Tray("control", "#ffffff");
    public string ControlHover => Tray("control_hover", "#f3f3f3");
    public string ControlPressed => Tray("control_pressed", "#e9e9e9");
    public string RowSurface => Tray("row_surface", "#ffffff");
    public string RowSurfaceHover => Tray("row_surface_hover", "#f8fafc");
    public string Border => Tray("border", "#d1d1d1");
    public string SubtleBorder => Tray("subtle_border", "#e5e5e5");
    public string Text => Tray("text", "#1a1a1a");
    public string Muted => Tray("muted", "#616161");
    public string Accent => Tray("accent", "#0067c0");
    public string AccentHover => Tray("accent_hover", "#005a9e");
    public string AccentPressed => Tray("accent_pressed", "#004578");
    public string AccentText => Tray("accent_text", "#ffffff");
    public string Success => Tray("success", "#107c10");
    public string SuccessText => Tray("success_text", "#ffffff");
    public string Warning => Tray("warning", "#b45309");
    public string WarningText => Tray("warning_text", "#ffffff");
    public string CloseHover => Tray("close_hover", "#c42b1c");
    public string ClosePressed => Tray("close_pressed", "#a4261d");
    public string CloseText => Tray("close_text", "#ffffff");
    public string IndicatorConnected => Tray("indicator_connected", "#107c10");
    public string IndicatorDisconnected => Tray("indicator_disconnected", "#c42b1c");
    public string IndicatorDisabled => Tray("indicator_disabled", "#7f8c8d");
    public string FaceplateEnabledBg => Tray("faceplate_enabled_bg", Accent);
    public string FaceplateEnabledText => Tray("faceplate_enabled_text", AccentText);
    public string FaceplateDisabledBg => Tray("faceplate_disabled_bg", AccentPressed);
    public string FaceplateDisabledText => Tray("faceplate_disabled_text", AccentText);
    public string FaceplatePrimaryBg => Tray("faceplate_primary_bg", "#cfe2f3");
    public string FaceplatePrimaryBorder => Tray("faceplate_primary_border", Accent);
    public string FaceplatePrimaryText => Tray("faceplate_primary_text", "#0a1a33");
    public string FaceplateUnavailableBg => Tray("faceplate_unavailable_bg", ControlPressed);
    public string FaceplateUnavailableText => Tray("faceplate_unavailable_text", Muted);
    public string Danger => Palette("danger", "#c42b1c");
    public string DangerText => Palette("danger_text", "#ffffff");

    public int RadiusSmall => _metrics.IntOr("radius_small", 6);
    public int RadiusMedium => _metrics.IntOr("radius_medium", 8);
    public int RadiusPanel => _metrics.IntOr("radius_panel", 14);
    public int ControlHeight => _metrics.IntOr("control_height", 30);

    public Brush Brush(string color) => FrozenBrush(ParseColor(color, Colors.Transparent));
    public Brush SurfaceBrush => Brush(Surface);
    public Brush TextBrush => Brush(Text);
    public Brush MutedBrush => Brush(Muted);
    public Brush BorderBrush => Brush(Border);
    public Brush SubtleBorderBrush => Brush(SubtleBorder);
    public Brush AccentBrush => Brush(Accent);
    public Brush AccentTextBrush => Brush(AccentText);
    public Brush ControlBrush => Brush(Control);
    public Brush ControlHoverBrush => Brush(ControlHover);
    public Brush ControlPressedBrush => Brush(ControlPressed);

    public string FaceplateBackgroundFor(string state) => state switch
    {
        "primary" => FaceplatePrimaryBg,
        "enabled" or "active" or "ok" => FaceplateEnabledBg,
        "limited" or "warning" or "disabled" => FaceplateDisabledBg,
        "full" or "disconnected" => Danger,
        "unavailable" => FaceplateUnavailableBg,
        _ => RowSurface,
    };

    public string FaceplateTextFor(string state) => state switch
    {
        "primary" => FaceplatePrimaryText,
        "enabled" or "active" or "ok" => FaceplateEnabledText,
        "limited" or "warning" or "disabled" => FaceplateDisabledText,
        "full" or "disconnected" => DangerText,
        "unavailable" => FaceplateUnavailableText,
        _ => Text,
    };

    public string IndicatorColor(string state) => state switch
    {
        "connected" => IndicatorConnected,
        "disconnected" => IndicatorDisconnected,
        _ => IndicatorDisabled,
    };

    public static Color ParseColor(string? value, Color fallback)
    {
        var text = (value ?? "").Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            return fallback;
        }
        if (text.StartsWith("rgba", StringComparison.OrdinalIgnoreCase)
            || text.StartsWith("rgb", StringComparison.OrdinalIgnoreCase))
        {
            var open = text.IndexOf('(');
            var close = text.LastIndexOf(')');
            if (open >= 0 && close > open)
            {
                var parts = text[(open + 1)..close]
                    .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length is 3 or 4
                    && byte.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var r)
                    && byte.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var g)
                    && byte.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out var b))
                {
                    var a = (byte)255;
                    if (parts.Length == 4)
                    {
                        if (byte.TryParse(parts[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out var alphaByte))
                        {
                            a = alphaByte;
                        }
                        else if (double.TryParse(parts[3], NumberStyles.Float, CultureInfo.InvariantCulture, out var alphaFloat))
                        {
                            a = (byte)Math.Clamp((int)Math.Round(alphaFloat * 255), 0, 255);
                        }
                    }
                    return Color.FromArgb(a, r, g, b);
                }
            }
        }
        if (text.StartsWith('#'))
        {
            var hex = text[1..];
            if (hex.Length == 3)
            {
                hex = string.Concat(hex.Select(ch => $"{ch}{ch}"));
            }
            if (hex.Length == 6
                && int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var rgb))
            {
                return Color.FromRgb(
                    (byte)((rgb >> 16) & 0xff),
                    (byte)((rgb >> 8) & 0xff),
                    (byte)(rgb & 0xff)
                );
            }
        }
        try
        {
            return (Color)ColorConverter.ConvertFromString(text);
        }
        catch
        {
            return fallback;
        }
    }

    private string Tray(string name, string fallback) => _tray.StringOr(name, fallback);
    private string Palette(string name, string fallback) => _palette.StringOr(name, fallback);

    private static SolidColorBrush FrozenBrush(Color color)
    {
        var brush = new SolidColorBrush(color);
        brush.Freeze();
        return brush;
    }

    private static JsonElement EmptyObject()
    {
        using var document = JsonDocument.Parse("{}");
        return document.RootElement.Clone();
    }
}
