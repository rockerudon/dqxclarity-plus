using System.Globalization;

namespace DqxClarity.Launcher.Models;

/// <summary>Maps a language code (e.g. "en") to a human-readable name (e.g. "English") using the
/// .NET/ICU culture data — no hardcoded table. Falls back to the raw code for unknown codes.</summary>
public static class LanguageNames
{
    private static readonly IReadOnlyDictionary<string, string> PreferredNames =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["pt-BR"] = "Brazilian Portuguese",
            ["pt-PT"] = "European Portuguese",
            ["zh-Hans"] = "Simplified Chinese",
            ["zh-Hant"] = "Traditional Chinese",
        };

    public static string DisplayName(string? code)
    {
        if (string.IsNullOrWhiteSpace(code)) return "";
        var canonical = LanguageCodes.Normalize(code);
        if (PreferredNames.TryGetValue(canonical, out var preferred)) return preferred;
        try { return CultureInfo.GetCultureInfo(canonical).EnglishName; }
        catch (CultureNotFoundException) { return canonical; }
    }
}
