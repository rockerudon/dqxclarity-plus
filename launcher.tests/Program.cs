using DqxClarity.Launcher.Models;
using DqxClarity.Launcher.Services;
using Microsoft.Data.Sqlite;
using System.IO.Compression;

static void Assert(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

Assert(LanguageCodes.Normalize("PT_br") == "pt-BR", "BCP 47 normalization failed");
Assert(LanguageNames.DisplayName("pt-BR") == "Brazilian Portuguese", "pt-BR display name failed");
Assert(LanguageNames.DisplayName("zh-Hant") == "Traditional Chinese", "script display name failed");
Assert(UpdateService.DefaultRepository == "rockerudon/dqxclarity-multilang", "updater does not target the fork");

var temp = Path.Combine(Path.GetTempPath(), $"dqxclarity-launcher-test-{Guid.NewGuid():N}");
Directory.CreateDirectory(temp);
try
{
    var config = new ConfigService(temp);
    config.SaveTargetLanguage("PT_br", "");
    var ini = File.ReadAllText(Path.Combine(temp, "user_settings.ini"));
    Assert(ini.Contains("target_language = pt-BR"), "launcher did not persist canonical target language");
    Assert(ini.Contains("target_language_name = Brazilian Portuguese"), "launcher did not persist provider name");
    var loaded = config.Load();
    Assert(loaded.Translation.TargetLanguage == "pt-BR", "launcher did not reload target language");
    Assert(!loaded.Translation.ApiTranslationOverlay, "API translation overlay must be opt-in");
    Assert(!loaded.Translation.GoogleFreeYandexFallback, "Google/Yandex fallback must be opt-in");

    config.SaveApiTranslationOverlay(true);
    loaded = config.Load();
    Assert(loaded.Translation.ApiTranslationOverlay, "launcher did not persist the API translation overlay");

    config.SaveGoogleFreeYandexFallback(true);
    loaded = config.Load();
    Assert(loaded.Translation.GoogleFreeYandexFallback, "launcher did not persist Google/Yandex fallback");

    config.Save(new LauncherConfig(), new TranslationConfig
    {
        TranslateService = "googlefree",
        TargetLanguage = "es",
        TargetLanguageName = "Spanish",
        ApiTranslationOverlay = true,
        GoogleFreeYandexFallback = true,
    });
    loaded = config.Load();
    Assert(loaded.Translation.TargetLanguage == "es", "settings save ignored the API target dropdown value");
    Assert(loaded.Translation.TargetLanguageName == "Spanish", "settings save ignored the API target display name");
    Assert(loaded.Translation.ApiTranslationOverlay, "settings save dropped the API translation overlay");
    Assert(loaded.Translation.GoogleFreeYandexFallback, "settings save dropped Google/Yandex fallback");
    ini = File.ReadAllText(Path.Combine(temp, "user_settings.ini"));
    Assert(ini.Contains("ascii_output_languages = *"), "launcher did not persist the safe game character policy");

    var misc = Path.Combine(temp, "misc_files");
    Directory.CreateDirectory(misc);
    var dbPath = Path.Combine(misc, "clarity_dialog.db");
    using (var connection = new SqliteConnection($"Data Source={dbPath}"))
    {
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE dialog (ja TEXT PRIMARY KEY, en TEXT);
            INSERT INTO dialog VALUES ('ja', 'en');
            CREATE TABLE translation_values (
                domain TEXT, source_text TEXT, language_code TEXT,
                translated_text TEXT, translation_kind TEXT, context TEXT);
            INSERT INTO translation_values VALUES ('dialog', 'a', 'pt-BR', 'auto', 'machine', '');
            INSERT INTO translation_values VALUES ('dialog', 'b', 'pt-BR', 'manual', 'manual', '');
            """;
        command.ExecuteNonQuery();
    }
    new DatabaseService(temp).PurgeDialogCache();
    using (var connection = new SqliteConnection($"Data Source={dbPath}"))
    {
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM dialog";
        Assert(Convert.ToInt32(command.ExecuteScalar()) == 0, "legacy dialog cache was not purged");
        command.CommandText = "SELECT translation_kind FROM translation_values";
        Assert((string?)command.ExecuteScalar() == "manual", "language cache purge did not preserve manual rows");
    }
}
finally
{
    SqliteConnection.ClearAllPools();
    Directory.Delete(temp, recursive: true);
}

using var zip = new MemoryStream();
using (var archive = new ZipArchive(zip, ZipArchiveMode.Create, leaveOpen: true)) { }
var zipBytes = zip.ToArray();
using var clpk = new MemoryStream();
ClpkFormat.Write(clpk, zipBytes, new ClpkMetadata { Language = "pt-BR", Author = "test" });
clpk.Position = 0;
Assert(ClpkFormat.TryReadHeader(clpk, out var metadata, out _, out _), "existing CLPK v1 format failed");
Assert(metadata?.Language == "pt-BR", "CLPK language changed unexpectedly");

var packTemp = Path.Combine(Path.GetTempPath(), $"dqxclarity-local-pack-test-{Guid.NewGuid():N}");
Directory.CreateDirectory(packTemp);
try
{
    var packPath = Path.Combine(packTemp, "pt-BR.clpk");
    File.WriteAllBytes(packPath, clpk.ToArray());
    var languagePacks = new LanguagePackService(packTemp);
    var installedPack = Path.Combine(languagePacks.GetSourceLanguagePacksFolder(), "pt-BR.clpk");
    File.Copy(packPath, installedPack);
    var scannedPack = languagePacks.ScanLanguagePacks().Single();
    Assert(scannedPack.CanActivate, "valid local language pack was rejected");
    Assert(scannedPack.Language == "pt-BR", "local language-pack identity was not preserved");

    var installDir = Path.Combine(packTemp, "game-install");
    var modsDir = Path.Combine(installDir, "Game", "mods");
    Directory.CreateDirectory(modsDir);
    var staleFile = Path.Combine(modsDir, "stale.dat");
    File.WriteAllText(staleFile, "test fixture only");

    var pack = new LanguagePack
    {
        Language = "pt-BR",
        Path = packPath,
        CanActivate = true,
    };
    var extracted = languagePacks.RebuildGameModsFolder(installDir, [pack]);
    Assert(extracted == 0, "empty test pack unexpectedly extracted a payload file");
    Assert(!File.Exists(staleFile), "Game mods folder was not rebuilt for the selected local pack");
}
finally
{
    Directory.Delete(packTemp, recursive: true);
}

Console.WriteLine("Launcher core tests passed.");
