using System.Text.RegularExpressions;

namespace DqxClarity.Launcher.Models;

/// <summary>Canonical BCP 47 language identity shared by packs and runtime configuration.</summary>
public static partial class LanguageCodes
{
    public const string Default = "en";
    public const string Source = "ja";

    [GeneratedRegex("^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$", RegexOptions.CultureInvariant)]
    private static partial Regex LanguageCodeRegex();

    public static bool TryNormalize(string? value, out string normalized)
    {
        normalized = "";
        var raw = (value ?? "").Trim().Replace('_', '-');
        if (!LanguageCodeRegex().IsMatch(raw)) return false;

        var parts = raw.Split('-');
        parts[0] = parts[0].ToLowerInvariant();
        for (var i = 1; i < parts.Length; i++)
        {
            var part = parts[i];
            if (part.Length == 4 && part.All(char.IsLetter))
                parts[i] = char.ToUpperInvariant(part[0]) + part[1..].ToLowerInvariant();
            else if ((part.Length == 2 && part.All(char.IsLetter)) ||
                     (part.Length == 3 && part.All(char.IsDigit)))
                parts[i] = part.ToUpperInvariant();
            else
                parts[i] = part.ToLowerInvariant();
        }

        normalized = string.Join('-', parts);
        return true;
    }

    public static string Normalize(string? value, string fallback = Default) =>
        TryNormalize(value, out var normalized)
            ? normalized
            : TryNormalize(fallback, out var normalizedFallback)
                ? normalizedFallback
                : Default;
}
