<script lang="ts">
  // the translation settings that matter while chatting (also in the main screen's quick popover: compact)
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Progress } from "$lib/components/ui/progress";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import LanguagePicker from "./LanguagePicker.svelte";
  import SettingRow from "./SettingRow.svelte";
  import { app } from "$lib/app.svelte";
  import { t, langTag } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  let { compact = false }: { compact?: boolean } = $props();

  const s = $derived(app.tr?.settings);
  const langs = $derived(app.tr?.languages ?? []);
  // (scripts that are never "Latin")
  const NON_LATIN = ["zh", "zh_hant", "ja", "ko", "ru", "uk", "bg", "ar", "fa", "ur", "he", "th", "el", "hi", "mr", "bn", "ta", "te", "kn", "ml", "gu", "sr"];
  const latinLangs = $derived(langs.filter((l) => !NON_LATIN.includes(l.code)));
  const pct = (code: string) => {
    const l = app.lang(code);
    return l?.total ? Math.floor((100 * (l.done ?? 0)) / l.total) : 0;
  };
  const sourceLabel = $derived(s?.source === "auto" ? t("tr.auto") : app.langName(s?.source ?? ""));

  function addTarget(code: string) {
    if (!s || s.targets.includes(code)) return;
    app.setTr({ targets: [...s.targets, code].slice(0, 2), enabled: true });
  }
  function removeTarget(code: string) {
    if (!s) return;
    app.setTr({ targets: s.targets.filter((x) => x !== code) });
  }
</script>

{#if s}
  <div class={cn("divide-y", compact && "text-sm")}>
    <SettingRow label={t("tr.enable")} desc={compact ? "" : t("tr.desc")}>
      <Switch checked={s.enabled} onCheckedChange={(v) => app.setTr({ enabled: v })} aria-label={t("tr.enable")} />
    </SettingRow>

    <div class={cn("space-y-3 py-3", !s.enabled && "opacity-50")}>
      <div class="space-y-0.5">
        <p class="text-sm font-medium leading-none">{t("tr.targets")}</p>
        <p class="text-muted-foreground text-xs">{t("tr.targetsDesc")}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        {#each s.targets as code, i (code)}
          {@const l = app.lang(code)}
          <div class="bg-muted/50 flex min-w-0 items-center gap-2 rounded-lg border py-1 pr-1 pl-2.5">
            <span class="text-muted-foreground text-[10px] font-semibold uppercase">{s.targets.length === 1 ? "R" : i === 0 ? "L" : "R"}</span>
            <span class="truncate text-sm font-medium">{app.langName(code)}</span>
            {#if l?.state === "downloading"}
              <span class="text-muted-foreground flex items-center gap-1 text-xs tabular-nums">
                <LoaderCircle class="size-3.5 animate-spin" />{pct(code)}%</span>
            {:else if l && l.state !== "ready"}
              <Button size="xs" variant="secondary" onclick={() => app.download(code)}>
                {#if l.state === "error"}<TriangleAlert />{t("tr.retry")}{:else}{t("tr.download")}{/if}
              </Button>
            {/if}
            <Button size="icon-xs" variant="ghost" aria-label={t("tr.remove", { name: app.langName(code) })} onclick={() => removeTarget(code)}>
              <X />
            </Button>
          </div>
        {/each}
        {#if s.targets.length < 2}
          <LanguagePicker exclude={[...s.targets, s.source === "auto" ? "" : s.source]} onPick={addTarget} />
        {/if}
      </div>
      {#each s.targets.filter((c) => app.lang(c)?.state === "downloading") as code (code)}
        <Progress value={pct(code)} class="h-1" />
      {/each}
    </div>

    <SettingRow label={t("tr.source")} desc={compact ? "" : ""}>
      <Select.Root type="single" value={s.source} onValueChange={(v) => app.setTr({ source: v })}>
        <Select.Trigger size="sm" class="w-48">{sourceLabel}</Select.Trigger>
        <Select.Content class="max-h-72">
          <Select.Item value="auto">{t("tr.auto")}</Select.Item>
          {#each langs as l (l.code)}<Select.Item value={l.code} lang={langTag(l.code)}>{l.native}</Select.Item>{/each}
        </Select.Content>
      </Select.Root>
    </SettingRow>
    {#if s.source === "auto" && !compact}
      <SettingRow label={t("tr.latin")} desc={t("tr.latinDesc")}>
        <Select.Root type="single" value={s.latin} onValueChange={(v) => app.setTr({ latin: v })}>
          <Select.Trigger size="sm" class="w-48">{app.langName(s.latin)}</Select.Trigger>
          <Select.Content class="max-h-72">
            {#each latinLangs as l (l.code)}<Select.Item value={l.code} lang={langTag(l.code)}>{l.native}</Select.Item>{/each}
          </Select.Content>
        </Select.Root>
      </SettingRow>
    {/if}

    <SettingRow label={t("tr.chatbox")} desc={compact ? "" : t("tr.chatboxDesc")}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={String(s.chatbox)}
        onValueChange={(v) => v && app.setTr({ chatbox: Number(v) })}>
        <ToggleGroup.Item value="0">{t("tr.cb0")}</ToggleGroup.Item>
        <ToggleGroup.Item value="1">{t("tr.cb1")}</ToggleGroup.Item>
        <ToggleGroup.Item value="2">{t("tr.cb2")}</ToggleGroup.Item>
      </ToggleGroup.Root>
    </SettingRow>

    {#if app.kdAvailable}
      <SettingRow label={t("tr.kd")} desc={compact ? "" : t("tr.kdDesc")}>
        <Switch checked={s.kd} onCheckedChange={(v) => app.setTr({ kd: v })} aria-label={t("tr.kd")} />
      </SettingRow>
    {/if}
  </div>
{/if}
