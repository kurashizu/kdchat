<script lang="ts">
  import Bell from "@lucide/svelte/icons/bell";
  import Eraser from "@lucide/svelte/icons/eraser";
  import ImageOff from "@lucide/svelte/icons/image-off";
  import ImagePlus from "@lucide/svelte/icons/image-plus";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import MonitorSmartphone from "@lucide/svelte/icons/monitor-smartphone";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { app } from "$lib/app.svelte";
  import { ACCEPT } from "$lib/decode";
  import { store } from "$lib/api";
  import { cn } from "$lib/utils";
  import { t } from "$lib/i18n.svelte";

  let { phone = false }: { phone?: boolean } = $props();
  let file = $state<HTMLInputElement>(null!);
  // phones: the card can fold to its header (the messages get the room); remembered
  let folded = $state(store.get("kdFolded", false));
  const fold = (v: boolean) => { folded = v; store.set("kdFolded", v); };
  let dims = $state<[number, number] | null>(null);

  const st = $derived(app.kdStat);
  const ks = $derived(app.kd?.settings);
  const tr = $derived(app.tr?.settings);
  // which language each side screen shows (one language: the right one)
  const sides = $derived.by(() => {
    if (!tr?.enabled || !tr.kd || !tr.targets.length) return null;
    const [a, b] = tr.targets;
    return b ? { l: app.langName(a), r: app.langName(b) } : { l: "—", r: app.langName(a) };
  });

  function loaded(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    dims = [img.naturalWidth / 2, img.naturalHeight / 2]; // (rendered at 2x)
  }
</script>

<Card.Root class="gap-0 py-0">
  <Card.Header class="flex flex-row items-center gap-2 border-b px-4 !py-3">
    <MonitorSmartphone class="text-muted-foreground size-4" />
    <Card.Title class="text-sm">{t("kd.title")}</Card.Title>
    {#if app.out.kd && st}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <Badge {...props} variant="outline" class="gap-1.5 font-normal">
              {#if st.synced}<span class="size-1.5 rounded-full bg-emerald-500"></span>{t("kd.synced")}
              {:else}<LoaderCircle class="size-3 animate-spin" />{t("kd.syncing", { s: Math.ceil(st.eta_s) })}{/if}
            </Badge>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{st.synced ? `${st.width}x${st.height}` : t("kd.syncTip", { p: st.pending_pages })}</Tooltip.Content>
      </Tooltip.Root>
    {/if}
    <Button variant="ghost" size="icon-sm" class="ml-auto" aria-label={t("kd.more")} title={t("kd.more")}
      onclick={() => app.openSettings("display")} disabled={!app.kdAvailable}>
      <SlidersHorizontal />
    </Button>
    {#if phone && app.out.kd}
      <Button variant="ghost" size="icon-sm" aria-label={t(folded ? "kd.expand" : "kd.collapse")} aria-expanded={!folded}
        onclick={() => fold(!folded)}><ChevronDown class={cn("transition-transform", !folded && "rotate-180")} /></Button>
    {/if}
  </Card.Header>

  {#if !app.out.kd}
    <Card.Content class="flex flex-col items-center gap-3 px-6 py-8 text-center">
      <div class="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-full">
        <MonitorSmartphone class="size-5" />
      </div>
      <div class="space-y-1">
        <p class="text-sm font-medium">{t("kd.off")}</p>
        <p class="text-muted-foreground text-xs">{app.kdAvailable ? t("kd.offDesc") : t("out.unavailable")}</p>
      </div>
      {#if app.kdAvailable}<Button size="sm" onclick={() => app.setOutput("kd", true)}>{t("kd.turnOn")}</Button>{/if}
    </Card.Content>
  {:else if !(phone && folded)}
    <Card.Content class="space-y-4 p-4">
      <div class="flex justify-center rounded-lg bg-[#0b0b0d] p-2 ring-1 ring-black/10 dark:ring-white/10">
        {#if app.previewUrl}
          <img src={app.previewUrl} alt={t("kd.previewAlt")} onload={loaded}
            class="block h-auto max-h-60 w-full max-w-full object-contain [image-rendering:pixelated]"
            style={dims ? `aspect-ratio: ${dims[0]} / ${dims[1]}` : "aspect-ratio: 176 / 96"} />
        {:else}
          <div class="aspect-[176/96] w-full"></div>
        {/if}
      </div>
      {#if app.kdError}<p class="text-destructive text-xs">{t("kd.unavailable", { msg: app.kdError })}</p>{/if}

      {#if ks}
        <div class="grid gap-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <Tooltip.Root>
              <Tooltip.Trigger class="text-sm font-medium">{t("kd.wings")}</Tooltip.Trigger>
              <Tooltip.Content class="max-w-64">{t("kd.wingsTip")}</Tooltip.Content>
            </Tooltip.Root>
            <ToggleGroup.Root type="single" variant="outline" size="sm" value={ks.wings}
              onValueChange={(v) => v && app.setKd({ wings: v })}>
              {#each ["auto", "on", "off"] as w (w)}
                <ToggleGroup.Item value={w}>{t(`wings.${w}` as any)}</ToggleGroup.Item>
              {/each}
            </ToggleGroup.Root>
          </div>
          {#if ks.wings !== "off"}
            <p class="text-muted-foreground -mt-1 text-xs">{sides ? t("kd.wingsAssign", sides) : t("kd.wingsNone")}</p>
          {/if}
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="text-sm font-medium">{t("kd.layout")}</span>
            <ToggleGroup.Root type="single" variant="outline" size="sm" value={ks.layout}
              onValueChange={(v) => v && app.setKd({ layout: v })}>
              <ToggleGroup.Item value="chat">{t("layout.chat")}</ToggleGroup.Item>
              <ToggleGroup.Item value="single">{t("layout.single")}</ToggleGroup.Item>
            </ToggleGroup.Root>
          </div>
        </div>
      {/if}

      <div class="flex flex-wrap gap-2 border-t pt-3">
        <Button variant="secondary" size="sm" onclick={() => app.kdAction("/kd/chime", "kd.chimed")}><Bell />{t("kd.chime")}</Button>
        <Button variant="secondary" size="sm" title={t("kd.imageTip")} onclick={() => file.click()}><ImagePlus />{t("kd.image")}</Button>
        {#if st?.image || st?.images?.length}
          <Button variant="secondary" size="sm" onclick={() => app.kdAction("/kd/image", undefined, "DELETE")}><ImageOff />{t("kd.closeImg")}</Button>
        {/if}
        <Button variant="ghost" size="sm" class="ml-auto" onclick={() => app.kdAction("/kd/clear", "kd.cleared")}><Eraser />{t("kd.clear")}</Button>
        <input bind:this={file} type="file" accept={ACCEPT} hidden
          onchange={(e) => { const i = e.currentTarget; app.sendImage(i.files?.[0]); i.value = ""; }} />
      </div>
    </Card.Content>
  {/if}
</Card.Root>
