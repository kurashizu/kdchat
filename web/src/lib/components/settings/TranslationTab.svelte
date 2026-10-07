<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Download from "@lucide/svelte/icons/download";
  import Search from "@lucide/svelte/icons/search";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Progress } from "$lib/components/ui/progress";
  import { Switch } from "$lib/components/ui/switch";
  import SettingRow from "../SettingRow.svelte";
  import TranslationControls from "../TranslationControls.svelte";
  import { app } from "$lib/app.svelte";
  import { ask } from "$lib/confirm.svelte";
  import { t, langTag } from "$lib/i18n.svelte";

  let q = $state("");
  const s = $derived(app.tr?.settings);
  const smallOk = $derived(new Set(app.tr?.small_ok ?? []));
  // the small font: the languages in use that it can write, and any already chosen
  const smallCand = $derived(s ? [...new Set([...s.targets, s.source === "auto" ? s.latin : s.source, "en", ...s.small])]
    .filter((c) => smallOk.has(c)) : []);
  const packs = $derived((app.tr?.languages ?? []).filter((l) => l.code !== "en")
    .filter((l) => !q || `${l.native} ${l.name} ${l.code}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(b.state === "ready") - Number(a.state === "ready") || a.name.localeCompare(b.name)));
  const pct = (l: { done?: number; total?: number }) => (l.total ? Math.floor((100 * (l.done ?? 0)) / l.total) : 0);
  const h3 = "text-muted-foreground mt-6 mb-1 text-xs font-semibold tracking-wide uppercase";

  async function del(code: string) {
    if (await ask({ title: `${t("tr.delete")}: ${app.langName(code)}`, desc: t("tr.packsDesc"), action: t("tr.delete") })) app.deleteModel(code);
  }
</script>

<TranslationControls />

{#if s && app.kdAvailable && smallCand.length}
  <h3 class={h3}>{t("tr.small")}</h3>
  <p class="text-muted-foreground mb-1 text-xs">{t("tr.smallDesc")}</p>
  <div class="divide-y">
    {#each smallCand as code (code)}
      <SettingRow label={app.langName(code)}>
        <Switch checked={s.small.includes(code)} aria-label={app.langName(code)}
          onCheckedChange={(v) => app.setTr({ small: v ? [...s.small, code] : s.small.filter((x) => x !== code) })} />
      </SettingRow>
    {/each}
  </div>
{/if}

<h3 class={h3}>{t("tr.packs")}</h3>
<p class="text-muted-foreground mb-3 text-xs">{t("tr.packsDesc")}</p>
<div class="relative mb-2">
  <Search class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
  <Input bind:value={q} placeholder={t("tr.search")} class="pl-8" />
</div>
<ul class="divide-y rounded-lg border">
  {#each packs as l (l.code)}
    <li class="flex items-center gap-3 px-3 py-2">
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium" lang={langTag(l.code)}>{l.native}</p>
        {#if l.native !== l.name}<p class="text-muted-foreground truncate text-xs">{l.name}</p>{/if}
      </div>
      {#if l.state === "downloading"}
        <div class="flex w-32 items-center gap-2">
          <Progress value={pct(l)} class="h-1.5" />
          <span class="text-muted-foreground w-9 text-right text-xs tabular-nums">{pct(l)}%</span>
        </div>
      {:else if l.state === "ready"}
        <span class="text-primary flex items-center gap-1 text-xs"><Check class="size-3.5" />{t("tr.ready")}</span>
        <Button size="icon-sm" variant="ghost" aria-label={t("tr.delete")} title={t("tr.delete")} onclick={() => del(l.code)}><Trash2 /></Button>
      {:else}
        {#if l.state === "error"}
          <span class="text-destructive flex max-w-40 items-center gap-1 truncate text-xs" title={l.error}><TriangleAlert class="size-3.5 shrink-0" />{l.error ?? "error"}</span>
        {:else}
          <span class="text-muted-foreground text-xs tabular-nums">{Math.round((l.size ?? 0) / 1e6)} MB</span>
        {/if}
        <Button size="sm" variant="outline" onclick={() => app.download(l.code)}>
          <Download />{t(l.state === "error" ? "tr.retry" : "tr.download")}</Button>
      {/if}
    </li>
  {:else}
    <li class="text-muted-foreground px-3 py-6 text-center text-sm">{t("tr.noResult")}</li>
  {/each}
</ul>
