<script lang="ts">
  // the main screen's translation shortcut: shows what happens now (off / into which languages), opens the controls
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Languages from "@lucide/svelte/icons/languages";
  import { Button } from "$lib/components/ui/button";
  import * as Popover from "$lib/components/ui/popover";
  import TranslationControls from "./TranslationControls.svelte";
  import { app } from "$lib/app.svelte";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  let open = $state(false);
  const s = $derived(app.tr?.settings);
  const on = $derived(!!s?.enabled && (s?.targets.length ?? 0) > 0);
  const tag = (c: string) => ({ zh: "ZH", zh_hant: "ZH-T" } as Record<string, string>)[c] ?? c.toUpperCase();
  const missing = $derived(on && s!.targets.some((c) => app.lang(c)?.state !== "ready"));
</script>

<Popover.Root bind:open onOpenChange={(o) => o && app.loadTr()}>
  <Popover.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" size="sm" title={t("tr.quickTip")}
        class={cn(on && "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15")}>
        <Languages />
        {#if on}
          <span class="font-medium tabular-nums">{s!.targets.map(tag).join(" · ")}</span>
          {#if missing}<span class="size-1.5 rounded-full bg-amber-500" aria-hidden="true"></span>{/if}
        {:else}
          <span>{t("tr.quickOff")}</span>
        {/if}
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-[min(26rem,calc(100vw-1.5rem))] p-0" align="start">
    <div class="px-4 pt-3">
      <p class="text-sm font-semibold">{t("tr.title")}</p>
      <p class="text-muted-foreground text-xs">{t("tr.desc")}</p>
    </div>
    <div class="px-4"><TranslationControls compact /></div>
    <div class="border-t p-1.5">
      <Button variant="ghost" size="sm" class="w-full justify-between"
        onclick={() => { open = false; app.openSettings("translation"); }}>
        {t("tr.manage")}<ChevronRight />
      </Button>
    </div>
  </Popover.Content>
</Popover.Root>
