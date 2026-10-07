<script lang="ts">
  // a searchable language list: installed packs first, the others show their download size; picking one that is not
  // installed starts its download at once
  import Check from "@lucide/svelte/icons/check";
  import Download from "@lucide/svelte/icons/download";
  import Plus from "@lucide/svelte/icons/plus";
  import { tick } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Command from "$lib/components/ui/command";
  import * as Popover from "$lib/components/ui/popover";
  import { app, type Language } from "$lib/app.svelte";
  import { t, langTag } from "$lib/i18n.svelte";

  let { exclude = [], onPick, label = undefined, size = "sm" }:
    { exclude?: string[]; onPick: (code: string) => void; label?: string; size?: "sm" | "default" } = $props();

  let open = $state(false);
  let triggerRef = $state<HTMLButtonElement>(null!);

  const langs = $derived((app.tr?.languages ?? []).filter((l) => !exclude.includes(l.code)));
  const ready = $derived(langs.filter((l) => l.state === "ready"));
  const other = $derived(langs.filter((l) => l.state !== "ready").sort((a, b) => a.name.localeCompare(b.name)));

  function pick(l: Language) {
    open = false;
    if (l.state !== "ready" && l.state !== "downloading") app.download(l.code);
    onPick(l.code);
    tick().then(() => triggerRef?.focus());
  }
  const mb = (l: Language) => Math.round((l.size ?? 0) / 1e6);
  const noDisplay = $derived(new Set(app.tr?.no_display ?? []));
</script>

<Popover.Root bind:open>
  <Popover.Trigger bind:ref={triggerRef}>
    {#snippet child({ props })}
      <Button {...props} variant="outline" {size} class="border-dashed">
        <Plus />{label ?? t("tr.add")}
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-72 p-0" align="start">
    <Command.Root>
      <Command.Input placeholder={t("tr.search")} autofocus />
      <Command.List class="max-h-72">
        <Command.Empty>{t("tr.noResult")}</Command.Empty>
        {#if ready.length}
          <Command.Group heading={t("tr.installed")}>
            {#each ready as l (l.code)}
              <Command.Item value={`${l.native} ${l.name} ${l.code}`} onSelect={() => pick(l)}>
                <span class="flex min-w-0 flex-1 items-baseline gap-2"><span class="truncate" lang={langTag(l.code)}>{l.native}</span>
                  <span class="text-muted-foreground truncate text-xs">{l.native === l.name ? "" : l.name}</span>
                  {#if noDisplay.has(l.code)}<span class="text-muted-foreground shrink-0 text-[10px]" title={t("tr.noDisplayTip")}>{t("tr.noDisplay")}</span>{/if}</span>
                <Check class="text-primary" />
              </Command.Item>
            {/each}
          </Command.Group>
        {/if}
        {#if other.length}
          <Command.Group heading={t("tr.available")}>
            {#each other as l (l.code)}
              <Command.Item value={`${l.native} ${l.name} ${l.code}`} onSelect={() => pick(l)}>
                <span class="flex min-w-0 flex-1 items-baseline gap-2"><span class="truncate" lang={langTag(l.code)}>{l.native}</span>
                  <span class="text-muted-foreground truncate text-xs">{l.native === l.name ? "" : l.name}</span>
                  {#if noDisplay.has(l.code)}<span class="text-muted-foreground shrink-0 text-[10px]" title={t("tr.noDisplayTip")}>{t("tr.noDisplay")}</span>{/if}</span>
                <span class="text-muted-foreground flex shrink-0 items-center gap-1 text-xs tabular-nums">
                  <Download class="size-3.5" />{mb(l)} MB
                </span>
              </Command.Item>
            {/each}
          </Command.Group>
        {/if}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
