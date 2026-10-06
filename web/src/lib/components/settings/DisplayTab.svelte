<script lang="ts">
  import Ban from "@lucide/svelte/icons/ban";
  import Check from "@lucide/svelte/icons/check";
  import * as Select from "$lib/components/ui/select";
  import { Slider } from "$lib/components/ui/slider";
  import { Switch } from "$lib/components/ui/switch";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import SettingRow from "../SettingRow.svelte";
  import { app } from "$lib/app.svelte";
  import { colorName, opt, t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  $effect(() => { if (!app.kd && app.kdAvailable) app.loadKd(); });
  const s = $derived(app.kd?.settings);
  const ch = $derived(app.kd?.choices ?? {});
  const palette = $derived(app.kdStat?.palette ?? []);
  const single = $derived(s?.layout === "single");
  const SHOW = ["clock", "date", "show_time", "divider", "highlight", "invert", "image_full"];
  const COLORS = ["color", "alt", "accent", "meta"];
  let size = $state(40);
  $effect(() => { if (s) size = Math.round(s.size * 100); });
  const h3 = "text-muted-foreground mt-6 mb-1 text-xs font-semibold tracking-wide uppercase";
</script>

{#if !app.kdAvailable}
  <p class="text-muted-foreground py-6 text-sm">{t("out.unavailable")}</p>
{:else if !s}
  <p class="text-muted-foreground py-6 text-sm">{app.kdError ? t("kd.unavailable", { msg: app.kdError }) : "…"}</p>
{:else}
  <div class="divide-y">
    <SettingRow label={t("set.screen")}>
      <Select.Root type="single" value={s.screen} onValueChange={(v) => app.setKd({ screen: v })}>
        <Select.Trigger size="sm" class="w-48">{opt("screen", s.screen)}</Select.Trigger>
        <Select.Content>
          {#each ch.screen ?? [] as v (v)}<Select.Item value={v}>{opt("screen", v)}</Select.Item>{/each}
        </Select.Content>
      </Select.Root>
    </SettingRow>
    <SettingRow label={t("set.layout")}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={s.layout} onValueChange={(v) => v && app.setKd({ layout: v })}>
        {#each ch.layout ?? ["chat", "single"] as v (v)}<ToggleGroup.Item value={v}>{opt("layout", v)}</ToggleGroup.Item>{/each}
      </ToggleGroup.Root>
    </SettingRow>
    <SettingRow label={t("set.scale")}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={String(s.scale)} onValueChange={(v) => v && app.setKd({ scale: Number(v) })}>
        {#each ch.scale ?? [1, 2] as v (v)}<ToggleGroup.Item value={String(v)}>{opt("scale", v)}</ToggleGroup.Item>{/each}
      </ToggleGroup.Root>
    </SettingRow>
    <SettingRow label={t("set.size")} desc={t("set.sizeDesc")}>
      <div class="flex w-56 items-center gap-3">
        <Slider type="single" min={20} max={60} step={1} bind:value={size} onValueCommit={(v) => app.setKd({ size: v / 100 })} />
        <span class="text-muted-foreground w-14 shrink-0 text-right text-sm whitespace-nowrap tabular-nums">{size} cm</span>
      </div>
    </SettingRow>
    <SettingRow label={t("set.wings")} desc={t("kd.wingsTip")}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={s.wings} onValueChange={(v) => v && app.setKd({ wings: v })}>
        {#each ch.wings ?? ["auto", "on", "off"] as v (v)}<ToggleGroup.Item value={v}>{opt("wings", v)}</ToggleGroup.Item>{/each}
      </ToggleGroup.Root>
    </SettingRow>
    <SettingRow label={t("set.long")} desc={single ? "" : t("set.onlySingle")} disabled={!single}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={s.long} disabled={!single} onValueChange={(v) => v && app.setKd({ long: v })}>
        {#each ch.long ?? [] as v (v)}<ToggleGroup.Item value={v}>{opt("long", v)}</ToggleGroup.Item>{/each}
      </ToggleGroup.Root>
    </SettingRow>
    <SettingRow label={t("set.speed")} desc={single ? "" : t("set.onlySingle")} disabled={!single}>
      <ToggleGroup.Root type="single" variant="outline" size="sm" value={s.speed} disabled={!single} onValueChange={(v) => v && app.setKd({ speed: v })}>
        {#each ch.speed ?? [] as v (v)}<ToggleGroup.Item value={v}>{opt("speed", v)}</ToggleGroup.Item>{/each}
      </ToggleGroup.Root>
    </SettingRow>
  </div>

  <h3 class={h3}>{t("set.show")}</h3>
  <div class="divide-y">
    {#each SHOW.filter((k) => k in s) as k (k)}
      <SettingRow label={t(`chip.${k}` as any)} desc={t(`chip.${k}Desc` as any)}>
        <Switch checked={!!s[k]} onCheckedChange={(v) => app.setKd({ [k]: v })} aria-label={t(`chip.${k}` as any)} />
      </SettingRow>
    {/each}
  </div>

  <h3 class={h3}>{t("set.colors")}</h3>
  <div class="divide-y">
    {#each COLORS.filter((k) => k in s) as k (k)}
      <SettingRow label={t(`color.${k}` as any)} desc={s[k] ? colorName(s[k]) : t("set.off")}>
        <div class="flex max-w-80 flex-wrap gap-1.5" role="radiogroup" aria-label={t(`color.${k}` as any)}>
          {#if k === "alt"}
            <button type="button" role="radio" aria-checked={s.alt === 0} aria-label={t("set.off")} title={t("set.off")}
              onclick={() => app.setKd({ alt: 0 })}
              class={cn("text-muted-foreground flex size-6 items-center justify-center rounded-md border", s.alt === 0 && "ring-ring ring-2 ring-offset-1 ring-offset-background")}>
              <Ban class="size-3.5" /></button>
          {/if}
          {#each Array.from({ length: 14 }, (_, i) => i + 1) as i (i)}
            <button type="button" role="radio" aria-checked={s[k] === i} aria-label={colorName(i)} title={colorName(i)}
              onclick={() => app.setKd({ [k]: i })} style={`background:${palette[i] ?? "#888"}`}
              class={cn("flex size-6 items-center justify-center rounded-md border border-black/20", s[k] === i && "ring-ring ring-2 ring-offset-1 ring-offset-background")}>
              {#if s[k] === i}<Check class="size-3.5 text-white mix-blend-difference" />{/if}
            </button>
          {/each}
        </div>
      </SettingRow>
    {/each}
  </div>

  <h3 class={h3}>{t("set.images")}</h3>
  <div class="divide-y">
    {#each [["image_fit", "img.fit", ["cover", "contain"]], ["image_screen", "img.screen", ["auto", "keep"]], ["image_res", "img.res", ["high", "low"]]] as [k, label, vals] (k)}
      <SettingRow label={t(label as any)}>
        <ToggleGroup.Root type="single" variant="outline" size="sm" value={s[k as string]} onValueChange={(v) => v && app.setKd({ [k as string]: v })}>
          {#each vals as v (v)}<ToggleGroup.Item value={v}>{t(`img.${v}` as any)}</ToggleGroup.Item>{/each}
        </ToggleGroup.Root>
      </SettingRow>
    {/each}
  </div>
{/if}
