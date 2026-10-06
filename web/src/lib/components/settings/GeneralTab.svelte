<script lang="ts">
  import Monitor from "@lucide/svelte/icons/monitor";
  import Moon from "@lucide/svelte/icons/moon";
  import Sun from "@lucide/svelte/icons/sun";
  import { mode, setMode, userPrefersMode } from "mode-watcher";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import SettingRow from "../SettingRow.svelte";
  import { app } from "$lib/app.svelte";
  import { i18n, setLang, t, type Lang } from "$lib/i18n.svelte";

  const LANGS: [Lang, string][] = [["en", "English"], ["zh", "中文"]];
  const prefs = [
    ["live", "gen.live", "gen.liveDesc"],
    ["typingHint", "gen.typing", "gen.typingDesc"],
    ["sfx", "gen.sfx", "gen.sfxDesc"],
    ["enterSends", "gen.enter", "gen.enterDesc"],
  ] as const;
  void mode;
</script>

<div class="divide-y">
  <SettingRow label={t("gen.language")}>
    <Select.Root type="single" value={i18n.lang} onValueChange={(v) => setLang(v as Lang)}>
      <Select.Trigger size="sm" class="w-40">{LANGS.find(([k]) => k === i18n.lang)?.[1]}</Select.Trigger>
      <Select.Content>
        {#each LANGS as [k, name] (k)}<Select.Item value={k} lang={k === "zh" ? "zh-CN" : "en"}>{name}</Select.Item>{/each}
      </Select.Content>
    </Select.Root>
  </SettingRow>
  <SettingRow label={t("gen.theme")}>
    <ToggleGroup.Root type="single" variant="outline" size="sm" value={userPrefersMode.current}
      onValueChange={(v) => v && setMode(v as "system" | "light" | "dark")}>
      <ToggleGroup.Item value="system"><Monitor />{t("gen.themeSystem")}</ToggleGroup.Item>
      <ToggleGroup.Item value="light"><Sun />{t("gen.themeLight")}</ToggleGroup.Item>
      <ToggleGroup.Item value="dark"><Moon />{t("gen.themeDark")}</ToggleGroup.Item>
    </ToggleGroup.Root>
  </SettingRow>
</div>

<h3 class="text-muted-foreground mt-6 mb-1 text-xs font-semibold tracking-wide uppercase">{t("gen.sending")}</h3>
<div class="divide-y">
  {#each prefs as [key, label, desc] (key)}
    <SettingRow desc={t(desc)} label={t(label)}>
      <Switch checked={app[key]} onCheckedChange={(v) => app.setPref(key, v)} aria-label={t(label)} />
    </SettingRow>
  {/each}
</div>
